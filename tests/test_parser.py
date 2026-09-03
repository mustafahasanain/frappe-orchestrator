#!/usr/bin/env python3
"""Tests for the delegation dispatcher's result contracts.

    python3 tests/test_parser.py

The parser is the one component of this plugin that fails silently. A missing CLI, a
malformed routing file, a wrong hook decision - all announce themselves. A parser that
returns the wrong object hands the orchestrator a plausible-looking report that nobody
questions, so it is the piece that earns coverage.

Two things beyond the parser earn it for the same reason, and both were added when
onboarding was given its own mode. The mode matrix is checked here because a mode
declared in one of the three tables and forgotten in the others fails at the point of use
rather than at the point of the mistake. And a verdict that no contract asked for is
checked here because it is the defect that motivated the mode: a FAIL that is a contract
artefact rather than a judgement is, where the orchestrator reads it, indistinguishable
from a real one.

The hook earns coverage for the opposite reason to the one first assumed here. A hook
that denies the wrong command does announce itself. A hook that *allows* the wrong command
announces nothing at all - and it can do that because its rule data became unusable, or
because it faulted and Claude Code treats a crashed hook as a non-blocking error and runs
the command anyway. Both were reachable and neither was visible, so the hook's real entry
point is exercised here as a process, payload on stdin, exactly as Claude Code runs it.

Two fixtures are real captured stdout from `codex exec`, not invented samples. The
inner-fence one is the output that broke the previous parser: its own `detail` string
contains a fenced example, and a regex delimiting a block on triple backticks truncates
the body there. A tidier stub is exactly how that defect survived.

No framework and nothing to install: standard library only.
"""

