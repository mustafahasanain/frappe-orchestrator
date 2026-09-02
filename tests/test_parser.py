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
    routing = json.loads((ROOT / "config" / "model-routing.json").read_text())
    model = next(
        (name for name, entry in routing["models"].items()
         if entry.get("executor") == "opencode" and entry.get("id")),
        None,
    )
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
    ("bench migrate", "ask"),
    ("mysql -u root", "ask"),
    ("ls -la", "allow"),
)

# What the same commands get when the data is intact. The control: it runs against a copy
# of the tree, so a degraded answer everywhere cannot be the copying.
INTACT_EXPECTED = (
    ("git push", "ask"),
    ("git add .", "deny"),
    ("bench migrate", "ask"),
    ("mysql -u root", "ask"),
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

    failures.extend("boundaries: " + line for line in check_command_boundaries())
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

    print(
        "%d cases, %d timed, %d strip, %d boundary rules, %d hook payloads, "
        "%d precedence, %d boundary faults, mode matrix, invocation, hook response, "
        "hook fault, agent path, adapters and --cwd checked"
        % (len(CASES), len(TIMED), len(STRIP), len(BOUNDARIES["rules"]),
           len(HOOK_PAYLOADS), len(PRECEDENCE), len(BOUNDARY_FAULTS))
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
