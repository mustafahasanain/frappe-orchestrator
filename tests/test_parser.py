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

import fnmatch
import importlib.machinery
import importlib.util
import json
import os
import re
import shlex
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
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend(
            "agent path: " + line for line in check_agent_path_record(Path(tmp))
        )
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend("--cwd: " + line for line in check_cwd_validation(Path(tmp)))

    print(
        "%d cases, %d timed, %d strip, %d boundary rules, mode matrix, invocation, "
        "agent path, adapters and --cwd checked"
        % (len(CASES), len(TIMED), len(STRIP), len(BOUNDARIES["rules"]))
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