import fnmatch
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_dispatcher():
    """Import scripts/delegate, which has no .py extension, without running it."""
    path = ROOT / "scripts" / "delegate"
    loader = importlib.machinery.SourceFileLoader("delegate", str(path))
    spec = importlib.util.spec_from_loader("delegate", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def load_module(path, name):
    """Import a file that has no .py extension, without running it."""
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def fixture(name):
    return (FIXTURES / name).read_text()


d = load_dispatcher()
g = load_module(ROOT / "hooks" / "guard.py", "guard")
BOUNDARIES = json.loads((ROOT / "config" / "command-boundaries.json").read_text())
BOUNDARY_FILE = ROOT / "config" / "command-boundaries.json"
GUARD = ROOT / "hooks" / "guard.py"
extract = d.extract_report

BANNER = "OpenAI Codex v0.149.0\n--------\nmodel: gpt-5.6-sol\n--------\n"
FOOTER = "\ntokens used\n10,078\n"
BLOCK = '```json\n{"verdict": "PASS", "summary": "s", "findings": []}\n```'
DEEP = '{"a":' * 10000 + "1" + "}" * 10000

ONBOARD = ('{"analysis": "complete", "summary": "s", "findings": [], '
           '"uncertain": []}')

# Longer than the parser will decode, so an enclosing report built around it cannot be
# recovered even when its opening brace is in view - which is the point: the question
# "is this candidate a field of a larger report" then has no answer, and an unanswered
# question about that must not read as "no".
OVERSIZED_PAD = "x" * (d.MAX_REPORT_CHARS + 5000)

# Ordinary CLI chatter, comfortably past the same bound, carrying no braces.
LONG_TRANSCRIPT = "opencode: reading src/pricing.py\n" * 9000

# The same length, full of JSON, which is what an agent transcript actually looks like.
# Nothing before the report can be ruled out cheaply here.
BRACEY_TRANSCRIPT = '{"tool":"read","path":"src/pricing.py","ok":true}\n' * 6000


def enclosed_late(outer, inner, key="verdict"):
    """An enclosing report too long to decode, with a qualifying object near its end."""
    return ('{"%s":"%s","summary":"%s","previous_run":{"%s":"%s","summary":"old"}}'
            % (key, outer, OVERSIZED_PAD, key, inner))


def enclosed_early(outer, inner, key="verdict"):
    """The same, with the qualifying object at the front.

    A different bound hides the enclosing report here: its brace is inside the search
    window, and it is the per-candidate decode slice that cuts it short. Same outcome,
    reached another way, which is why both are in the table.
    """
    return ('{"previous_run":{"%s":"%s","summary":"old"},"%s":"%s","padding":"%s"}'
            % (key, inner, key, outer, OVERSIZED_PAD))

# (name, mode, text, expected state, expected discriminator value or None)
# The discriminator compared is the mode's own, read from the dispatcher, so a mode with a
# different key needs no special case here.
CASES = [
    # --- real captured output ---------------------------------------------
    ("real codex output", "review", fixture("codex-review-clean.txt"), "present", "PASS"),
    ("real output, fence inside a string value", "review",
     fixture("codex-review-inner-fence.txt"), "present", "FAIL"),

    # --- shapes a CLI can wrap the report in -------------------------------
    ("banner and footer on the same stream", "review", BANNER + BLOCK + FOOTER, "present", "PASS"),
    ("prose either side of the block", "review", "Review:\n\n" + BLOCK + "\n\nDone.", "present", "PASS"),
    ("no fence at all", "review", BANNER + '{"verdict":"BLOCKED","summary":"s"}' + FOOTER,
     "present", "BLOCKED"),

    # --- fences are not parsed, so none of these can matter ----------------
    ("untagged fence", "review", '```\n{"verdict":"FAIL","summary":"s"}\n```', "present", "FAIL"),
    ("multiword info string", "review", '```json result\n{"verdict":"PASS","summary":"s"}\n```',
     "present", "PASS"),
    ("unterminated fence", "review", '```json\n{"verdict":"PASS","summary":"s"}', "present", "PASS"),
    ("braces and backticks inside a string", "review",
     '{"verdict":"PASS","summary":"see {a:1} and ```x"}', "present", "PASS"),

    # --- selection ---------------------------------------------------------
    ("last report wins", "review", '{"verdict":"FAIL","summary":"a"}\n' + BLOCK, "present", "PASS"),
    ("report nested in a wrapper is found", "review",
     '{"wrapper":{"verdict":"PASS","summary":"n"}}', "present", "PASS"),
    ("discriminator compared casefolded", "review", '{"verdict":"pass","summary":"s"}',
     "present", "pass"),

    # --- a report nested in a report is a field of it, not a replacement ----
    # The innermost object is what a backwards scan reaches first, so each of these was
    # answered with the quoted value and the real report was thrown away.
    ("review FAIL quoting an earlier PASS", "review",
     '{"verdict":"FAIL","summary":"blocking issue found",'
     '"previous_run":{"verdict":"PASS","summary":"old"}}', "present", "FAIL"),
    ("review FAIL with a PASS in context", "review",
     '{"verdict":"FAIL","summary":"s","findings":["blocking problem"],'
     '"context":{"verdict":"PASS"}}', "present", "FAIL"),
    # The reverse, so the rule cannot be "the worse verdict wins": structure decides,
    # and an enclosing PASS keeps its own verdict over a nested FAIL.
    ("review PASS quoting an earlier FAIL", "review",
     '{"verdict":"PASS","summary":"clean","previous_run":{"verdict":"FAIL"}}',
     "present", "PASS"),
    ("nested in an array inside the report", "review",
     '{"verdict":"FAIL","history":[{"verdict":"PASS"}]}', "present", "FAIL"),
    ("three qualifying levels resolve to the outermost", "review",
     '{"verdict":"FAIL","a":{"verdict":"BLOCKED","b":{"verdict":"PASS"}}}',
     "present", "FAIL"),
    ("implement incomplete quoting a completed run", "implement",
     '{"status":"incomplete","summary":"could not finish","prior":{"status":"completed"}}',
     "present", None),
    ("onboard partial quoting a complete one", "onboard",
     '{"analysis":"partial","not_analysed":["tests"],"note":{"analysis":"complete"}}',
     "present", "partial"),
    ("a quoted verdict inside a string is still just a string", "review",
     '{"verdict":"FAIL","summary":"the earlier run said {\\"verdict\\":\\"PASS\\"}"}',
     "present", "FAIL"),

    # --- and the wrapper the contract has always tolerated still works -------
    ("wrapper whose own object is not a report", "review",
     '{"wrapper":{"verdict":"PASS","summary":"review complete"}}', "present", "PASS"),
    ("wrapper with a sibling that is not a report", "review",
     '{"metadata":{"foo":"bar"},"result":{"verdict":"FAIL","summary":"real report"}}',
     "present", "FAIL"),
    ("a later wrapped report still beats an earlier bare one", "review",
     '{"verdict":"FAIL","summary":"earlier"}\n'
     '{"wrap":{"verdict":"PASS","summary":"later"}}', "present", "PASS"),
    ("two independent reports: the later one wins", "review",
     '{"verdict":"FAIL","summary":"earlier"}\n{"verdict":"PASS","summary":"later"}',
     "present", "PASS"),

    # --- CLI JSON must not be mistaken for a report ------------------------
    ("connected/summary pair rejected", "review", '{"status":"connected","summary":"x"}',
     "missing", None),
    ("summary and findings without a verdict rejected", "review",
     '{"summary":"s","findings":[]}', "missing", None),
    ("off-contract verdict rejected", "review", '{"verdict":"PARTIAL","summary":"s"}',
     "missing", None),
    ("config JSON alone", "review", 'echo {"model":"x","port":8080}', "missing", None),
    ("telemetry after a real report does not displace it", "review",
     '{"verdict":"PASS","summary":"real"}\n{"status":"connected","summary":"tel"}',
     "present", "PASS"),

    # --- mode decides the discriminator ------------------------------------
    ("implement report", "implement", '{"status":"completed","summary":"s"}', "present", None),
    ("implement rejects a non-contract status", "implement",
     '{"status":"connected","summary":"s"}', "missing", None),
    ("a review report is not an implement report", "implement", BLOCK, "invalid", None),

    # --- onboard: a contract with no verdict -------------------------------
    ("onboard report", "onboard", ONBOARD, "present", "complete"),
    ("partial analysis is a report, not a failure", "onboard",
     '{"analysis":"partial","not_analysed":["tests"],"findings":[]}', "present", "partial"),
    ("onboard report in a banner", "onboard", BANNER + "```json\n" + ONBOARD + "\n```" + FOOTER,
     "present", "complete"),
    ("onboard discriminator compared casefolded", "onboard", '{"analysis":"COMPLETE"}',
     "present", "COMPLETE"),
    ("off-contract analysis value rejected", "onboard", '{"analysis":"PASS","summary":"s"}',
     "missing", None),
    ("a review report is not an onboard report", "onboard", BLOCK, "invalid", None),
    ("an implement report is not an onboard report", "onboard",
     '{"status":"completed","summary":"s"}', "missing", None),
    ("an onboard report is not a review report", "review", ONBOARD, "missing", None),
    ("an onboard report is not an implement report", "implement", ONBOARD, "missing", None),

    # --- states ------------------------------------------------------------
    ("fence present but nothing parses", "review", "```json\n{oops}\n```", "invalid", None),
    ("truncated JSON, no fence", "review", '{"verdict":', "missing", None),
    ("no JSON anywhere", "review", BANNER + "Could not review." + FOOTER, "missing", None),
    ("empty output", "review", "", "missing", None),

    # --- untrusted input must not raise ------------------------------------
    ("nesting past the recursion limit", "review", DEEP, "missing", None),
    ("real report after deep nesting", "review", DEEP + '{"verdict":"PASS","summary":"s"}',
     "present", "PASS"),

    # --- limits fail closed ------------------------------------------------
    ("report larger than MAX_REPORT_CHARS is dropped, not truncated", "review",
     '{"verdict":"PASS","summary":"%s"}' % ("x" * (d.MAX_REPORT_CHARS + 10)), "missing", None),
    ("report just inside MAX_REPORT_CHARS is kept", "review",
     '{"verdict":"PASS","summary":"%s"}' % ("x" * (d.MAX_REPORT_CHARS - 100)), "present", "PASS"),
    ("report behind more than MAX_DECODE_ATTEMPTS candidates is dropped", "review",
     '{"verdict":"PASS","summary":"s"}' + ("{x" * (d.MAX_DECODE_ATTEMPTS + 100)), "missing", None),
]

# Bounded-time checks. Thresholds are generous: this asserts the bounds exist, not that
# the machine is fast.
TIMED = [
    ("one million malformed candidates", "review", "{x" * 1000000, 3.0),
    ("compact hostile nesting", "review", '{"x":' * 20000 + "0" + "}" * 20000,
     d.MAX_SCAN_SECONDS + 3.0),
    ("hostile input with a real report at the end", "review",
     '{"x":' * 20000 + "0" + "}" * 20000 + '{"verdict":"PASS","summary":"s"}', 1.0),
    # The same input with the report written where something could enclose it - after a
    # string key, which is the one shape the cheap gate cannot rule out. This is what pays
    # for the enclosing scan, and it still has to finish inside the budget rather than
    # becoming a second, unbounded traversal of the transcript.
    ("hostile input with an enclosed report at the end", "review",
     '{"x":' * 20000 + "0" + "}" * 20000 + ',"k":{"verdict":"PASS","summary":"s"}',
     d.MAX_SCAN_SECONDS + 3.0),
]

# (name, mode, report in, keys expected removed, keys expected to survive)
# A verdict key is stripped in every mode whose contract has no verdict, not only in
# onboard: an implementer volunteering a verdict on its own work is the same defect.
STRIP = [
    ("onboard verdict is stripped", "onboard",
     {"analysis": "complete", "verdict": "FAIL", "findings": []},
     ["verdict"], ["analysis", "findings"]),
    ("onboard blocker_reason is stripped", "onboard",
     {"analysis": "partial", "blocker_reason": "no tests found"},
     ["blocker_reason"], ["analysis"]),
    ("both are stripped, and reported in order", "onboard",
     {"analysis": "complete", "blocker_reason": "x", "verdict": "PASS"},
     ["verdict", "blocker_reason"], ["analysis"]),
    ("implement verdict is stripped too", "implement",
     {"status": "completed", "verdict": "PASS"}, ["verdict"], ["status"]),
    ("a clean onboard report is untouched", "onboard",
     {"analysis": "complete", "findings": []}, [], ["analysis", "findings"]),
    ("review keeps its verdict", "review",
     {"verdict": "FAIL", "blocker_reason": None}, [], ["verdict", "blocker_reason"]),
    ("test keeps its verdict", "test", {"verdict": "BLOCKED"}, [], ["verdict"]),
    ("no report is not an error", "onboard", None, [], []),
]


# (name, mode, output, the entire report that must come back)
# The whole object, not its discriminator: a selection defect that returns the right
# verdict off the wrong object would pass a discriminator check, and losing `findings` is
# most of the damage. Comparing the object proves nothing was substituted and nothing was
# dropped.
NESTED_SELECTION = [
    ("the enclosing report keeps its summary", "review",
     '{"verdict":"FAIL","summary":"blocking issue found",'
     '"previous_run":{"verdict":"PASS","summary":"old"}}',
     {"verdict": "FAIL", "summary": "blocking issue found",
      "previous_run": {"verdict": "PASS", "summary": "old"}}),
    ("the enclosing report keeps its findings", "review",
     '{"verdict":"FAIL","summary":"s","findings":["blocking problem"],'
     '"context":{"verdict":"PASS"}}',
     {"verdict": "FAIL", "summary": "s", "findings": ["blocking problem"],
      "context": {"verdict": "PASS"}}),
    ("severity is not consulted in either direction", "review",
     '{"verdict":"PASS","summary":"clean","previous_run":{"verdict":"FAIL"}}',
     {"verdict": "PASS", "summary": "clean", "previous_run": {"verdict": "FAIL"}}),
    ("implement keeps its own status", "implement",
     '{"status":"incomplete","summary":"could not finish","prior":{"status":"completed"}}',
     {"status": "incomplete", "summary": "could not finish",
      "prior": {"status": "completed"}}),
    ("onboard keeps not_analysed", "onboard",
     '{"analysis":"partial","not_analysed":["tests"],"note":{"analysis":"complete"}}',
     {"analysis": "partial", "not_analysed": ["tests"],
      "note": {"analysis": "complete"}}),
    ("an enclosing object that is not a report yields the inner one", "review",
     '{"wrapper":{"verdict":"PASS","summary":"review complete"}}',
     {"verdict": "PASS", "summary": "review complete"}),
    ("a report reached through two non-report levels", "review",
     '{"envelope":{"result":{"verdict":"FAIL","summary":"real report"}}}',
     {"verdict": "FAIL", "summary": "real report"}),
    ("an independent later report is not a nested one", "review",
     '{"verdict":"FAIL","summary":"earlier"}\n{"verdict":"PASS","summary":"later"}',
     {"verdict": "PASS", "summary": "later"}),
    ("banner, prose and a fence around a report that quotes a verdict", "review",
     BANNER + "Review:\n\n```json\n"
     '{"verdict":"FAIL","summary":"s","earlier":{"verdict":"PASS"}}'
     "\n```\n\nDone." + FOOTER,
     {"verdict": "FAIL", "summary": "s", "earlier": {"verdict": "PASS"}}),
]


def check_nested_report_selection():
    """A report written inside another report is a field of it, never a replacement.

    The scan reaches the innermost object first, because that is the last one to start,
    so every shape here used to be answered with the quoted value and the enclosing report
    was discarded entirely - `{"verdict": "FAIL", ..., "previous_run": {"verdict":
    "PASS"}}` came back as a bare PASS with no findings. Where the orchestrator reads it,
    that is the difference between the fix loop and a commit, and it is not distinguishable
    from a review that really passed.

    Selection is therefore structural, which is what these assert in both directions: an
    enclosing PASS keeps its verdict over a nested FAIL exactly as an enclosing FAIL keeps
    its verdict over a nested PASS. A rule that preferred the worse verdict would satisfy
    half of this table and would be a different guess, not a fix.
    """
    failures = []
    for name, mode, text, want in NESTED_SELECTION:
        try:
            state, report = extract(text, mode)
        except Exception as exc:
            failures.append("%s: raised %s" % (name, type(exc).__name__))
            continue
        if state != "present":
            failures.append("%s: state %r, wanted present" % (name, state))
            continue
        if report != want:
            failures.append(
                "%s: returned %r, wanted %r" % (name, report, want)
            )
    return failures


# (name, mode, output, the value that must not come back)
# An enclosing report the parser cannot read is still an enclosing report. Each of these
# returned the nested value before the bounds were made to say so: the outer report is
# past MAX_REPORT_CHARS, so it is unusable either way, and the choice is between saying
# that and answering with one of its fields.
OVERSIZED_ENCLOSURE = [
    ("oversized FAIL quoting a PASS", "review",
     enclosed_late("FAIL", "PASS"), "PASS"),
    ("oversized PASS quoting a FAIL", "review",
     enclosed_late("PASS", "FAIL"), "FAIL"),
    ("the quoted object sits at the front instead", "review",
     enclosed_early("FAIL", "PASS"), "PASS"),
    ("implement: oversized incomplete quoting a completed run", "implement",
     enclosed_late("incomplete", "completed", "status"), "completed"),
    ("onboard: oversized partial quoting a complete one", "onboard",
     enclosed_late("partial", "complete", "analysis"), "complete"),
    # Stated as a decision rather than discovered later: past this size the parser cannot
    # tell a wrapper from an enclosing report it failed to read, and it refuses instead of
    # guessing. Wrapper tolerance loses to the verdict being right.
    ("an oversized wrapper that is not itself a report", "review",
     '{"log":"%s","result":{"verdict":"PASS","summary":"wrapped"}}' % OVERSIZED_PAD,
     "PASS"),
]

# (name, mode, output, the value that must come back)
# The other half, and the one that stops the rule above from being "long transcript, no
# report". Neither of these is enclosed by anything, at any length.
INDEPENDENT_AFTER_TRANSCRIPT = [
    ("a report after more transcript than the parser will decode", "review",
     LONG_TRANSCRIPT + '{"verdict":"PASS","summary":"clean"}', "PASS"),
    ("the same, introduced in prose ending in a colon", "review",
     LONG_TRANSCRIPT + 'Final report:\n{"verdict":"PASS","summary":"clean"}', "PASS"),
    ("the same, inside a fence", "review",
     LONG_TRANSCRIPT + '```json\n{"verdict":"FAIL","summary":"clean"}\n```', "FAIL"),
    ("prose ending in a quoted word and a colon", "review",
     LONG_TRANSCRIPT + 'wrote "result":\n{"verdict":"PASS","summary":"clean"}', "PASS"),
    # The one that pins the colon distinction. The transcripts above carry no braces, so
    # the window check alone rules out an enclosing object and the report survives either
    # way; a real agent transcript is full of them. Here nothing before the report can be
    # ruled out cheaply, and only "that colon ends a word, not a key" saves it.
    ("prose colon after a transcript that is itself full of JSON", "review",
     BRACEY_TRANSCRIPT + 'Final report:\n{"verdict":"PASS","summary":"clean"}', "PASS"),
    ("a fenced report after a transcript full of JSON", "review",
     BRACEY_TRANSCRIPT + '```json\n{"verdict":"FAIL","summary":"clean"}\n```', "FAIL"),
]

# (name, text ending just before the report, whether the report could be enclosed)
# The gate that decides which of the two tables above a shape lands in. A colon is the
# only one of the three that carries enough to tell prose from JSON: an object value has
# a string key in front of it, always, and a colon that ends a word ends a sentence.
ENCLOSURE_GATE = [
    ("start of text", "", False),
    ("after a newline", "banner\n", False),
    ("after a closing brace", '{"a":1}', False),
    ("after prose ending in a colon", "Final report:", False),
    ("after prose ending in a colon and a newline", "Final report:\n", False),
    ("after a string key and a colon", '{"result":', True),
    ("after a string key, a colon and spaces", '{"result": ', True),
    ("after an opening bracket", '{"history":[', True),
    ("after a comma", '{"history":[{"verdict":"PASS"},', True),
]


def check_oversized_enclosure():
    """A bound that hides an enclosing report must not clear the candidate inside it.

    Slice 2 asked whether a qualifying ancestor exists and treated "none found" as "none
    there". Two of this parser's own limits make those different statements: the enclosing
    object's brace can sit before the search window, and the object can be too long for the
    per-candidate decode slice. Both were reachable, and both handed back a nested verdict
    with the report around it discarded - the same defect Slice 2 fixed, arriving through
    the size bound instead of through the scan order.

    The outer report is past MAX_REPORT_CHARS in every case here, so it was never going to
    be returned; the only question is whether the parser says so or answers with one of its
    fields. Refusing costs a wrapped report at the far end of a very long transcript, which
    the second table is here to bound: nothing that is genuinely independent may be lost to
    this, at any transcript length.
    """
    failures = []
    for name, mode, text, forbidden in OVERSIZED_ENCLOSURE:
        try:
            state, report = extract(text, mode)
        except Exception as exc:
            failures.append("%s: raised %s" % (name, type(exc).__name__))
            continue
        value = (report or {}).get(d.REPORT_DISCRIMINATORS[mode][0])
        if value == forbidden:
            failures.append(
                "%s: answered %r, which is the quoted value from inside the report that "
                "was too large to read - the enclosing report is what the agent wrote"
                % (name, value)
            )
        elif state != "missing":
            failures.append(
                "%s: state %r with %r; the enclosing report cannot be decoded, so there "
                "is nothing here to return" % (name, state, report)
            )

    for name, mode, text, expected in INDEPENDENT_AFTER_TRANSCRIPT:
        state, report = extract(text, mode)
        value = (report or {}).get(d.REPORT_DISCRIMINATORS[mode][0])
        if state != "present" or value != expected:
            failures.append(
                "%s: state %r value %r, wanted present %r. Nothing encloses this report, "
                "and the length of what precedes it is not evidence that something does"
                % (name, state, value, expected)
            )

    for name, prefix, expected in ENCLOSURE_GATE:
        got = d._may_be_enclosed(prefix + "{}", len(prefix))
        if got != expected:
            failures.append(
                "gate: %s -> may_be_enclosed %r, wanted %r" % (name, got, expected)
            )
    return failures


def check_nesting_is_structural():
    """The invariant itself, stated over spans rather than over example outputs.

    A table of shapes can only show that the ones someone thought of come out right. This
    asserts the rule they are all instances of: whatever is returned, no *other* qualifying
    object in the same text encloses it. That holds for a wrapper (nothing encloses the
    inner report), for a quoted verdict (the enclosing report is what comes back), and for
    two independent reports (neither encloses the other).
    """
    failures = []
    # Every structural shape in the suite, and only the structural ones. The bounded-input
    # fixtures above are hundreds of KB built to exhaust a limit, and re-scanning them in
    # four modes measures the limits again rather than the invariant - which TIMED already
    # does, once, on purpose.
    structural = 2000
    shapes = [text for _n, _m, text, _w in NESTED_SELECTION]
    shapes += [text for _n, _m, text, _s, _v in CASES if len(text) < structural]
    for text in shapes:
        for mode in sorted(d.REPORT_DISCRIMINATORS):
            state, report = extract(text, mode)
            if state != "present":
                continue
            budget = d._Budget()
            spans = [(s, e, obj) for s, e, obj in d._reports(text, mode, budget)]
            chosen = [(s, e) for s, e, obj in spans if obj == report]
            if not chosen:
                failures.append(
                    "%r in %s mode: the returned report is not one of the objects the "
                    "scan found" % (text[:60], mode)
                )
                continue
            start, end = chosen[-1]
            enclosing = [
                (s, e) for s, e, _o in spans if (s < start and e >= end) or
                (s <= start and e > end)
            ]
            if enclosing:
                failures.append(
                    "%r in %s mode: the returned report at %d:%d is enclosed by a "
                    "qualifying object at %d:%d"
                    % (text[:60], mode, start, end, enclosing[0][0], enclosing[0][1])
                )
    return failures


def check_matrix():
    """The three mode tables must declare the same modes, mechanically.

    MODES is the matrix; CONTRACTS supplies the brief; REPORT_DISCRIMINATORS identifies
    the reply. A mode present in one and absent from another does not fail until a run
    uses it, and then it fails as a KeyError inside a delegated run rather than as a
    mistake in a table.
    """
    failures = []
    declared = set(d.MODE_NAMES)
    if declared != {m for modes in d.MODES.values() for m in modes}:
        failures.append("MODE_NAMES does not match MODES")
    for table in ("CONTRACTS", "REPORT_DISCRIMINATORS"):
        missing = declared - set(getattr(d, table))
        extra = set(getattr(d, table)) - declared
        if missing or extra:
            failures.append(
                "%s: missing %s, extra %s" % (table, sorted(missing), sorted(extra))
            )

    # VERDICT_MODES is the one list a reader has to trust when deciding whether a result
    # can carry a verdict. It has to agree with the contracts themselves.
    by_discriminator = {
        m for m, (key, _) in d.REPORT_DISCRIMINATORS.items() if key == "verdict"
    }
    if by_discriminator != set(d.VERDICT_MODES):
        failures.append(
            "VERDICT_MODES %s but verdict discriminators %s"
            % (sorted(d.VERDICT_MODES), sorted(by_discriminator))
        )
    # .get, not [], so a mode missing from CONTRACTS is reported by the check above
    # rather than raised out of this one.
    for mode in declared - set(d.VERDICT_MODES):
        for key in d.VERDICT_KEYS:
            if '"%s"' % key in d.CONTRACTS.get(mode, ""):
                failures.append(
                    '%s contract asks for "%s" but has no verdict' % (mode, key)
                )
    for mode in d.VERDICT_MODES:
        if '"verdict"' not in d.CONTRACTS.get(mode, ""):
            failures.append(
                "%s is in VERDICT_MODES but its contract has no verdict" % mode
            )

    # Read-only is the default for Codex, so a mode added later cannot land on the write
    # side of the sandbox test by omission.
    for mode in d.MODES["codex"]:
        argv, _env, _stdin = d.adapt_codex(brief="b", mode=mode, cwd="/probe")
        sandbox = argv[argv.index("--sandbox") + 1]
        expected = "workspace-write" if mode == "test" else "read-only"
        if sandbox != expected:
            failures.append(
                "codex %s mode: sandbox %s, wanted %s" % (mode, sandbox, expected)
            )
    return failures


class Refused(Exception):
    """What the dispatcher's `fail` does: reports and exits. Raised so a test can catch it."""


def refuse(message):
    raise Refused(message)


def check_cwd_validation(tmp):
    """--cwd is required, absolute, and a repository root - or the run does not start.

    A default here is the defect: an inherited directory reads as "here" and is not. So
    the absent case is checked as carefully as the invalid ones, and the accepted case
    asserts the returned path is resolved rather than echoed.
    """
    failures = []

    def real(q):
        return os.path.realpath(str(q))

    root = tmp / "repo"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    (tmp / "plain").mkdir()
    worktree = tmp / "linked"
    worktree.mkdir()
    (worktree / ".git").write_text("gitdir: ../repo/.git/worktrees/linked\n")
    link = tmp / "link-to-repo"
    link.symlink_to(root)

    def refused(name, raw, expect_in):
        try:
            d.resolve_working_directory(raw, refuse)
        except Refused as exc:
            if expect_in not in str(exc):
                failures.append("%s: refused, but the reason lacks %r" % (name, expect_in))
        else:
            failures.append("%s: accepted, and must not be" % name)

    def accepted(name, raw, want):
        try:
            got = d.resolve_working_directory(raw, refuse)
        except Refused as exc:
            failures.append("%s: refused (%s)" % (name, str(exc)[:60]))
            return
        if got != want:
            failures.append("%s: resolved to %r, wanted %r" % (name, got, want))

    refused("absent --cwd", None, "required")
    refused("directory that is not a repository", str(tmp / "plain"), "not a git work tree")
    refused("path that does not exist", str(tmp / "missing"), "not a directory")
    refused("a file rather than a directory", str(worktree / ".git"), "not a directory")
    # Stated decision: a subdirectory is refused, not resolved upward. The error names the
    # root so the fix is one edit.
    refused("subdirectory of a repository", str(root / "src"), "subdirectory of")
    try:
        d.resolve_working_directory(str(root / "src"), refuse)
    except Refused as exc:
        if real(root) not in str(exc):
            failures.append("subdirectory refusal does not name the repository root")

    accepted("repository root", str(root), real(root))
    accepted("trailing separator", str(root) + "/", real(root))
    accepted("relative path", os.path.relpath(str(root)), real(root))
    accepted("symlink to a repository root", str(link), real(root))
    accepted("linked work tree, .git is a file", str(worktree), real(worktree))

    if d.enclosing_repository(str(root / "src")) != real(root):
        failures.append("enclosing_repository did not find the enclosing root")
    if d.enclosing_repository(real(root)) is not None:
        failures.append("enclosing_repository looked at the path itself, not its ancestors")
    return failures


def check_working_directory():
    """Every adapter must state the working directory, not inherit it.

    This is here because the failure is silent and looks like success. OpenCode resolved
    its directory from the inherited PWD rather than from the child process's cwd, so a
    delegated run operated on whatever repository the orchestrator's shell was sitting in
    while the dispatcher's result reported the directory it had been given. Nothing about
    the run looked wrong: it exited 0, returned a well-formed report, and described work
    it had done somewhere else.
    """
    failures = []
    cwd = "/probe/target"

    argv, env, stdin = d.adapt_opencode(
        brief="b", model_id="p/m", effort="low", mode="implement", cwd=cwd
    )
    if "--dir" not in argv:
        failures.append("opencode: no --dir; the directory would be inherited")
    elif argv[argv.index("--dir") + 1] != cwd:
        failures.append("opencode: --dir is not the requested directory")
    if env.get("PWD") != cwd:
        failures.append("opencode: PWD %r disagrees with the requested directory" % env.get("PWD"))
    if stdin is not None or argv[-1] != "b":
        failures.append("opencode: the brief is no longer the final argument")

    for mode in d.MODES["codex"]:
        argv, env, stdin = d.adapt_codex(brief="b", mode=mode, cwd=cwd)
        if "-C" not in argv:
            failures.append("codex %s: no -C; the directory would be inherited" % mode)
        elif argv[argv.index("-C") + 1] != cwd:
            failures.append("codex %s: -C is not the requested directory" % mode)
        if env.get("PWD") != cwd:
            failures.append("codex %s: PWD disagrees with the requested directory" % mode)
        if stdin != "b" or argv[-1] != "-":
            failures.append("codex %s: the brief is no longer delivered on stdin" % mode)
    return failures


# Behaviour that is known to be wrong and is not yet fixed. Recorded so it is visible
# rather than mistaken for correctness. Reported by Codex, attempt 3 of the Phase 03
# review loop, which reached the three-attempt bound. See PHASE_03_REPORT.md.
KNOWN_GAPS = [
    ("generic object with a valid discriminator is accepted", "implement",
     '{"status":"completed","operation":"session"}', "present"),
    ("same, review mode", "review", '{"verdict":"PASS","rule":"transport"}', "present"),
]


def check_command_boundaries():
    """The one rule set, and both engines that translate it.

    `config/command-boundaries.json` exists because these rules were maintained twice, by
    hand, in two matching engines - and the copies drifted apart without anything
    noticing. A bench subcommand with no --site ended up asked for by the hook and
    permitted inside a delegated run, which gave a delegated agent wider access to live
    sites than Claude had. That is the failure this function exists to make loud: every
    rule must be enforced by every consumer that declares a decision for it, and a rule
    added to the data and dropped by one translation fails here, by name.

    It also checks that each rule names a real section of a real skill. Prose is written
    by hand and stays that way; what is enforced is that it exists.
    """
    problems = []
    rules = BOUNDARIES["rules"]

    if not rules:
        return ["the boundary data declares no rules at all"]

    for rule in rules:
        name = rule.get("name", "<unnamed>")
        hook, delegated = rule.get("hook"), rule.get("delegated")
        examples = rule.get("examples") or []
        counters = rule.get("not_examples") or []

        if not examples:
            problems.append("%s: no examples, so nothing checks either translation" % name)
        if hook is None and delegated is None:
            problems.append("%s: no consumer enforces this rule" % name)

        # A null decision has to be justified in the data. Without this, dropping a rule
        # from one consumer is a one-word edit that nothing objects to - which is how the
        # divergence this file exists to prevent came about in the first place.
        stated = rule.get("not_enforced_because") or {}
        for consumer, decision, where in (
            ("hook", hook, "by the hook"),
            ("delegated", delegated, "inside a delegated run"),
        ):
            if decision is None and not stated.get(consumer):
                problems.append(
                    "%s: not enforced %s and no reason given - say why in "
                    "not_enforced_because, or restore the decision" % (name, where)
                )

        # --- the hook's translation ---------------------------------------
        if hook:
            if not g.REASONS.get(name):
                problems.append(
                    "%s: enforced by the hook with no reason text, so a blocked agent is "
                    "told only the rule's intent" % name
                )
            for command in examples:
                matched = g.match_rule(command)
                if matched is None or matched.get("name") != name:
                    problems.append(
                        "%s: hook does not catch %r (matched %r)"
                        % (name, command, matched.get("name") if matched else None)
                    )
                elif g.check(command)[0] != hook:
                    problems.append(
                        "%s: hook decided %r on %r, data says %r"
                        % (name, g.check(command)[0], command, hook)
                    )
            for command in counters:
                matched = g.match_rule(command)
                if matched is not None and matched.get("name") == name:
                    problems.append("%s: hook wrongly catches %r" % (name, command))

        # --- the dispatcher's translation ---------------------------------
        if delegated == "deny":
            patterns = d.rule_patterns(rule)
            if not patterns:
                problems.append(
                    "%s: denied in a delegated run but the dispatcher produced no "
                    "pattern for it - match kind %r is not implemented there"
                    % (name, (rule.get("match") or {}).get("kind"))
                )
            for command in examples:
                if not any(fnmatch.fnmatch(command, p) for p in patterns):
                    problems.append("%s: delegated policy does not deny %r" % (name, command))
            for command in counters:
                hit = [p for p in patterns if fnmatch.fnmatch(command, p)]
                if hit:
                    problems.append(
                        "%s: delegated policy wrongly denies %r via %r" % (name, command, hit[0])
                    )

        # --- the prose ----------------------------------------------------
        for where in rule.get("documented_in") or []:
            path = ROOT / where["file"]
            if not path.exists():
                problems.append("%s: documented_in names a missing file %s" % (name, where["file"]))
            elif where["heading"] not in path.read_text():
                problems.append(
                    "%s: %s has no section %r - the rule is enforced but undocumented"
                    % (name, where["file"], where["heading"])
                )

    # --- the set both engines must cover in full --------------------------
    site = next((r for r in rules if r["name"] == "site-unnamed"), None)
    if site is None:
        problems.append("the site-unnamed rule is gone; bench subcommands resolve a site silently")
    else:
        subs = site["match"]["subcommands"]
        patterns = d.rule_patterns(site)
        missed_hook = [s for s in subs
                       if (g.match_rule("bench %s" % s) or {}).get("name") != "site-unnamed"]
        missed_deleg = [s for s in subs
                        if not any(fnmatch.fnmatch("bench %s" % s, p) for p in patterns)]
        if missed_hook:
            problems.append("hook misses %d of %d bench subcommands, e.g. %s"
                            % (len(missed_hook), len(subs), ", ".join(missed_hook[:5])))
        if missed_deleg:
            problems.append("delegated policy misses %d of %d bench subcommands, e.g. %s"
                            % (len(missed_deleg), len(subs), ", ".join(missed_deleg[:5])))

    # --- the two engines agree where both apply ---------------------------
    for rule in rules:
        if rule.get("hook") and rule.get("delegated") == "deny":
            patterns = d.rule_patterns(rule)
            for command in rule.get("examples") or []:
                seen_by_hook = (g.match_rule(command) or {}).get("name") == rule["name"]
                denied = any(fnmatch.fnmatch(command, p) for p in patterns)
                if seen_by_hook != denied:
                    problems.append(
                        "%s: the engines disagree on %r - hook %s, delegated %s"
                        % (rule["name"], command,
                           "catches" if seen_by_hook else "misses",
                           "denies" if denied else "permits")
                    )
    return problems


# --------------------------------------------------------------------------
# Destructive operations
#
# The rule set protected the boundaries whose worst case is a messy commit -
# staging, committing, pushing - and none of the boundaries whose worst case is the
# user's uncommitted work being gone. `git reset --hard`, `git checkout -- .`,
# `git clean -fdx` and `rm -rf .` were permitted by the hook and, inside a delegated
# run, auto-approved: the base policy is `{"*": "ask"}` and the dispatcher passes
# --auto, so everything not explicitly denied runs with nobody watching.
#
# The failure this guards against needs no adversary. An implementation agent whose
# first edit broke the build decides to start from a clean state and reaches for the
# command that does that. The user's unrelated uncommitted work - which the
# orchestrator specifically looked at and decided to leave alone - goes with it, and
# unstaged content has no reflog entry to come back from.
#
# What is checked here is different from the drift test above, in three ways that
# each caught something while this was being written:
#
#   - decisions come from `decide()`, the hook's real entry point, so what is
#     asserted is the answer Claude Code receives rather than which rule matched;
#   - a counter-example must draw *no* decision at all, not merely a decision from
#     some other rule - falling through to a different rule is still a prompt the
#     user did not need;
#   - the delegated side is checked against the *assembled* policy, every rule's
#     patterns together, because a rule that is narrow on its own can still be
#     shadowed by a pattern belonging to another one.
#
# Nothing here runs any of these commands. Both engines decide from the command
# string alone, so the string is the whole input, and a test that actually ran
# `git clean -fdx` to see what happens would be the bug it is testing for.
# --------------------------------------------------------------------------

# The policy this slice establishes, as decisions rather than as rules: what Claude
# is told, and what a delegated run is allowed to do, for one representative command
# from each family. `None` is "no rule covers this" - the answer a safe form must
# get, since an ask on a command that destroys nothing is the noise that teaches a
# reader to stop reading the rules.
#
# Deliberately a handful of representatives and not a catalogue. The exhaustive
# per-family coverage is the examples and not_examples in the boundary data, which
# check_command_boundaries drives through both engines; a second catalogue here
# would be the duplicate rule set that file exists to prevent.
DESTRUCTIVE_POLICY = (
    # command                          hook      delegated
    ("git reset --hard HEAD~1",        "ask",    "deny"),
    ("git reset HEAD~1",               None,     "permit"),
    ("git checkout -- .",              "ask",    "deny"),
    ("git checkout feature-branch",    None,     "permit"),
    ("git checkout -b new-feature",    None,     "permit"),
    ("git restore src/file.py",        "ask",    "deny"),
    ("git clean -fdx",                 "ask",    "deny"),
    ("git clean -n",                   "ask",    "deny"),
    ("git stash clear",                "ask",    "deny"),
    ("git stash list",                 None,     "permit"),
    ("git branch -D feature",          "ask",    "deny"),
    ("git branch -d merged-feature",   None,     "permit"),
    ("git rebase -i HEAD~3",           None,     "deny"),
    ("rm -rf .",                       "ask",    "deny"),
    ("rm build/output.js",             None,     "permit"),
    ("find . -delete",                 "ask",    "deny"),
    ("find . -name '*.pyc'",           None,     "permit"),
    ("truncate -s 0 config.json",      "ask",    "deny"),
)

# The rules this slice added, by name. Not a second copy of what they match - only
# which entries in the data the checks below are about, so that a rule quietly
# dropped from the file fails here instead of reducing the coverage in silence.
DESTRUCTIVE_RULES = (
    "discard-tracked-changes",
    "discard-pathspec-changes",
    "discard-worktree",
    "drop-stash",
    "force-branch-ref",
    "expire-recovery-refs",
    "rewrite-repository-history",
    "rebase-inside-delegated-run",
    "recursive-delete",
    "mass-delete",
    "overwrite-file-contents",
)

# Commands a rule declares it does not cover, which the *assembled* delegated policy
# denies anyway through a pattern belonging to a different rule. Recorded rather than
# asserted away, and recorded rather than quietly dropped from the data: the command
# is genuinely one its own rule must not catch, the hook gets it right, and the
# over-match is in the glob translation of an older rule.
#
# `git * push*` exists so that `git -C /repo push` is denied. It has no way to
# require that `push` is the subcommand, so `git stash push` - which creates a stash
# and destroys nothing - matches it too. Narrowing that is the word-boundary work in
# the delegated translation, not this slice; what belongs here is that it is known,
# so a new one shows up as a new line rather than as nothing at all.
POLICY_OVERMATCHES = {
    "git stash push -m wip": "git * push*",
}


def check_destructive_boundaries():
    """Destructive Git and filesystem commands, through both engines, end to end."""
    problems = []
    rules = BOUNDARIES["rules"]
    by_name = {r["name"]: r for r in rules}
    policy = d.opencode_permissions(rules)["permission"]["bash"]
    denied = [p for p, decision in policy.items() if decision == "deny"]

    def delegated_hits(command):
        return [p for p in denied if fnmatch.fnmatch(command, p)]

    # --- the rules are present at all -------------------------------------
    for name in DESTRUCTIVE_RULES:
        if name not in by_name:
            problems.append(
                "%s is gone from the boundary data - the destructive-operation policy is "
                "only as present as its rules" % name
            )
    if problems:
        return problems

    # --- the decisions, for one representative per family ------------------
    for command, want_hook, want_delegated in DESTRUCTIVE_POLICY:
        got = g.decide(command)
        got_hook = got[0] if got else None
        if got_hook != want_hook:
            matched = g.match_rule(command)
            problems.append(
                "%r: the hook decides %r, the policy is %r%s"
                % (command, got_hook, want_hook,
                   " (matched %s)" % matched["name"] if matched else "")
            )
        hits = delegated_hits(command)
        got_delegated = "deny" if hits else "permit"
        if got_delegated != want_delegated:
            problems.append(
                "%r: a delegated run gets %r, the policy is %r%s"
                % (command, got_delegated, want_delegated,
                   " (via %r)" % hits[0] if hits else "")
            )

    # --- every example, through the hook's real entry point -----------------
    # decide() rather than match_rule(): it splits the command, applies deny over
    # ask, and returns what Claude Code is actually handed. A rule can match and
    # still deliver the wrong decision.
    for name in DESTRUCTIVE_RULES:
        rule = by_name[name]
        for command in rule["examples"]:
            got = g.decide(command)
            want = rule.get("hook")
            if (got[0] if got else None) != want:
                problems.append(
                    "%s: decide(%r) is %r, the data says %r"
                    % (name, command, got[0] if got else None, want)
                )
            if not delegated_hits(command):
                problems.append(
                    "%s: the assembled delegated policy permits %r" % (name, command)
                )

    # --- every counter-example, against the whole of both engines -----------
    for name in DESTRUCTIVE_RULES:
        rule = by_name[name]
        for command in rule["not_examples"]:
            got = g.decide(command)
            if got is not None:
                matched = g.match_rule(command)
                problems.append(
                    "%s: %r is documented as safe and the hook still decides %r on it "
                    "(via %s) - a counter-example has to draw no decision, not a "
                    "decision from somewhere else"
                    % (name, command, got[0], matched["name"] if matched else "?")
                )
            hits = delegated_hits(command)
            known = POLICY_OVERMATCHES.get(command)
            if hits and known not in hits:
                problems.append(
                    "%s: the assembled delegated policy denies %r via %r, and it is "
                    "documented as safe" % (name, command, hits[0])
                )

    # --- a rule that claims to be narrow has to prove it --------------------
    # An over-broad rule and a precise one look identical in the data until someone
    # writes down what the rule must leave alone. Every rule carries counter-examples
    # today; this keeps that true for the next one added.
    for rule in rules:
        if not rule.get("not_examples"):
            problems.append(
                "%s: no not_examples, so nothing establishes what this rule leaves "
                "alone" % rule["name"]
            )

    # --- the recorded over-matches are still real ---------------------------
    # A stale entry here would silently excuse a false positive that had since been
    # fixed, which is the same invisibility the table exists to remove.
    for command, pattern in POLICY_OVERMATCHES.items():
        if pattern not in delegated_hits(command):
            problems.append(
                "POLICY_OVERMATCHES records %r as denied via %r and it no longer is - "
                "remove the entry" % (command, pattern)
            )
    return problems


def check_agent_path_record(tmp):
    """The result must say which binary actually ran, and it must be the child's PATH.

    A CLI name is not a build. `opencode` on the machine this was developed against is a
    Linux binary in nvm's bin directory, with a Windows shim second on PATH; the Windows
    one never received the permission policy and ran a delegated `bench migrate`
    unrefused. Which of the two a run got is decided by PATH order, which nothing in this
    plugin controls and which changes without announcing itself, so the result records the
    resolved path - otherwise a result measured against the wrong build cannot be told
    apart from one measured against the right one, and the record cannot settle it later.

    Checked end to end rather than by inspecting the function, because the failure this
    guards against is the field quietly not reaching `result.json`. A stub CLI on a PATH
    the test controls stands in for the real one: it makes the correct answer known in
    advance, which no real agent run does.
    """
    problems = []
    model = delegable_model()
    if model is None:
        return ["no delegable model in the routing file to drive the dispatcher with"]

    bin_dir, repo, work = tmp / "bin", tmp / "repo", tmp / "work"
    for path in (bin_dir, repo / ".git", work):
        path.mkdir(parents=True)
    # A symlink, because the real one is: nvm installs `opencode` as a link to a file in
    # node_modules named `opencode.exe` that is an ELF binary. A stub that is a plain file
    # makes "follows the link" trivially true and checks nothing.
    target = bin_dir / "opencode-real"
    target.write_text(
        '#!/bin/sh\n'
        'echo \'{"status": "completed", "summary": "stub", "touched_files": []}\'\n'
    )
    target.chmod(0o755)
    stub = bin_dir / "opencode"
    stub.symlink_to(target)

    env = dict(os.environ)
    env["PATH"] = "%s:/usr/bin:/bin" % bin_dir
    env["TMPDIR"] = str(work)   # so the run's workspace is cleaned up with the test
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "delegate"),
         "--agent", "opencode", "--mode", "implement", "--tier", "FAST",
         "--cwd", str(repo), "--model", model],
        input="stub brief", capture_output=True, text=True, env=env, timeout=60,
    )
    if proc.returncode != 0:
        return ["the dispatcher exited %s: %s" % (proc.returncode, proc.stderr[-200:])]
    try:
        result = json.loads(proc.stdout)
    except ValueError as exc:
        return ["the dispatcher's stdout is not JSON: %s" % exc]

    if result.get("agent_path") != str(stub):
        problems.append(
            "agent_path is %r; the CLI on the child's PATH was %s"
            % (result.get("agent_path"), stub)
        )
    if result.get("agent_real_path") != str(target):
        problems.append(
            "agent_real_path is %r; the link on PATH points at %s"
            % (result.get("agent_real_path"), target)
        )
    if result.get("result_block") != "present":
        problems.append("the stub's report was not parsed out of its stdout")

    # Which PATH is consulted cannot be established through the subprocess above: Popen
    # hands the child that same env as its os.environ, so the two agree whatever the code
    # reads. In process they can be made to disagree, which is the only way to show the
    # lookup follows the environment the child will actually get rather than this one.
    elsewhere = tmp / "elsewhere"
    elsewhere.mkdir()
    decoy = elsewhere / "opencode"
    decoy.write_text("#!/bin/sh\nexit 0\n")
    decoy.chmod(0o755)
    found = d.resolve_program("opencode", {"PATH": str(elsewhere)})
    if found is None or found[0] != str(decoy):
        problems.append(
            "resolve_program returned %r for a PATH containing only %s - it is not "
            "reading the environment it was passed" % (found, elsewhere)
        )
    if d.resolve_program("no-such-agent-cli", {"PATH": str(elsewhere)}) is not None:
        problems.append("resolve_program invented a path for a CLI that is not installed")

    # The same record has to survive into the workspace copy, which is what is left behind
    # for anyone reading the run afterwards.
    written = Path(result["workspace"]) / "result.json"
    if not written.exists():
        problems.append("no result.json was written to the workspace")
    elif json.loads(written.read_text()).get("agent_path") != result.get("agent_path"):
        problems.append("the workspace's result.json disagrees about which binary ran")
    return problems


