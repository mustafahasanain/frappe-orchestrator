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

Two fixtures are real captured stdout from `codex exec`, not invented samples. The
inner-fence one is the output that broke the previous parser: its own `detail` string
contains a fenced example, and a regex delimiting a block on triple backticks truncates
the body there. A tidier stub is exactly how that defect survived.

No framework and nothing to install: standard library only.
"""

import importlib.machinery
import importlib.util
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


def fixture(name):
    return (FIXTURES / name).read_text()


d = load_dispatcher()
extract = d.extract_report

BANNER = "OpenAI Codex v0.149.0\n--------\nmodel: gpt-5.6-sol\n--------\n"
FOOTER = "\ntokens used\n10,078\n"
BLOCK = '```json\n{"verdict": "PASS", "summary": "s", "findings": []}\n```'
DEEP = '{"a":' * 10000 + "1" + "}" * 10000

ONBOARD = ('{"analysis": "complete", "summary": "s", "findings": [], '
           '"uncertain": []}')

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

    failures.extend("mode matrix: " + line for line in check_matrix())
    failures.extend("working directory: " + line for line in check_working_directory())

    print(
        "%d cases, %d timed, %d strip, mode matrix and working directory checked"
        % (len(CASES), len(TIMED), len(STRIP))
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