def check_dispatcher_invocation():
    """The copies that say how to invoke the dispatcher, checked against the dispatcher.

    Three places outside `scripts/delegate` state its invocation, and none of them can be
    generated from it: the hook's deny reason, which is the only instruction a blocked
    agent gets; the orchestration skill's delegation block, which is what Claude follows;
    and the dispatcher's own `--help`. A mode added to `MODES` updates none of them.

    The failure is quiet, which is why it is checked here. A stale deny reason sends a
    blocked agent to re-run an invocation the dispatcher then refuses, and a stale skill
    block does the same to Claude - in both cases the mistake surfaces one layer away from
    where it was made, as a usage error about an argument the reader was told to pass.

    The prose stays hand-written; what is asserted is that it still describes this
    dispatcher, the same way each boundary rule asserts that the skill section documenting
    it exists. The skill's invocations get the stronger form that is available for them:
    each one is run through `validate_invocation`, the function a real run goes through,
    so a documented combination the dispatcher would refuse fails here rather than at the
    point of use.
    """
    problems = []
    parser = d.build_parser()
    by_parser = [a.option_strings[0] for a in parser._actions if a.required]
    options = {opt for a in parser._actions for opt in a.option_strings}

    # --cwd is required by resolve_working_directory rather than by argparse, so it is
    # invisible to the introspection above and has to be declared. Both halves are
    # checked:
    # that it is a real option, and that it is not one argparse already requires - either
    # would make the declaration a stale copy of its own.
    for option in d.REQUIRED_OUTSIDE_PARSER:
        if option not in options:
            problems.append(
                "REQUIRED_OUTSIDE_PARSER names %s, which is not an option" % option
            )
        if option in by_parser:
            problems.append(
                "%s is required by the parser, so REQUIRED_OUTSIDE_PARSER should not "
                "name it" % option
            )
    required = by_parser + [o for o in d.REQUIRED_OUTSIDE_PARSER if o in options]

    # --- the hook's deny reason -------------------------------------------
    reason = g.AGENT_REASON
    for option in required:
        if option not in reason:
            problems.append(
                "the hook's bare-agent reason does not name %s, and an agent that reads "
                "it will be refused for leaving it out" % option
            )
    for option, accepted in (("--agent", set(d.MODES)), ("--mode", set(d.MODE_NAMES))):
        found = re.search(re.escape(option) + r" <([^>]+)>", reason)
        if not found:
            problems.append(
                "the hook's bare-agent reason does not enumerate %s" % option
            )
            continue
        listed = {value.strip() for value in found.group(1).split("|")}
        if listed != accepted:
            problems.append(
                "the hook's bare-agent reason offers %s %s; the dispatcher accepts %s"
                % (option, sorted(listed), sorted(accepted))
            )

    # --- the orchestration skill's delegation block ------------------------
    skill = (ROOT / "skills" / "orchestration" / "SKILL.md").read_text()
    documented = set()
    lines = [line.strip() for line in skill.splitlines()
             if line.strip().startswith("delegate --")]
    if not lines:
        return problems + [
            "the orchestration skill documents no delegate invocation at all"
        ]
    for line in lines:
        tokens = shlex.split(line)
        given = {}
        for token, following in zip(tokens, tokens[1:] + [""]):
            if token.startswith("--"):
                given[token] = "" if following.startswith("--") else following
        for option in required:
            if option not in given:
                problems.append("skill: %r does not pass %s" % (line, option))
        agent, mode = given.get("--agent"), given.get("--mode")
        if agent not in d.MODES:
            problems.append("skill: %r names an agent the dispatcher does not run" % line)
            continue
        documented.add((agent, mode))
        try:
            d.validate_invocation(agent, mode, given.get("--model"), refuse)
        except Refused as exc:
            problems.append(
                "skill: the dispatcher refuses %r - %s" % (line, str(exc)[:80])
            )

    supported = {(agent, mode) for agent, modes in d.MODES.items() for mode in modes}
    for pair in sorted(supported - documented):
        problems.append(
            "skill: --agent %s --mode %s is supported and undocumented" % pair
        )
    return problems


# --------------------------------------------------------------------------
# The hook's entry point
#
# Everything below runs `hooks/guard.py` as a process with a payload on stdin, which is
# what Claude Code does. Calling `check()` in process, which the boundary checks above do,
# cannot see any of it: not the payload contract, not the JSON that Claude Code parses,
# not what happens when the rule data will not load, and not what happens when the hook
# faults. Three of those were failing open before this was written.
# --------------------------------------------------------------------------


def payload(command):
    """A PreToolUse payload shaped the way Claude Code delivers one."""
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})


def run_hook(stdin_text, guard=None):
    """One hook process, payload on stdin. Returns the finished process."""
    return subprocess.run(
        [sys.executable, str(guard or GUARD)],
        input=stdin_text, capture_output=True, text=True, timeout=60,
    )


def outcome(proc):
    """(decision, reason) for a finished hook run.

    "allow" is the absence of a decision, which is how this hook permits a command - so a
    run that produced no output is an allow, and must be read as one. Anything that is not
    a clean exit with either no output or exactly one well-formed decision is reported as
    a fault, because that is what Claude Code would be left to interpret: a non-zero exit
    is a non-blocking error there, after which the command runs.
    """
    if proc.returncode != 0:
        return "exit%d" % proc.returncode, proc.stderr.strip()[-160:]
    if not proc.stdout.strip():
        return "allow", ""
    try:
        block = json.loads(proc.stdout)["hookSpecificOutput"]
        decision, reason = block["permissionDecision"], block["permissionDecisionReason"]
    except (ValueError, KeyError, TypeError) as exc:
        return "unparseable", "%s: %r" % (type(exc).__name__, proc.stdout[:100])
    # A decision Claude Code cannot act on is not a decision. Reported rather than
    # returned as-is, so a caller comparing it never has to be defensive about the type -
    # and so a hook that emits one fails by name instead of raising out of a test.
    if not isinstance(decision, str):
        return "invalid(%r)" % (decision,), reason if isinstance(reason, str) else ""
    return decision, reason if isinstance(reason, str) else ""


# (name, raw stdin, expected decision)
# The shapes that are not dictionaries all the way down are here because every one of them
# raised AttributeError out of main() and exited 1, which Claude Code reports as a
# non-blocking error - so the command ran. "allow" is the correct answer for them, but it
# has to be an allow the hook decided, not one a traceback produced.
HOOK_PAYLOADS = [
    # --- payloads carrying a real command ------------------------------------
    ("valid payload, ask rule", payload("git push"), "ask"),
    ("valid payload, deny rule", payload("git add ."), "deny"),
    ("valid payload, no rule", payload("ls -la"), "allow"),
    ("command with unknown sibling fields", json.dumps(
        {"tool_name": "Bash", "session_id": "s", "cwd": "/x",
         "tool_input": {"command": "git push", "timeout": 120}}), "ask"),

    # --- nothing to decide about ---------------------------------------------
    ("empty stdin", "", "allow"),
    ("invalid JSON", "not json", "allow"),
    ("truncated JSON", '{"tool_input":', "allow"),
    ("JSON null", "null", "allow"),
    ("top-level array", "[]", "allow"),
    ("top-level string", '"hello"', "allow"),
    ("top-level number", "5", "allow"),
    ("top-level bool", "true", "allow"),
    ("empty object", "{}", "allow"),
    ("no tool_input", '{"tool_name": "Bash"}', "allow"),
    ("tool_input null", '{"tool_input": null}', "allow"),
    ("tool_input array", '{"tool_input": ["git push"]}', "allow"),
    ("tool_input string", '{"tool_input": "git push"}', "allow"),
    ("tool_input number", '{"tool_input": 7}', "allow"),
    ("tool_input empty object", '{"tool_input": {}}', "allow"),
    ("no command key", '{"tool_input": {"bash_id": "x"}}', "allow"),
    ("command null", '{"tool_input": {"command": null}}', "allow"),
    ("command number", '{"tool_input": {"command": 123}}', "allow"),
    ("command array", '{"tool_input": {"command": ["git", "push"]}}', "allow"),
    ("command object", '{"tool_input": {"command": {"run": "git push"}}}', "allow"),
    ("command empty string", '{"tool_input": {"command": ""}}', "allow"),
    ("command whitespace only", '{"tool_input": {"command": "   \\n  "}}', "allow"),
    ("nested past the recursion limit", "[" * 20000 + "]" * 20000, "allow"),
]


def check_hook_payloads():
    """Every payload shape produces a decision, and none produces a traceback."""
    problems = []
    for name, stdin_text, want in HOOK_PAYLOADS:
        proc = run_hook(stdin_text)
        got, reason = outcome(proc)
        if "Traceback" in proc.stderr:
            problems.append(
                "%s: the hook raised - %s" % (name, proc.stderr.strip()[-120:])
            )
        if proc.returncode != 0:
            problems.append(
                "%s: exit %d. Claude Code treats a non-zero hook exit as a non-blocking "
                "error and runs the command, so this is an allow the hook did not decide"
                % (name, proc.returncode)
            )
            continue
        if got != want:
            problems.append("%s: decided %r, wanted %r" % (name, got, want))
        if got != "allow" and not reason.strip():
            problems.append("%s: decided %r with an empty reason" % (name, got))
    return problems


def check_hook_response_shape():
    """The JSON Claude Code parses, checked as a contract rather than as non-empty text.

    Every field name here was verified against the hooks reference when the hook was
    written and none of them is guessable: a typo in `hookSpecificOutput` or in
    `permissionDecision` is a decision Claude Code silently does not act on, which looks
    exactly like a hook that chose to allow.
    """
    problems = []
    want_keys = ["hookEventName", "permissionDecision", "permissionDecisionReason"]
    for command, want in (("git push", "ask"), ("git add .", "deny")):
        proc = run_hook(payload(command))
        if proc.returncode != 0:
            problems.append("%r: exit %d" % (command, proc.returncode))
            continue
        try:
            body = json.loads(proc.stdout)
        except ValueError as exc:
            problems.append("%r: stdout is not JSON (%s)" % (command, exc))
            continue
        if not isinstance(body, dict) or list(body) != ["hookSpecificOutput"]:
            problems.append(
                "%r: top level is %r, wanted exactly hookSpecificOutput"
                % (command, sorted(body) if isinstance(body, dict) else type(body).__name__)
            )
            continue
        block = body["hookSpecificOutput"]
        if not isinstance(block, dict):
            problems.append("%r: hookSpecificOutput is a %s" % (command, type(block).__name__))
            continue
        if sorted(block) != want_keys:
            problems.append(
                "%r: hookSpecificOutput carries %r, wanted %r"
                % (command, sorted(block), want_keys)
            )
        if block.get("hookEventName") != "PreToolUse":
            problems.append(
                "%r: hookEventName is %r" % (command, block.get("hookEventName"))
            )
        if block.get("permissionDecision") != want:
            problems.append(
                "%r: permissionDecision is %r, wanted %r"
                % (command, block.get("permissionDecision"), want)
            )
        reason = block.get("permissionDecisionReason")
        if not isinstance(reason, str) or not reason.strip():
            problems.append("%r: permissionDecisionReason is %r" % (command, reason))
        if proc.stdout.count("hookSpecificOutput") != 1:
            problems.append("%r: more than one decision was written" % command)
    return problems


# (name, command, expected decision, the rule whose reason text must come back)
# A command is submitted as one unit, so the strongest decision any segment earns is the
# decision for all of it. The reason is asserted too: a right decision carrying another
# rule's explanation sends the reader to check the wrong thing.
PRECEDENCE = [
    ("deny outranks an earlier ask", "bench migrate; git add .", "deny", "blanket-staging"),
    ("deny outranks a later ask", "git add .; bench migrate", "deny", "blanket-staging"),
    ("two asks: the first segment wins", "bench migrate && git push", "ask", "site-unnamed"),
    ("ask beside a pass-through", "ls -la; git push", "ask", "push"),
    ("pipe is a separator", "git status | git push", "ask", "push"),
    ("newline is a separator, so a heredoc body is seen",
     "bash <<'EOF'\ngit add -A\nEOF", "deny", "blanket-staging"),
    ("nothing matches", "ls -la; npm test", "allow", None),
]


def check_decision_precedence():
    """deny > ask > allow, across the segments of one command."""
    problems = []
    for name, command, want, rule in PRECEDENCE:
        got, reason = outcome(run_hook(payload(command)))
        if got != want:
            problems.append("%s: %r decided %r, wanted %r" % (name, command, got, want))
            continue
        if rule is None:
            continue
        expected = g.REASONS.get(rule) or ""
        if reason != expected:
            problems.append(
                "%s: %r decided %r but with %s's reason, not %s's"
                % (name, command, got,
                   next((n for n, t in g.REASONS.items() if t == reason), "an unknown rule"),
                   rule)
            )
    return problems


ABSENT = object()   # the mutation that removes the file rather than rewriting it


def _rules(data, name, **overrides):
    """The rule set with one named rule's fields replaced."""
    return dict(data, rules=[
        dict(rule, **overrides) if rule["name"] == name else rule
        for rule in data["rules"]
    ])


def _match(data, name, **overrides):
    """The rule set with one named rule's match fields replaced."""
    return _rules(data, name, match=dict(
        next(r for r in data["rules"] if r["name"] == name)["match"], **overrides
    ))


def _drop(data, name, key):
    """The rule set with one key removed from one named rule."""
    return dict(data, rules=[
        {k: v for k, v in rule.items() if k != key} if rule["name"] == name else rule
        for rule in data["rules"]
    ])


# (name, mutation) - each returns what to write in place of the boundary data.
# Every entry here silently disabled the hook entirely, or crashed it on every command,
# before load_rules() validated its input. The four that only fail to *read* were already
# handled and are kept as the control group: the fix is that the rest behave like them.
BOUNDARY_FAULTS = [
    # --- unreadable: already degraded correctly, kept so that stays true -----
    ("file absent", lambda data: ABSENT),
    ("empty file", lambda data: ""),
    ("invalid JSON", lambda data: "{not json"),
    ("not UTF-8", lambda data: b"\xff\xfe{\x00}\x00"),
    # --- structurally wrong above the rules ---------------------------------
    ("top level is an array", lambda data: [data]),
    ("top level is a string", lambda data: '"rules"'),
    ("no rules key", lambda data: {k: v for k, v in data.items() if k != "rules"}),
    # --- rules present but not a usable collection ---------------------------
    ("rules: []", lambda data: dict(data, rules=[])),
    ("rules: {}", lambda data: dict(data, rules={})),
    ("rules: 'x'", lambda data: dict(data, rules="x")),
    ("rules: 42", lambda data: dict(data, rules=42)),
    ("rules holds strings", lambda data: dict(data, rules=["push", "blanket-staging"])),
    ("rules holds objects and a string",
     lambda data: dict(data, rules=[data["rules"][0], "blanket-staging"] + data["rules"][2:])),
    ("rules holds a null", lambda data: dict(data, rules=[None] + data["rules"])),
    ("every rule hook: null",
     lambda data: dict(data, rules=[dict(r, hook=None) for r in data["rules"]])),
    # --- a rule the hook cannot match ---------------------------------------
    ("unsupported match kind", lambda data: _match(data, "push", kind="regex")),
    ("match kind absent",
     lambda data: _rules(data, "push", match={"program": "git", "subcommands": ["push"]})),
    ("match is not an object", lambda data: _rules(data, "push", match="git push")),
    ("rule missing match", lambda data: _drop(data, "push", "match")),
    ("rule missing name", lambda data: _drop(data, "push", "name")),
    # --- match data the hook cannot use -------------------------------------
    ("subcommands is a string", lambda data: _match(data, "push", subcommands="push")),
    ("subcommands is empty", lambda data: _match(data, "push", subcommands=[])),
    ("subcommands holds a number", lambda data: _match(data, "push", subcommands=["push", 5])),
    ("program is not a string", lambda data: _match(data, "site-named", program=5)),
    ("options is empty", lambda data: _match(data, "site-named", options=[])),
    ("programs is a string", lambda data: _match(data, "database-client", programs="mysql")),
    ("identifiers is empty", lambda data: _match(data, "frappe-connection", identifiers=[])),
    ("any_argument is a string", lambda data: _match(data, "blanket-staging", any_argument=".")),
    ("unless_flags holds a number",
     lambda data: _match(data, "bare-agent-run", unless_flags=["--help", 5])),
    # --- a decision the hook cannot make ------------------------------------
    ("hook decision is allow", lambda data: _rules(data, "push", hook="allow")),
    ("hook decision is a number", lambda data: _rules(data, "push", hook=5)),
    ("hook decision is an empty string", lambda data: _rules(data, "push", hook="")),
]

# What a degraded hook must do. Protected commands are asked about - never allowed - and
# an unrelated command still passes through, because a hook that stopped every command
# would be removed, which is the outcome degrading exists to avoid.
DEGRADED_EXPECTED = (
    ("git push", "ask"),
    ("git add .", "ask"),
    ("git reset --hard", "ask"),
    ("bench migrate", "ask"),
    ("mysql -u root", "ask"),
    ("rm -rf .", "ask"),
    ("find . -delete", "ask"),
    ("ls -la", "allow"),
)

# What the same commands get when the data is intact. The control: it runs against a copy
# of the tree, so a degraded answer everywhere cannot be the copying.
INTACT_EXPECTED = (
    ("git push", "ask"),
    ("git add .", "deny"),
    ("git reset --hard", "ask"),
    ("bench migrate", "ask"),
    ("mysql -u root", "ask"),
    ("rm -rf .", "ask"),
    ("find . -delete", "ask"),
    ("ls -la", "allow"),
)


def check_shipped_rules_load():
    """The rule data in this repository must satisfy the validation, rule by rule.

    Checked separately from the fault table so that a real edit to the boundary data that
    the hook cannot enforce fails here by rule name, rather than as four commands
    mysteriously degrading.
    """
    problems = []
    if g.RULES is None:
        problems.append("the shipped boundary data does not load: %s" % g.RULES_FAULT)
    if g.RULES_FAULT is not None:
        problems.append("load_rules reported a fault: %s" % g.RULES_FAULT)
    for index, rule in enumerate(BOUNDARIES["rules"]):
        fault = g.rule_fault(rule, index)
        if fault is not None:
            problems.append(fault)
    enforced = [r["name"] for r in BOUNDARIES["rules"] if r.get("hook")]
    if g.RULES is not None and [r["name"] for r in g.RULES] != enforced:
        problems.append(
            "the hook loaded %r, but the data declares a hook decision for %r"
            % ([r["name"] for r in g.RULES], enforced)
        )
    return problems


def check_boundary_config_faults(tmp):
    """Unusable rule data must degrade visibly, never enforce nothing silently.

    `load_rules` used to return an empty list for most of these, which is not `None`, so
    the degraded path never ran and every command was allowed with no output and exit 0 -
    a hook that looked installed, said nothing, and guarded nothing. Two others raised on
    every command instead, which exits non-zero, which Claude Code reports as a
    non-blocking error before running the command anyway. Same outcome, louder.

    Each mutation gets its own copy of the plugin's two runtime files. The repository's own
    boundary data is read but never written.
    """
    problems = []
    data = json.loads(BOUNDARY_FILE.read_text())

    def guard_for(slot, written):
        root = tmp / slot
        (root / "hooks").mkdir(parents=True)
        (root / "config").mkdir()
        shutil.copy(GUARD, root / "hooks" / "guard.py")
        target = root / "config" / "command-boundaries.json"
        if written is ABSENT:
            pass
        elif isinstance(written, bytes):
            target.write_bytes(written)
        elif isinstance(written, str):
            target.write_text(written)
        else:
            target.write_text(json.dumps(written))
        return root / "hooks" / "guard.py"

    # The control first: the same copying, with the data intact.
    control = guard_for("control", data)
    for command, want in INTACT_EXPECTED:
        got, _reason = outcome(run_hook(payload(command), control))
        if got != want:
            problems.append(
                "control (data intact, in a copied tree): %r decided %r, wanted %r - the "
                "copies below prove nothing if this one is already degraded"
                % (command, got, want)
            )

    for slot, (name, mutate) in enumerate(BOUNDARY_FAULTS):
        guard = guard_for("fault-%02d" % slot, mutate(data))
        for command, want in DEGRADED_EXPECTED:
            proc = run_hook(payload(command), guard)
            got, reason = outcome(proc)
            if "Traceback" in proc.stderr:
                problems.append(
                    "%s: %r raised - %s" % (name, command, proc.stderr.strip()[-100:])
                )
            if got == want:
                continue
            if want == "ask" and got == "allow":
                problems.append(
                    "%s: %r was ALLOWED. Unusable rule data must never silently enforce "
                    "nothing" % (name, command)
                )
            elif want == "ask" and got.startswith("exit"):
                problems.append(
                    "%s: %r exited non-zero (%s), which Claude Code treats as a "
                    "non-blocking error - the command would run" % (name, command, got)
                )
            else:
                problems.append("%s: %r decided %r, wanted %r" % (name, command, got, want))
        # The reason has to say what is wrong, or the degraded state is undiagnosable.
        _got, reason = outcome(run_hook(payload("git push"), guard))
        if "not being enforced" not in reason:
            problems.append(
                "%s: the degraded reason does not say the boundaries are unenforced: %r"
                % (name, reason[:80])
            )
        elif "command-boundaries.json" not in reason and "declares no rules" not in reason:
            problems.append(
                "%s: the degraded reason names neither the file nor the fault: %r"
                % (name, reason[:80])
            )
    return problems


# Injected into a copy of the hook so the fault can be observed end to end, at the
# process boundary, where the exit status lives. `check` is redefined after the real one,
# and `decide` resolves it as a global at call time, so the copy faults exactly where a
# real engine fault would.
INJECT_FAULT = (
    'def check(segment):   # noqa: F811 - injected fault\n'
    '    raise RuntimeError("injected: rule engine fault")\n'
    '\n'
    '\n'
    'def decide(command):'
)


INJECT_LATE_FAULT = (
    '    raise MemoryError("injected: fault after the command was read")'
)


def check_internal_failure_is_fail_closed(tmp):
    """A fault inside the matching engine must block the command, not ask about it.

    No payload and no configuration can reach this path from outside - the validation
    above exists to prevent it - which is exactly why the fault is injected. The property
    under test does not depend on having predicted the fault: once a command has been
    extracted, a hook that cannot say whether a boundary applies does not let the command
    run, and does not put the question to a user who knows less about it than the code
    that just failed to answer it.

    `ls -la` is the probe on purpose. The working hook passes it through, so a block here
    can only have come from the failure path, and an allow would be indistinguishable
    from the hook working correctly.

    Both layers are checked, because either one alone can be mishandled: the `deny`
    decision on stdout, and the exit status, which blocks even when the JSON does not
    arrive.
    """
    problems = []

    # --- at the process boundary: decision, exit status and stderr -----------
    faulted = tmp / "faulted-guard.py"
    text = GUARD.read_text()
    if text.count("def decide(command):") != 1:
        return ["cannot inject a fault: decide() is not where this test expects it"]
    faulted.write_text(text.replace("def decide(command):", INJECT_FAULT, 1))

    proc = run_hook(payload("ls -la"), faulted)
    if "Traceback" in proc.stderr:
        problems.append(
            "the fault escaped as a traceback: %s" % proc.stderr.strip()[-120:]
        )
    if proc.returncode != g.BLOCKED_EXIT:
        problems.append(
            "exit %d on an internal failure, wanted %d. Every other non-zero status is a "
            "non-blocking error to Claude Code, after which the command runs"
            % (proc.returncode, g.BLOCKED_EXIT)
        )
    # outcome() reads a non-zero exit as a fault, which it is, so the decision is read
    # off stdout directly here - both layers have to be checked separately.
    try:
        decision = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
    except (ValueError, KeyError, TypeError) as exc:
        decision = None
        problems.append(
            "no usable decision on stdout (%s): %r" % (type(exc).__name__, proc.stdout[:100])
        )
    if decision in ("allow", "ask"):
        problems.append(
            "an internal failure decided %r. Once a command has been extracted, a hook "
            "that could not evaluate it must not authorise it or ask for it to be "
            "authorised" % decision
        )
    elif decision is not None and decision != "deny":
        problems.append("an internal failure decided %r, wanted deny" % decision)
    if "internal failure" not in proc.stderr:
        problems.append(
            "stderr does not identify an internal guard failure, and it is the only "
            "channel left when stdout is not read: %r" % proc.stderr.strip()[:100]
        )

    # --- in process, so the emitted reason can be inspected directly ---------
    original = g.check

    def exploding(_segment):
        raise RuntimeError("injected: rule engine fault")

    captured = io.StringIO()
    stdin, stdout, stderr = sys.stdin, sys.stdout, sys.stderr
    status = None
    g.check = exploding
    try:
        sys.stdin = io.StringIO(payload("ls -la"))
        sys.stdout = captured
        sys.stderr = io.StringIO()
        g.main()
    except SystemExit as exc:
        status = exc.code
    except BaseException as exc:
        problems.append(
            "main() raised %s rather than exiting. An uncaught exception exits 1, which "
            "Claude Code reports as a non-blocking error before running the command"
            % type(exc).__name__
        )
    finally:
        sys.stdin, sys.stdout, sys.stderr = stdin, stdout, stderr
        g.check = original

    if status != g.BLOCKED_EXIT:
        problems.append("main() exited %r on an internal failure, wanted %r"
                        % (status, g.BLOCKED_EXIT))
    written = captured.getvalue()
    if not written.strip():
        problems.append(
            "a fault while evaluating a command wrote no decision at all - the exit "
            "status blocks, but nothing tells the reader why"
        )
    else:
        try:
            block = json.loads(written)["hookSpecificOutput"]
        except (ValueError, KeyError, TypeError) as exc:
            problems.append("the failure decision is not usable JSON (%s): %r"
                            % (type(exc).__name__, written[:100]))
            block = {}
        if block.get("permissionDecision") != "deny":
            problems.append("in process, an internal failure decided %r, wanted deny"
                            % block.get("permissionDecision"))
        reason = block.get("permissionDecisionReason") or ""
        if "internal failure" not in reason:
            problems.append(
                "the failure reason does not identify itself as an internal guard "
                "failure: %r" % reason[:90]
            )
        if "not by a rule" not in reason:
            problems.append(
                "the failure reason does not separate itself from a rule decision, which "
                "is what the reader has to be able to tell apart: %r" % reason[:90]
            )
        if "Traceback" in reason or "RuntimeError" not in reason:
            problems.append(
                "the reason should name the exception without pasting a traceback: %r"
                % reason[:120]
            )
        if written.count("hookSpecificOutput") != 1:
            problems.append("more than one decision was written for one payload")

    # --- the outer belt, which is the only thing covering read_command() -----
    # A fault there escapes main() entirely, so neither branch checked above can catch
    # it. The fault is injected after the command has been read, so a command really was
    # in hand: "we could not tell whether there was a command" has to block for the same
    # reason "we could not evaluate it" does.
    late = tmp / "late-fault-guard.py"
    text = GUARD.read_text()
    if text.count("\n    return command\n") != 1:
        return problems + [
            "cannot inject a late fault: read_command() does not end where this test "
            "expects it"
        ]
    late.write_text(text.replace("\n    return command\n",
                                 "\n" + INJECT_LATE_FAULT + "\n", 1))

    proc = run_hook(payload("ls -la"), late)
    if "Traceback" in proc.stderr:
        problems.append(
            "a fault outside main()'s own handling escaped as a traceback, which exits 1 "
            "and lets the command run: %s" % proc.stderr.strip()[-110:]
        )
    if proc.returncode != g.BLOCKED_EXIT:
        problems.append(
            "a fault outside main()'s own handling exited %d, wanted %d - the outer belt "
            "in __main__ must block rather than return" % (proc.returncode, g.BLOCKED_EXIT)
        )
    try:
        late_decision = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
    except (ValueError, KeyError, TypeError):
        late_decision = None
    if late_decision != "deny":
        problems.append(
            "the outer belt decided %r, wanted deny" % late_decision
        )
    if "MemoryError" not in (proc.stdout + proc.stderr):
        problems.append("the outer belt does not name the exception it caught")

    # ...and the same injected copy still passes a payload with no command through, so
    # the belt is firing on the fault rather than on everything.
    proc = run_hook('{"tool_name": "Bash"}', late)
    if proc.returncode != 0 or proc.stdout.strip():
        problems.append(
            "with the late fault injected, a payload carrying no command exited %d and "
            "wrote %r - the no-command pass-through must survive"
            % (proc.returncode, proc.stdout[:60])
        )

    # --- the control ---------------------------------------------------------
    # Without any injected fault the same command still passes through. Without this, a
    # hook that blocked everything would satisfy every assertion above.
    proc = run_hook(payload("ls -la"))
    if proc.returncode != 0 or proc.stdout.strip():
        problems.append(
            "with the engine intact, 'ls -la' exited %d and wrote %r - the injected-fault "
            "case proves nothing if the hook blocks this anyway"
            % (proc.returncode, proc.stdout[:60])
        )
    for command, want in (("git push", "ask"), ("git add .", "deny")):
        got, _reason = outcome(run_hook(payload(command)))
        if got != want:
            problems.append(
                "with the engine intact, %r decided %r, wanted %r - failing closed must "
                "not have changed a normal rule decision" % (command, got, want)
            )
    return problems


# --------------------------------------------------------------------------
# Timeout containment
#
# `--timeout N` is the only bound the orchestrator has on a delegated run, and the
# skill tells Claude to start the long tiers in the background - so a dispatcher
# that does not return is not a slow run, it is a result nobody is waiting to
# notice the absence of. The old timeout path sent SIGKILL to the one pid it had
# spawned and then read the pipes with no bound; a grandchild holding the inherited
# stdout kept a 2-second timeout hanging past 20. Both halves are exercised below,
# because either one alone still hangs.
#
# Everything here runs stub executables out of a temporary directory. No agent CLI
# is invoked, nothing is signalled by name, and the only process group ever
# signalled is one a stub reported for itself - `pkill opencode` in a test suite is
# how someone's real editor session dies.
# --------------------------------------------------------------------------

# What the assertion allows: the requested timeout plus the dispatcher's own two
# grace periods and its reap, plus room for a loaded CI or WSL box. Generous on
# purpose - the bug being guarded against is unbounded, so proving "bounded at all"
# is the point and millisecond precision would only make the suite flaky.
TIMEOUT_BOUND_SECONDS = 15.0

# A harder bound outside the dispatcher, so a regression cannot hang the suite: at
# this point the run is abandoned and reported as a failure rather than waited on.
TIMEOUT_HARNESS_SECONDS = 25.0

# How long the stubs stay alive if nothing stops them. Longer than both bounds
# above, so a stub that is merely slept out rather than killed fails the test.
STUB_SLEEP_SECONDS = 45

# A stub CLI's child, standing in for what a real agent leaves running: a shell per
# tool call, a language server, an MCP process. It inherits the dispatcher's stdout
# and stderr, which is the entire point - holding those open after the CLI itself
# was killed is what used to make the recovery read never return.
#
#   argv: <seconds> <heartbeat> <sigterm-note|-> [escape]
#
# The heartbeat file is rewritten ten times a second. That is what proves the
# process stopped, rather than a single instantaneous pid check that a recycled pid
# would answer wrongly: a heartbeat that has not advanced after several intervals
# means this process is not running, whoever owns the pid now.
#
# `sigterm-note` records SIGTERM and carries on instead of dying from it. A
# descendant that survives SIGTERM and is nevertheless gone afterwards can only have
# been killed by the second stage, so the two files together prove both signals
# landed rather than asserting that one of them theoretically would.
#
# `escape` calls setsid, leaving the delegated run's process group entirely while
# keeping the inherited pipes. Nothing the dispatcher signals can reach it - which
# is how the bound on the recovery read gets tested rather than assumed.
DESCENDANT = '''#!/usr/bin/env python3
import os, signal, sys, time

seconds, heartbeat, note = float(sys.argv[1]), sys.argv[2], sys.argv[3]
if "escape" in sys.argv[4:]:
    os.setsid()
if note != "-":
    signal.signal(signal.SIGTERM, lambda *_: open(note, "w").write("seen\\n"))

beat = 0
deadline = time.monotonic() + seconds
while time.monotonic() < deadline:
    beat += 1
    with open(heartbeat, "w") as fh:
        fh.write("%d %d\\n" % (os.getpid(), beat))
    time.sleep(0.1)
'''

# The stub CLI itself. It records its own pid before anything else: with
# start_new_session that pid is also its process group id, which is the only handle
# the cleanup below will signal.
STUB_WITH_DESCENDANT = """#!/bin/sh
echo $$ > "%(session)s"
printf '%%s\\n' '%(preamble)s'
"%(python)s" "%(descendant)s" %(seconds)s "%(heartbeat)s" "%(note)s" %(extra)s &
echo $! > "%(pidfile)s"
sleep %(seconds)s
"""

STUB_ALONE = """#!/bin/sh
echo $$ > "%(session)s"
printf '%%s\\n' '%(preamble)s'
sleep %(seconds)s
"""

PREAMBLE = "stub-said-this-before-hanging"


def delegable_model():
    """A model the routing file marks as delegated to OpenCode, or None."""
    routing = json.loads((ROOT / "config" / "model-routing.json").read_text())
    return next(
        (name for name, entry in routing["models"].items()
         if entry.get("executor") == "opencode" and entry.get("id")),
        None,
    )


def reap_leaked_session(session_file, problems, label):
    """Kill a stub tree the dispatcher failed to contain, by its own group id alone.

    Only ever reached when a test has already failed, and only ever given the pid
    the stub wrote for itself. The check against this process's own group is the
    same one the dispatcher makes and is here for the same reason: killpg on the
    test runner's group ends the suite and the shell that started it.
    """
    try:
        pid = int(session_file.read_text().strip())
    except (OSError, ValueError):
        return
    if pid <= 0 or pid == os.getpgid(0):
        problems.append("%s: refusing to signal process group %s" % (label, pid))
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def descendant_gone(pid, marker, seconds=3.0):
    """Whether that pid has stopped being the marked descendant, within a bound.

    A bare `os.kill(pid, 0)` answers the wrong question twice over: it is true for a
    zombie, and it is true again once the kernel has handed the number to something
    unrelated. Where /proc is available the marker settles both - the descendant's
    argv contains a path unique to this test's temporary directory, so a recycled
    pid reads as gone rather than as a survivor.
    """
    deadline = time.monotonic() + seconds
    while True:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError):
            return True
        except OSError:
            return True
        cmdline = Path("/proc/%d/cmdline" % pid)
        if cmdline.exists():
            try:
                if marker.encode() not in cmdline.read_bytes():
                    return True     # the pid was reused; the descendant itself is gone
            except OSError:
                return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def stub_run(case, tmp, *, body, agent="opencode", mode="implement", timeout="1",
             env_extra=None):
    """Run the real dispatcher against one stub CLI. Returns (result, seconds, proc).

    `result` is the parsed result JSON, or None if the dispatcher produced none -
    including the case this whole section exists for, where it never returned at all
    and the harness bound had to abandon it.

    `env_extra` overlays the dispatcher's environment, which is how the encoding
    section below starts a run under a locale that is not this suite's.
    """
    home = tmp / case
    bin_dir, repo, work = home / "bin", home / "repo", home / "work"
    for path in (bin_dir, repo / ".git", work):
        path.mkdir(parents=True)
    stub = bin_dir / agent
    stub.write_text(body)
    stub.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = "%s:/usr/bin:/bin" % bin_dir
    env["TMPDIR"] = str(work)       # so each run's workspace goes with the test
    env.update(env_extra or {})
    argv = [sys.executable, str(ROOT / "scripts" / "delegate"),
            "--agent", agent, "--mode", mode, "--tier", "FAST",
            "--cwd", str(repo), "--timeout", timeout]
    if agent == "opencode":
        argv += ["--model", delegable_model()]

    started = time.monotonic()
    try:
        proc = subprocess.run(argv, input="stub brief", capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=env, timeout=TIMEOUT_HARNESS_SECONDS)
    except subprocess.TimeoutExpired:
        return None, time.monotonic() - started, None
    elapsed = time.monotonic() - started
    try:
        return json.loads(proc.stdout), elapsed, proc
    except ValueError:
        return None, elapsed, proc


def check_timeout_bounds(tmp):
    """A timeout must bound the whole tree, and the dispatcher must always return.

    Six stubs, each a different way for a timed-out run to keep hold of the pipes:
    nothing at all, a descendant that dies on SIGTERM, one that refuses to, one that
    has left the process group so no signal can reach it, and the two controls that
    say the containment did not change what an ordinary run does.
    """
    problems = []
    if delegable_model() is None:
        return ["no delegable model in the routing file to drive the dispatcher with"]

    def paths(case):
        home = tmp / case
        home.mkdir(parents=True, exist_ok=True)
        return {
            "session": home / "session", "heartbeat": home / "heartbeat",
            "note": home / "sigterm", "pidfile": home / "descendant.pid",
            "descendant": home / "descendant.py",
        }

    def with_descendant(case, extra="", note=False):
        p = paths(case)
        p["descendant"].write_text(DESCENDANT)
        p["descendant"].chmod(0o755)
        return STUB_WITH_DESCENDANT % {
            "session": p["session"], "preamble": PREAMBLE, "python": sys.executable,
            "descendant": p["descendant"], "seconds": STUB_SLEEP_SECONDS,
            "heartbeat": p["heartbeat"], "note": p["note"] if note else "-",
            "pidfile": p["pidfile"], "extra": extra,
        }, p

    def timed_out(case, result, elapsed, proc, want_status="timeout"):
        """The properties every one of these runs must have, whatever it spawned."""
        local = []
        if result is None:
            local.append(
                "%s: the dispatcher produced no result within %gs - this is the hang"
                % (case, TIMEOUT_HARNESS_SECONDS)
            )
            return local
        if elapsed > TIMEOUT_BOUND_SECONDS:
            local.append(
                "%s: returned after %.1fs for a 1s timeout; the bound is %gs"
                % (case, elapsed, TIMEOUT_BOUND_SECONDS)
            )
        if result.get("status") != want_status:
            local.append("%s: status is %r, wanted %r"
                         % (case, result.get("status"), want_status))
        if proc is not None and proc.returncode != 0:
            local.append("%s: the dispatcher exited %s; a result is still a result"
                         % (case, proc.returncode))
        if proc is not None and "Traceback" in proc.stderr:
            local.append("%s: the dispatcher raised: %s"
                         % (case, proc.stderr.strip().splitlines()[-1][:120]))
        for field in ("workspace", "transcript", "agent_path", "agent_real_path"):
            if not result.get(field):
                local.append("%s: the result lost %s" % (case, field))
        if want_status == "timeout":
            if result.get("blocker_reason") != "timeout":
                local.append("%s: blocker_reason is %r"
                             % (case, result.get("blocker_reason")))
            written = Path(result["workspace"]) / "result.json"
            if not written.exists():
                local.append("%s: no result.json reached the workspace" % case)
        return local

    # --- 1. nothing but the CLI itself ------------------------------------
    # The plain path, and the one that already worked. It is here so that a fix
    # aimed at descendants cannot quietly break the case that has none.
    p = paths("direct")
    body = STUB_ALONE % {"session": p["session"], "preamble": PREAMBLE,
                         "seconds": STUB_SLEEP_SECONDS}
    result, elapsed, proc = stub_run("direct", tmp, body=body)
    problems += timed_out("direct child", result, elapsed, proc)
    reap_leaked_session(p["session"], problems, "direct child")

    # --- 2. a descendant holding the inherited stdout ----------------------
    # The reproduced bug. Under the old code the CLI died, this process did not,
    # and the second communicate() waited on a pipe it was still holding.
    body, p = with_descendant("grandchild")
    result, elapsed, proc = stub_run("grandchild", tmp, body=body)
    problems += timed_out("grandchild", result, elapsed, proc)
    reap_leaked_session(p["session"], problems, "grandchild")
    if result is not None:
        # The descendant is gone, shown two ways: its heartbeat has stopped
        # advancing, which no live copy of it could allow, and its pid is no longer
        # that process.
        before = p["heartbeat"].read_bytes() if p["heartbeat"].exists() else b""
        time.sleep(0.6)     # six heartbeat intervals
        after = p["heartbeat"].read_bytes() if p["heartbeat"].exists() else b""
        if before != after:
            problems.append(
                "grandchild: the descendant is still running - its heartbeat went "
                "from %r to %r after the dispatcher reported a timeout"
                % (before, after)
            )
        try:
            pid = int(p["pidfile"].read_text().strip())
        except (OSError, ValueError):
            problems.append("grandchild: the stub recorded no descendant pid")
        else:
            if not descendant_gone(pid, str(p["descendant"])):
                problems.append(
                    "grandchild: descendant pid %d is still running the stub's "
                    "child after the dispatcher returned" % pid
                )
        # Output produced before the kill survives into the transcript.
        transcript = Path(result["transcript"])
        if transcript.exists() and PREAMBLE not in transcript.read_text():
            problems.append(
                "grandchild: the transcript lost what the stub printed before it hung"
            )
        if transcript.exists() and transcript.read_text().count(PREAMBLE) > 1:
            problems.append(
                "grandchild: the transcript repeats the stub's output - the partial "
                "read and the drain were both counted"
            )

    # --- 3. a descendant that refuses SIGTERM ------------------------------
    # Proof that the second stage is real. This process records SIGTERM and keeps
    # running, so its absence afterwards cannot be explained by the first signal.
    body, p = with_descendant("stubborn", note=True)
    result, elapsed, proc = stub_run("stubborn", tmp, body=body)
    problems += timed_out("sigterm-resistant", result, elapsed, proc)
    reap_leaked_session(p["session"], problems, "sigterm-resistant")
    if result is not None:
        if not p["note"].exists():
            problems.append(
                "sigterm-resistant: the descendant never received SIGTERM, so the "
                "first stage never reached the group"
            )
        before = p["heartbeat"].read_bytes() if p["heartbeat"].exists() else b""
        time.sleep(0.6)
        after = p["heartbeat"].read_bytes() if p["heartbeat"].exists() else b""
        if before != after:
            problems.append(
                "sigterm-resistant: the descendant survived - it ignores SIGTERM, so "
                "SIGKILL either was not sent to the group or did not reach it"
            )

    # --- 4. a descendant that has left the process group -------------------
    # Nothing the dispatcher signals can reach a process that called setsid, and it
    # still holds the pipes. This is the case the bound on the recovery read exists
    # for: the transcript cannot be completed, so the run is reported without it.
    body, p = with_descendant("escaped", extra="escape")
    result, elapsed, proc = stub_run("escaped", tmp, body=body)
    problems += timed_out("escaped descendant", result, elapsed, proc)
    if result is not None:
        stderr_file = Path(result["workspace"]) / "agent-stderr.txt"
        if stderr_file.exists() and "delegate:" not in stderr_file.read_text():
            problems.append(
                "escaped descendant: the dispatcher gave up reading the pipes and "
                "left no note saying so"
            )
        transcript = Path(result["transcript"])
        if transcript.exists() and PREAMBLE not in transcript.read_text():
            problems.append(
                "escaped descendant: output buffered before the timeout was dropped "
                "when the drain gave up"
            )
    # This stub deliberately escapes containment, so the test cleans up after it -
    # by the pid the descendant reported, never by name.
    reap_leaked_session(p["session"], problems, "escaped descendant")
    try:
        os.killpg(int(p["pidfile"].read_text().strip()), signal.SIGKILL)
    except (OSError, ValueError):
        pass

    # --- 5. the child exits on the timeout boundary ------------------------
    # Whether this lands as a timeout or as an ordinary exit is a scheduling
    # question with no right answer, so what is asserted is that neither outcome
    # goes through a process-control race and out as a traceback.
    for attempt in range(3):
        p = paths("race%d" % attempt)
        body = STUB_ALONE % {"session": p["session"], "preamble": PREAMBLE,
                             "seconds": 1}
        result, elapsed, proc = stub_run("race%d" % attempt, tmp, body=body)
        case = "boundary race %d" % attempt
        if result is None:
            problems.append("%s: no result was produced" % case)
            continue
        if result.get("status") not in ("timeout", "completed", "failed"):
            problems.append("%s: status is %r" % (case, result.get("status")))
        if proc.returncode != 0:
            problems.append("%s: the dispatcher exited %s" % (case, proc.returncode))
        if "Traceback" in proc.stderr:
            problems.append("%s: the dispatcher raised: %s"
                            % (case, proc.stderr.strip().splitlines()[-1][:120]))
        if elapsed > TIMEOUT_BOUND_SECONDS:
            problems.append("%s: took %.1fs" % (case, elapsed))

    # --- 6. an ordinary successful run -------------------------------------
    # The control. Giving the run its own session must not change what a CLI that
    # simply works looks like, transcript and parsed report included.
    body = ('#!/bin/sh\n'
            'echo \'{"status": "completed", "summary": "stub", "touched_files": []}\'\n')
    result, elapsed, proc = stub_run("success", tmp, body=body, timeout="30")
    if result is None:
        problems.append("success control: the dispatcher produced no result")
    else:
        if result.get("status") != "completed":
            problems.append("success control: status is %r" % result.get("status"))
        if result.get("exit_code") != 0:
            problems.append("success control: exit_code is %r" % result.get("exit_code"))
        if result.get("result_block") != "present":
            problems.append("success control: the stub's report was not parsed out")
        if elapsed > TIMEOUT_BOUND_SECONDS:
            problems.append("success control: took %.1fs for a run that exits at once"
                            % elapsed)

    # --- 7. an ordinary non-zero exit --------------------------------------
    # The other control. A failure is a failure; nothing in the timeout path may
    # rewrite one into a timeout. Output is printed because a silent non-zero exit
    # from a CLI passed --variant is separately reported as a usage error.
    body = '#!/bin/sh\necho "stub failed"\nexit 3\n'
    result, elapsed, proc = stub_run("failure", tmp, body=body, timeout="30")
    if result is None:
        problems.append("failure control: the dispatcher produced no result")
    else:
        if result.get("status") != "failed":
            problems.append("failure control: status is %r, wanted 'failed'"
                            % result.get("status"))
        if result.get("exit_code") != 3:
            problems.append("failure control: exit_code is %r, wanted 3"
                            % result.get("exit_code"))
        if result.get("blocker_reason") is not None:
            problems.append("failure control: an ordinary failure was given %r"
                            % result.get("blocker_reason"))

    # --- 8. the same containment on the agent that is fed on stdin ---------
    # Codex takes its brief through a pipe rather than argv, so the timeout path has
    # a stdin to deal with as well as the two output pipes.
    p = paths("codex")
    body = STUB_ALONE % {"session": p["session"], "preamble": PREAMBLE,
                         "seconds": STUB_SLEEP_SECONDS}
    result, elapsed, proc = stub_run("codex", tmp, body=body, agent="codex",
                                     mode="review")
    problems += timed_out("codex on stdin", result, elapsed, proc)
    if result is not None and result.get("verdict") != "BLOCKED":
        problems.append("codex on stdin: a timed-out review lost its BLOCKED verdict")
    reap_leaked_session(p["session"], problems, "codex on stdin")
    return problems


# --------------------------------------------------------------------------
# The byte/text boundary
#
# An agent's output is bytes, and nothing guarantees they are valid UTF-8. Before
# the fix these cases were reported against, `Popen(..., text=True)` decoded with
# the locale's encoding and errors="strict", so one stray byte raised
# UnicodeDecodeError inside `communicate()`: the dispatcher exited 1 with a
# traceback, printed no result JSON, and never wrote the transcript - losing the
# record of work the agent had already finished. The write side was the same bug
# facing the other way: `write_text` with no encoding raises UnicodeEncodeError
# under an ASCII locale for a transcript that decoded perfectly.
#
# What is asserted throughout is the transport invariant, not report validity:
# arbitrary bytes must never stop the dispatcher producing its structured result.
# Whether a report survives its own bytes is the parser's business, and case 3
# exists to keep those two apart - a report that replacement made unparseable is
# correctly reported missing, and fabricating one instead would be the worse bug.
#
# The stubs here write to `sys.stdout.buffer` rather than going through `echo` or
# `printf`: what a shell builtin does with a byte outside ASCII differs between
# shells, and a test of byte handling cannot have a shell deciding which bytes the
# dispatcher sees.
# --------------------------------------------------------------------------

# Invalid UTF-8 that is unambiguous about being invalid: 0xff and 0xfe are start
# bytes no UTF-8 sequence begins with, so a decoder cannot resynchronise on them
# and the failure is not a matter of where a read boundary happened to fall.
BAD = b"\xff\xfe"

# A truncated multi-byte character - the realistic way a stray byte arrives, from a
# character split across a pipe read rather than from binary data.
TRUNCATED = "✓".encode()[:2]

# Real text, to prove the policy is UTF-8 rather than something ASCII-safe and
# lossy. Arabic (multi-byte), an emoji (outside the BMP, a surrogate pair in JSON)
# and a combining accent - the three shapes that go wrong separately.
UNICODE_SUMMARY = "اختبار ✓ 🚀 café"

BYTE_STUB = '''#!/usr/bin/env python3
"""A stub CLI whose output is exact bytes, chosen by the test, not by a shell."""
import sys, time

sys.stdout.buffer.write(%(out)r)
sys.stdout.buffer.flush()
sys.stderr.buffer.write(%(err)r)
sys.stderr.buffer.flush()
time.sleep(%(sleep)r)
sys.exit(%(code)r)
'''


BYTE_STUB_ESCAPED = '''#!/usr/bin/env python3
"""Exact bytes, then a descendant outside this run's process group.

The descendant inherits the dispatcher's stdout and stderr and calls setsid, so
nothing the timeout path signals can reach it and the bounded drain cannot
complete. That is the only way to reach the dispatcher's last output path: the
partial buffer CPython attached to the TimeoutExpired, which is raw bytes.
"""
import os, subprocess, sys, time

open(%(session)r, "w").write("%%d\\n" %% os.getpid())
sys.stdout.buffer.write(%(out)r)
sys.stdout.buffer.flush()
sys.stderr.buffer.write(%(err)r)
sys.stderr.buffer.flush()
child = subprocess.Popen(
    [sys.executable, %(descendant)r, %(seconds)r, %(heartbeat)r, "-", "escape"]
)
open(%(pidfile)r, "w").write("%%d\\n" %% child.pid)
time.sleep(float(%(seconds)r))
'''


def byte_stub(out=b"", err=b"", sleep=0, code=0):
    """A stub that emits exactly `out` and `err`, then optionally hangs.

    `sleep` is what makes the same stub serve the timeout case: the bytes are
    flushed before it starts, so they are in the pipe when the deadline arrives and
    the salvage path is the thing that has to decode them.
    """
    return BYTE_STUB % {"out": out, "err": err, "sleep": sleep, "code": code}


def report_bytes(*summary):
    """A valid implement report, as bytes, whose summary is assembled from pieces.

    A `str` piece is encoded as UTF-8; a `bytes` piece is spliced in raw. The point
    is a report that is structurally fine and only textually broken - the invalid
    bytes sit inside a string value that JSON's own syntax still delimits - because
    that is the case where a dispatcher which survives the bytes should still come
    back with a parsed report.

    The document itself is built by `json.dumps` rather than by hand, so what is
    being tested is the dispatcher's decoding and not this fixture's escaping. The
    placeholders are ASCII for that reason: `json.dumps` rewrites a control
    character into an escape sequence, which would leave nothing to substitute, so
    each one is checked to have survived rather than assumed to have.
    """
    marks, parts = {}, []
    for index, piece in enumerate(summary):
        if isinstance(piece, str):
            parts.append(piece)
            continue
        mark = "@@raw%d@@" % index
        marks[mark] = piece
        parts.append(mark)
    document = json.dumps(
        {"status": "completed", "summary": "".join(parts), "touched_files": []},
        ensure_ascii=False,
    ).encode()
    for mark, raw in marks.items():
        if mark.encode() not in document:
            raise AssertionError(
                "report_bytes: the placeholder %s did not survive json.dumps, so the "
                "raw bytes never reached the fixture" % mark
            )
        document = document.replace(mark.encode(), raw)
    return document


def locale_encoding(env_extra):
    """What default encoding a Python started with this environment actually gets.

    Recorded rather than asserted. CPython coerces the C locale to C.UTF-8 (PEP 538)
    and honours PYTHONUTF8, so an environment that names an ASCII locale does not
    always produce one, and a test that asserted it did would fail for a reason that
    has nothing to do with this dispatcher. What the locale case asserts is the
    dispatcher's behaviour; this string only tells whoever reads a failure whether
    the locale had bitten at all.
    """
    env = dict(os.environ)
    env.update(env_extra)
    try:
        proc = subprocess.run(
            [sys.executable, "-c", "import sys; print(sys.stdout.encoding)"],
            capture_output=True, text=True, encoding="ascii", errors="replace",
            env=env, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return proc.stdout.strip() or "unknown"


def check_output_encoding(tmp):
    """Arbitrary bytes from an agent must never cost the dispatcher its result.

    Six cases: an invalid byte in an otherwise usable report, one on stderr, stdout
    that is nothing but invalid bytes, invalid bytes on the timeout path, real
    Unicode passing through intact, and a run started under a locale that is not
    this suite's.
    """
    problems = []

    def contract(case, result, proc, *, want_status):
        """The dispatcher's side of the contract, whatever the bytes were.

        Every case checks this: a result on stdout, exit 0, no traceback, the
        artifacts on disk, and a result.json that is valid UTF-8 a consumer can
        load. This is the invariant BUG-003 broke - status and report contents are
        each case's own business.
        """
        local = []
        if result is None:
            local.append(
                "%s: the dispatcher produced no result JSON (exit %s); stderr: %s"
                % (case, proc.returncode if proc else "no return",
                   (proc.stderr or "")[-500:] if proc else "the run was abandoned")
            )
            return local
        if proc.returncode != 0:
            local.append(
                "%s: exit %d, but the contract is 0 whenever a result was produced"
                % (case, proc.returncode)
            )
        if "Traceback" in (proc.stderr or ""):
            local.append("%s: the dispatcher raised: %s"
                         % (case, proc.stderr.strip()[-400:]))
        if result.get("status") != want_status:
            local.append("%s: status %r, wanted %r"
                         % (case, result.get("status"), want_status))
        workspace = Path(result["workspace"])
        for name in ("agent-output.txt", "agent-stderr.txt", "result.json"):
            if not (workspace / name).exists():
                local.append("%s: %s never reached the workspace" % (case, name))
        if result.get("transcript") != str(workspace / "agent-output.txt"):
            local.append("%s: the result does not name its own transcript" % case)
        # The result artifact must be loadable by a consumer that assumes UTF-8,
        # replacement characters and all. json.dumps escapes them, so this is a
        # check that nothing hand-concatenated its way into the file.
        written = workspace / "result.json"
        if written.exists():
            try:
                reloaded = json.loads(written.read_bytes().decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                local.append("%s: result.json is not loadable UTF-8: %s" % (case, exc))
            else:
                if reloaded.get("status") != result.get("status"):
                    local.append(
                        "%s: result.json disagrees with stdout about status (%r vs %r)"
                        % (case, reloaded.get("status"), result.get("status"))
                    )
        return local

    # --- 1. an invalid byte inside an otherwise usable report ---------------
    # The reproduced bug, in its most costly form: the agent did the work and said
    # so correctly, and one byte in a summary used to lose the whole run.
    body = byte_stub(out=report_bytes("abc ", BAD, " xyz") + b"\n")
    result, _, proc = stub_run("bad-stdout", tmp, body=body, timeout="30")
    problems += contract("bad-stdout", result, proc, want_status="completed")
    if result is not None:
        if result.get("result_block") != "present":
            problems.append(
                "bad-stdout: result_block %r - the report was structurally fine and "
                "only its text was undecodable, so it should still parse"
                % result.get("result_block")
            )
        report = result.get("agent_report") or {}
        if report.get("status") != "completed":
            problems.append("bad-stdout: report status %r, wanted 'completed'"
                            % report.get("status"))
        summary = report.get("summary") or ""
        if "�" not in summary:
            problems.append(
                "bad-stdout: the summary %r carries no replacement character, so the "
                "invalid bytes went somewhere other than through the decoder"
                % summary
            )
        if not (summary.startswith("abc") and summary.endswith("xyz")):
            problems.append(
                "bad-stdout: replacement ate the valid text around it: %r" % summary
            )
        transcript = Path(result["transcript"])
        if transcript.exists() and "�" not in transcript.read_text(encoding="utf-8"):
            problems.append(
                "bad-stdout: the transcript has no replacement character where the "
                "invalid bytes were"
            )

    # A truncated multi-byte character, which is how this arrives in practice.
    body = byte_stub(out=report_bytes("abc ", TRUNCATED, " xyz") + b"\n")
    result, _, proc = stub_run("truncated-char", tmp, body=body, timeout="30")
    problems += contract("truncated-char", result, proc, want_status="completed")
    if result is not None and result.get("result_block") != "present":
        problems.append(
            "truncated-char: result_block %r for a report whose only fault is half a "
            "character" % result.get("result_block")
        )

    # --- 2. an invalid byte on stderr -------------------------------------
    # stderr is decoded by the same call and used to take the run down the same way,
    # even when the report on stdout was perfect.
    body = byte_stub(out=report_bytes("a clean report") + b"\n",
                     err=b"warning: " + BAD + b" ignored\n")
    result, _, proc = stub_run("bad-stderr", tmp, body=body, timeout="30")
    problems += contract("bad-stderr", result, proc, want_status="completed")
    if result is not None:
        if result.get("result_block") != "present":
            problems.append(
                "bad-stderr: a clean report on stdout was lost to bytes on stderr "
                "(result_block %r)" % result.get("result_block")
            )
        artifact = Path(result["workspace"]) / "agent-stderr.txt"
        if artifact.exists():
            written = artifact.read_text(encoding="utf-8")
            if "�" not in written:
                problems.append(
                    "bad-stderr: the stderr artifact %r has no replacement character"
                    % written
                )
            if "warning:" not in written or "ignored" not in written:
                problems.append(
                    "bad-stderr: the stderr artifact lost the text around the bad "
                    "bytes: %r" % written
                )

    # --- 3. stdout is nothing but invalid bytes ----------------------------
    # Transport robustness and report validity are different questions. The
    # dispatcher must still return a structured result; the parser must still refuse
    # to find a report in bytes that do not contain one. A fabricated report here
    # would be a worse outcome than a missing one.
    body = byte_stub(out=bytes(range(0x80, 0x100)) * 4 + BAD)
    result, _, proc = stub_run("binary-stdout", tmp, body=body, timeout="30")
    problems += contract("binary-stdout", result, proc, want_status="completed")
    if result is not None:
        if result.get("result_block") not in ("missing", "invalid"):
            problems.append(
                "binary-stdout: result_block %r - there is no report in those bytes"
                % result.get("result_block")
            )
        if result.get("agent_report") is not None:
            problems.append(
                "binary-stdout: a report was invented out of binary noise: %r"
                % (result.get("agent_report"),)
            )
        transcript = Path(result["transcript"])
        if transcript.exists():
            raw = transcript.read_bytes()
            if not raw:
                problems.append("binary-stdout: the transcript is empty")
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                problems.append(
                    "binary-stdout: undecodable bytes reached the transcript "
                    "unreplaced: %s" % exc
                )

    # --- 4. invalid bytes on the timeout path ------------------------------
    # A separate code path with its own conversion: a TimeoutExpired carries the raw
    # chunks CPython had joined, so this is bytes reaching the salvage path rather
    # than the completed read. The timeout's own guarantees have to survive it - a
    # bounded return, the timeout status, and the partial transcript counted once.
    marker = "before-the-bytes"
    body = byte_stub(
        out=marker.encode() + b" " + BAD + b"\n",
        err=b"stderr " + BAD + b"\n",
        sleep=STUB_SLEEP_SECONDS,
    )
    result, elapsed, proc = stub_run("timeout-bytes", tmp, body=body, timeout="1")
    problems += contract("timeout-bytes", result, proc, want_status="timeout")
    if elapsed > TIMEOUT_BOUND_SECONDS:
        problems.append(
            "timeout-bytes: the dispatcher took %.1fs against a 1s timeout - bound is "
            "%.1fs. Invalid bytes must not cost the timeout its bound."
            % (elapsed, TIMEOUT_BOUND_SECONDS)
        )
    if result is not None:
        if result.get("blocker_reason") != "timeout":
            problems.append("timeout-bytes: blocker_reason %r, wanted 'timeout'"
                            % result.get("blocker_reason"))
        transcript = Path(result["transcript"])
        if transcript.exists():
            written = transcript.read_text(encoding="utf-8")
            if marker not in written:
                problems.append(
                    "timeout-bytes: the salvaged transcript lost what the stub printed "
                    "before it hung: %r" % written
                )
            if written.count(marker) > 1:
                problems.append(
                    "timeout-bytes: the transcript repeats the stub's output - the "
                    "partial read and the drain were both counted"
                )
            if "�" not in written:
                problems.append(
                    "timeout-bytes: the salvaged transcript has no replacement "
                    "character, so the salvage path is not decoding the same way: %r"
                    % written
                )

    # --- 4b. invalid bytes on the last output path -------------------------
    # Case 4 does not reach the salvage conversion: the drain completes, and what it
    # returns has already been decoded by the pipes. The only way to the buffer
    # CPython attaches to a TimeoutExpired - raw bytes, whatever the pipes were
    # opened as - is a descendant that has left the process group and still holds
    # them, so the bounded drain expires and the dispatcher reports what it had.
    # That is Slice 3's fallback carrying Slice 4's bytes, and it is the one path
    # where a decode of the wrong kind is invisible to every case above.
    aux = tmp / "salvage-aux"
    aux.mkdir(parents=True, exist_ok=True)
    descendant, session = aux / "descendant.py", aux / "session"
    heartbeat, pidfile = aux / "heartbeat", aux / "pidfile"
    descendant.write_text(DESCENDANT)
    descendant.chmod(0o755)
    body = BYTE_STUB_ESCAPED % {
        "session": str(session), "descendant": str(descendant),
        "seconds": str(STUB_SLEEP_SECONDS), "heartbeat": str(heartbeat),
        "pidfile": str(pidfile),
        "out": marker.encode() + b" " + BAD + b"\n",
        "err": b"stderr " + BAD + b"\n",
    }
    result, elapsed, proc = stub_run("salvaged-bytes", tmp, body=body, timeout="1")
    problems += contract("salvaged-bytes", result, proc, want_status="timeout")
    if elapsed > TIMEOUT_BOUND_SECONDS:
        problems.append(
            "salvaged-bytes: the dispatcher took %.1fs against a 1s timeout - bound "
            "is %.1fs" % (elapsed, TIMEOUT_BOUND_SECONDS)
        )
    if result is not None:
        stderr_file = Path(result["workspace"]) / "agent-stderr.txt"
        if stderr_file.exists() and "delegate:" not in stderr_file.read_text(
                encoding="utf-8"):
            problems.append(
                "salvaged-bytes: the drain did not give up, so this case did not "
                "reach the salvage path it exists to test"
            )
        transcript = Path(result["transcript"])
        if transcript.exists():
            written = transcript.read_text(encoding="utf-8")
            if marker not in written:
                problems.append(
                    "salvaged-bytes: the salvaged transcript lost what the stub wrote "
                    "before the deadline: %r" % written
                )
            if written.count(marker) > 1:
                problems.append(
                    "salvaged-bytes: the salvaged transcript repeats the stub's output"
                )
            if "\ufffd" not in written:
                problems.append(
                    "salvaged-bytes: no replacement character in the salvaged "
                    "transcript - the fallback is not decoding under the same policy "
                    "as the pipes: %r" % written
                )
    # This stub deliberately escapes containment; the test cleans up after it, by
    # the pids the stub reported for itself and its child and never by name.
    reap_leaked_session(session, problems, "salvaged-bytes")
    try:
        os.killpg(int(pidfile.read_text().strip()), signal.SIGKILL)
    except (OSError, ValueError):
        pass

    # --- 5. real Unicode, intact ------------------------------------------
    # The other half of the policy. Replacement is for invalid sequences only; a
    # transport that turned agent output into ASCII-safe mush would pass every case
    # above and be useless for any agent that reports a filename or a message in a
    # language other than English.
    body = byte_stub(out=report_bytes(UNICODE_SUMMARY) + b"\n")
    result, _, proc = stub_run("valid-unicode", tmp, body=body, timeout="30")
    problems += contract("valid-unicode", result, proc, want_status="completed")
    if result is not None:
        summary = (result.get("agent_report") or {}).get("summary")
        if summary != UNICODE_SUMMARY:
            problems.append(
                "valid-unicode: the report's summary came back %r, wanted %r"
                % (summary, UNICODE_SUMMARY)
            )
        if summary and "�" in summary:
            problems.append(
                "valid-unicode: valid UTF-8 was replaced - the decoder is not reading "
                "UTF-8: %r" % summary
            )
        transcript = Path(result["transcript"])
        if transcript.exists():
            raw = transcript.read_bytes()
            if UNICODE_SUMMARY.encode() not in raw:
                problems.append(
                    "valid-unicode: the transcript is not the UTF-8 encoding of what "
                    "the agent wrote: %r" % raw[:200]
                )

    # --- 6. a run started under someone else's locale ----------------------
    # The write-side half of the same bug, and the reason the policy is stated rather
    # than inherited. Under a genuinely ASCII default encoding, an unqualified
    # `write_text` raises UnicodeEncodeError on a transcript that decoded perfectly,
    # and an unqualified `text=True` refuses to decode the Arabic below at all.
    #
    # CPython may coerce this locale away (PEP 538), in which case the case still
    # passes and simply repeats case 5 rather than failing for a reason that is not
    # about this dispatcher - so what is asserted is the dispatcher's behaviour, and
    # the locale that was actually in force is only reported in a failure.
    ascii_locale = {"LC_ALL": "C", "LANG": "C", "LANGUAGE": "C",
                    "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
    observed = locale_encoding(ascii_locale)
    body = byte_stub(out=report_bytes(UNICODE_SUMMARY + " ", BAD) + b"\n")
    result, _, proc = stub_run("ascii-locale", tmp, body=body, timeout="30",
                               env_extra=ascii_locale)
    problems += ["%s (the dispatcher's default encoding was %s)" % (line, observed)
                 for line in contract("ascii-locale", result, proc,
                                      want_status="completed")]
    if result is not None:
        summary = (result.get("agent_report") or {}).get("summary") or ""
        if not summary.startswith(UNICODE_SUMMARY):
            problems.append(
                "ascii-locale: the summary came back %r, wanted it to start with %r - "
                "the dispatcher's default encoding was %s"
                % (summary, UNICODE_SUMMARY, observed)
            )
        if "�" not in summary:
            problems.append(
                "ascii-locale: no replacement character where the invalid bytes were "
                "(default encoding %s): %r" % (observed, summary)
            )
        transcript = Path(result["transcript"])
        raw = transcript.read_bytes() if transcript.exists() else b""
        if raw and UNICODE_SUMMARY.encode() not in raw:
            problems.append(
                "ascii-locale: the transcript was not written as UTF-8 under a %s "
                "locale" % observed
            )
    return problems


def check_group_isolation():
    """Before any group is signalled, prove the group is not this process's own.

    This is the check that makes everything above safe to run at all. A child
    spawned the way the dispatcher spawns one has a group to itself; a child spawned
    without that shares the group of whatever started it, and `killpg` on that
    number takes down the test runner, the shell it was launched from, and the
    editor session around them. That is not a hypothetical hazard - it is what
    happened while this fix was being written, which is why the dispatcher compares
    against `os.getpgid(0)` and why it is asserted here rather than trusted.
    """
    problems = []
    if os.name != "posix":
        return problems

    sleeper = [sys.executable, "-c", "import time; time.sleep(30)"]
    own = subprocess.Popen(sleeper, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           start_new_session=True)
    shared = subprocess.Popen(sleeper, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        pgid = d.delegated_group(own)
        if pgid is None:
            problems.append(
                "delegated_group found no group for a child given its own session, so "
                "the timeout path can only reach the direct child"
            )
        elif pgid == os.getpgid(0) or pgid != own.pid:
            problems.append(
                "delegated_group returned %r for a session leader whose pid is %d"
                % (pgid, own.pid)
            )
        if d.delegated_group(shared) is not None:
            problems.append(
                "delegated_group offered up this process's own group for a child that "
                "shares it - signalling that group would kill the test runner"
            )
    finally:
        for proc in (own, shared):
            d.terminate_process_tree(proc)      # must fall back to the child alone
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                problems.append("a probe process outlived terminate_process_tree")
            proc.stdout.close()
            proc.stderr.close()
    if shared.returncode is None:
        problems.append("the shared-group probe was left running")

    # An already-finished child has no group left worth signalling, and cleaning up
    # after it must not raise - the timeout path's only job at that point is to
    # produce a result.
    done = subprocess.Popen([sys.executable, "-c", ""], stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, start_new_session=True)
    done.communicate(timeout=30)
    if d.delegated_group(done) is not None:
        problems.append("delegated_group returned a group for a reaped child")
    try:
        notes = d.terminate_process_tree(done)
    except Exception as exc:
        problems.append("terminate_process_tree raised %s on a reaped child"
                        % type(exc).__name__)
    else:
        if notes:
            problems.append("terminate_process_tree complained about a clean exit: %r"
                            % notes)
    if d.group_alive(done.pid) and done.pid != os.getpgid(0):
        problems.append("group_alive says a finished child's group still has members")

    # The partial output a TimeoutExpired carries is bytes even when the pipes were
    # opened in text mode, and the drain has to hand back str either way.
    for given, want in ((None, ""), (b"part", "part"), ("part", "part"),
                        (b"\xff", "\ufffd")):
        got = d.as_text(given)
        if got != want:
            problems.append("as_text(%r) is %r, wanted %r" % (given, got, want))
    return problems


def main():
    failures = []

    for name, mode, text, want_state, want_value in CASES:
        try:
            state, report = extract(text, mode)
        except Exception as exc:  # a parser of untrusted output must never raise
            failures.append("%s: raised %s" % (name, type(exc).__name__))
            continue
        key = d.REPORT_DISCRIMINATORS[mode][0]
        got_value = report.get(key) if report else None
        if state != want_state:
            failures.append("%s: state %r, wanted %r" % (name, state, want_state))
        elif want_value is not None and got_value != want_value:
            failures.append("%s: value %r, wanted %r" % (name, got_value, want_value))

    for name, mode, text, budget in TIMED:
        started = time.monotonic()
        try:
            extract(text, mode)
        except Exception as exc:
            failures.append("%s: raised %s" % (name, type(exc).__name__))
            continue
        elapsed = time.monotonic() - started
        if elapsed > budget:
            failures.append("%s: took %.1fs, budget %.1fs" % (name, elapsed, budget))

    for name, mode, report, want_removed, want_kept in STRIP:
        before = dict(report) if report else {}
        got_removed = d.strip_off_contract(report, mode)
        if got_removed != want_removed:
            failures.append(
                "%s: removed %r, wanted %r" % (name, got_removed, want_removed)
            )
        for key in want_kept:
            if report is None or key not in report or report[key] != before[key]:
                failures.append("%s: %r did not survive intact" % (name, key))

    failures.extend("nested report: " + line for line in check_nested_report_selection())
    failures.extend("oversized: " + line for line in check_oversized_enclosure())
    failures.extend("nesting invariant: " + line for line in check_nesting_is_structural())
    failures.extend("boundaries: " + line for line in check_command_boundaries())
    failures.extend("destructive: " + line for line in check_destructive_boundaries())
    failures.extend("mode matrix: " + line for line in check_matrix())
    failures.extend("working directory: " + line for line in check_working_directory())
    failures.extend("invocation: " + line for line in check_dispatcher_invocation())
    failures.extend("hook payload: " + line for line in check_hook_payloads())
    failures.extend("hook response: " + line for line in check_hook_response_shape())
    failures.extend("hook precedence: " + line for line in check_decision_precedence())
    failures.extend("shipped rules: " + line for line in check_shipped_rules_load())
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend(
            "hook fault: " + line
            for line in check_internal_failure_is_fail_closed(Path(tmp))
        )
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend(
            "boundary faults: " + line
            for line in check_boundary_config_faults(Path(tmp))
        )
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend(
            "agent path: " + line for line in check_agent_path_record(Path(tmp))
        )
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend("--cwd: " + line for line in check_cwd_validation(Path(tmp)))
    failures.extend("group isolation: " + line for line in check_group_isolation())
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend("timeout: " + line for line in check_timeout_bounds(Path(tmp)))
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend(
            "encoding: " + line for line in check_output_encoding(Path(tmp))
        )

    print(
        "%d cases, %d timed, %d strip, %d nested, %d oversized, %d boundary rules, "
        "%d hook payloads, %d precedence, %d boundary faults, %d destructive decisions, "
        "mode matrix, invocation, "
        "nesting invariant, hook response, hook fault, agent path, adapters, --cwd, "
        "group isolation, timeout containment and the byte/text boundary checked"
        % (len(CASES), len(TIMED), len(STRIP), len(NESTED_SELECTION),
           len(OVERSIZED_ENCLOSURE) + len(INDEPENDENT_AFTER_TRANSCRIPT)
           + len(ENCLOSURE_GATE),
           len(BOUNDARIES["rules"]), len(HOOK_PAYLOADS), len(PRECEDENCE),
           len(BOUNDARY_FAULTS), len(DESTRUCTIVE_POLICY))
    )

    regressed = []
    for name, mode, text, current in KNOWN_GAPS:
        state, _ = extract(text, mode)
        if state != current:
            regressed.append(name)
    if KNOWN_GAPS:
        print("\n%d known gap(s), documented, not counted as failures:" % len(KNOWN_GAPS))
        for name, _, _, _ in KNOWN_GAPS:
            print("  - %s" % name)
    if regressed:
        print("\nA known gap no longer behaves as recorded. If it was fixed, move it into")
        print("CASES; if it changed some other way, it needs looking at:")
        for name in regressed:
            print("  - %s" % name)

    if failures:
        print("\nFAILED (%d):" % len(failures))
        for line in failures:
            print("  - %s" % line)
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
