#!/usr/bin/env python3
"""Tests for Debate Mode: the `deliberate` mode, the Claude adapter, and scripts/debate.

    python3 tests/test_debate.py

Debate Mode fails quietly in more ways than it fails loudly. A debate that ran one side
and reported success, an "Opus" answer that came from another model, an adviser that
could write, a critique that saw nothing, a third round - every one of those produces a
plausible result that nobody would question. So each is checked here by the property it
breaks, and the runner is driven end to end against stub CLIs that record what they were
given, so independence and the two-stage bound are observed rather than assumed.

No framework and nothing to install: standard library only.
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTING = json.loads((ROOT / "config" / "model-routing.json").read_text())
SKILL = (ROOT / "skills" / "orchestration" / "SKILL.md").read_text()


def load_module(path, name):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


d = load_module(ROOT / "scripts" / "delegate", "delegate")
g = load_module(ROOT / "hooks" / "guard.py", "guard")
runner = load_module(ROOT / "scripts" / "debate", "debate")


class Refused(Exception):
    pass


def refuse(message):
    raise Refused(message)


def refused(call):
    try:
        call()
    except Refused:
        return True
    return False


POSITION = {
    "stage": "position",
    "recommended_approach": "Use a permission query condition per role.",
    "assumptions": ["roles are stable"],
    "risks": ["report views bypass the condition"],
    "alternatives": ["user permissions per record - too many rows"],
    "important_constraints": ["do not change the DocType schema"],
    "verification_strategy": ["test each role against list and report views"],
}
CRITIQUE = {
    "stage": "critique",
    "strong_points": ["small surface"],
    "concerns": ["report views"],
    "missed_risks": ["API access"],
    "recommended_changes": ["add an API test"],
    "remaining_disagreement": [],
}


# --------------------------------------------------------------------------
# 1-4: the mode matrix - existing modes unchanged, new combinations exactly as designed
# --------------------------------------------------------------------------

def check_matrix():
    problems = []
    if d.MODES.get("opencode") != ("implement",):
        problems.append("opencode modes changed: %r" % (d.MODES.get("opencode"),))
    if d.MODES.get("codex") != ("review", "test", "onboard", "deliberate"):
        problems.append("codex modes: %r" % (d.MODES.get("codex"),))
    if d.MODES.get("claude") != ("deliberate",):
        problems.append("claude may run %r; deliberate only" % (d.MODES.get("claude"),))

    accepted = [("opencode", "implement", "Kimi K2.6"), ("codex", "review", None),
                ("codex", "test", None), ("codex", "onboard", None),
                ("codex", "deliberate", None), ("claude", "deliberate", None)]
    for agent, mode, model in accepted:
        if refused(lambda: d.validate_invocation(agent, mode, model, refuse)):
            problems.append("%s + %s was refused" % (agent, mode))

    rejected = [
        ("claude", "implement", None), ("claude", "review", None), ("claude", "test", None),
        ("claude", "onboard", None), ("codex", "implement", None),
        ("opencode", "deliberate", "Kimi K2.6"), ("opencode", "review", "Kimi K2.6"),
        # The Opus pin is the routing file's, never a per-run choice.
        ("claude", "deliberate", "Claude Sonnet 5.5"),
        ("claude", "deliberate", "Claude Opus 5.5"),
        ("codex", "deliberate", "Kimi K2.6"),
    ]
    for agent, mode, model in rejected:
        if not refused(lambda: d.validate_invocation(agent, mode, model, refuse)):
            problems.append("%s + %s (model %r) was accepted" % (agent, mode, model))

    # Stage arguments belong to deliberate, and each stage takes its own.
    stage_cases = [
        ("review", "position", None, None, None, True),
        ("review", None, "user-request", None, None, True),
        ("onboard", None, None, "a.json", None, True),
        ("review", None, None, None, None, False),
        ("deliberate", None, "user-request", None, None, True),
        ("deliberate", "position", None, None, None, True),
        ("deliberate", "position", "user-request", "a.json", None, True),
        ("deliberate", "position", "user-request", None, "b.json", True),
        ("deliberate", "critique", "user-request", "a.json", None, True),
        ("deliberate", "critique", "user-request", None, "b.json", True),
        ("deliberate", "position", "user-request", None, None, False),
        ("deliberate", "critique", "user-request", "a.json", "b.json", False),
    ]
    for mode, stage, trigger, own, other, want_refused in stage_cases:
        got = refused(lambda: d.validate_stage_arguments(mode, stage, trigger, own, other,
                                                          refuse))
        if got != want_refused:
            problems.append("stage args %r: refused=%s, wanted %s"
                            % ((mode, stage, trigger, own, other), got, want_refused))
    return problems


# --------------------------------------------------------------------------
# 5: read-only advisers
# --------------------------------------------------------------------------

def check_read_only():
    problems = []
    argv, env, stdin = d.adapt_claude(brief="b", mode="deliberate", cwd="/probe",
                                      model_id="claude-opus-5-5", effort="high")

    def value(flag):
        return argv[argv.index(flag) + 1] if flag in argv else None

    if argv[:2] != ["claude", "-p"]:
        problems.append("claude is not run non-interactively: %r" % argv[:2])
    if value("--model") != "claude-opus-5-5":
        problems.append("claude --model is %r" % value("--model"))
    if set((value("--tools") or "").split(",")) != {"Read", "Grep", "Glob"}:
        problems.append("claude tool set is %r, not Read/Grep/Glob" % value("--tools"))
    if value("--allowedTools") != value("--tools"):
        problems.append("pre-approved tools differ from the tool set")
    for writer in ("Bash", "Edit", "Write", "NotebookEdit", "Agent", "Task"):
        if writer in (value("--tools") or "").split(","):
            problems.append("claude adviser has %s" % writer)
    if value("--permission-mode") != "dontAsk":
        problems.append("permission mode %r: anything unlisted must be denied"
                        % value("--permission-mode"))
    if value("--permission-prompts") != "none":
        problems.append("permission prompts are not off")
    for flag in ("--strict-mcp-config", "--restricted", "--disable-slash-commands",
                 "--no-session-persistence"):
        if flag not in argv:
            problems.append("claude argv lacks %s" % flag)
    for flag in ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions",
                 "--add-dir", "--mcp-config", "--fallback-model"):
        if flag in argv:
            problems.append("claude argv carries %s" % flag)
    if value("--output-format") != "json":
        problems.append("claude output is not the JSON envelope model verification reads")
    if env.get("PWD") != "/probe" or stdin != "b":
        problems.append("claude: PWD or stdin brief wrong")
    for mode in ("implement", "review", "test", "onboard"):
        try:
            d.adapt_claude(brief="b", mode=mode, cwd="/probe", model_id="x")
            problems.append("adapt_claude built a %s command" % mode)
        except ValueError:
            pass

    argv, _env, _stdin = d.adapt_codex(brief="b", mode="deliberate", cwd="/probe")
    if argv[argv.index("--sandbox") + 1] != "read-only":
        problems.append("codex deliberate is not in the read-only sandbox")

    # Running the adviser outside the dispatcher would skip all of the above.
    for command in ("claude -p 'decide the schema'", "claude --model opus --print x",
                    "/usr/bin/claude --model claude-opus-5-5 -p x"):
        decision = g.check(command)
        if not decision or decision[0] != "deny":
            problems.append("hook did not deny %r: %r" % (command, decision))
    for command in ("claude --version", "claude plugin list", "claude --help"):
        if g.check(command) is not None:
            problems.append("hook interferes with %r" % command)
    return problems


# --------------------------------------------------------------------------
# 6-8: the contract - no verdict, parsed correctly, malformed never valid
# --------------------------------------------------------------------------

def check_contract():
    problems = []
    if "deliberate" in d.VERDICT_MODES:
        problems.append("deliberate is a verdict mode")
    for text in (d.CONTRACTS["deliberate"], *d.DELIBERATION_STAGES.values()):
        for word in ('"verdict"', "PASS", "FAIL", "BLOCKED", '"winner"'):
            if word in text:
                problems.append("a deliberate contract mentions %s" % word)
    if set(d.DELIBERATION_STAGES) != {"position", "critique"}:
        problems.append("stages are %r; there must be exactly two"
                        % sorted(d.DELIBERATION_STAGES))

    report = dict(POSITION, verdict="PASS", winner="claude", final_decision="mine")
    removed = d.strip_off_contract(report, "deliberate")
    if sorted(removed) != ["final_decision", "verdict", "winner"]:
        problems.append("off-contract keys removed: %r" % removed)
    if d.validate_deliberation(report, "position"):
        problems.append("stripping broke the report: %r"
                        % d.validate_deliberation(report, "position"))
    if d.derive_verdict is None:
        problems.append("derive_verdict disappeared")

    def fenced(obj):
        return "Banner\n```json\n%s\n```\ntokens used\n" % json.dumps(obj)

    cases = [
        ("position", fenced(POSITION), "present", []),
        ("critique", fenced(CRITIQUE), "present", []),
        # A critique quoting the position it critiques is still the critique.
        ("critique", fenced(dict(CRITIQUE, quoted=POSITION)), "present", []),
        ("position", "no json here", "missing", None),
        ("position", '{"status": "completed", "summary": "s"}', "missing", None),
        ("position", '```json\n{"stage": "opinion"}\n```', "invalid", None),
    ]
    for stage, text, want_state, want_errors in cases:
        state, parsed = d.extract_report(text, "deliberate")
        if state != want_state:
            problems.append("%s %r: state %s, wanted %s" % (stage, text[:40], state, want_state))
            continue
        if want_errors is not None and d.validate_deliberation(parsed, stage) != want_errors:
            problems.append("%s: errors %r" % (stage, d.validate_deliberation(parsed, stage)))
        if parsed is not None and parsed.get("stage") != stage:
            problems.append("%s: parsed the wrong object %r" % (stage, parsed))

    malformed = [
        ("bare discriminator", "position", {"stage": "position"}),
        ("wrong stage", "position", CRITIQUE),
        ("critique answered with a position", "critique", POSITION),
        ("empty approach", "position", dict(POSITION, recommended_approach="  ")),
        ("approach not a string", "position", dict(POSITION, recommended_approach=["x"])),
        ("risks not a list", "position", dict(POSITION, risks="none")),
        ("missing verification", "position",
         {k: v for k, v in POSITION.items() if k != "verification_strategy"}),
        ("critique missing concerns", "critique",
         {k: v for k, v in CRITIQUE.items() if k != "concerns"}),
        ("not an object", "position", ["stage", "position"]),
    ]
    for name, stage, report in malformed:
        if not d.validate_deliberation(report, stage):
            problems.append("malformed report accepted: %s" % name)
    return problems


# --------------------------------------------------------------------------
# 9-11: triggers
# --------------------------------------------------------------------------

def check_triggers():
    problems = []
    tiers = ROUTING["tiers"]
    config = d.load_deliberation(ROUTING, tiers, refuse)
    reasons = ("architectural-ambiguity", "competing-approaches", "high-risk-decision")
    if config["trigger_tiers"] != ["DIFFICULT"]:
        problems.append("automatic tiers are %r" % config["trigger_tiers"])

    for tier in ("FAST", "SMALL", "NORMAL"):
        for reason in reasons:
            if not refused(lambda: d.check_trigger(config, tier, reason, refuse)):
                problems.append("%s auto-triggered Debate Mode (%s)" % (tier, reason))
    for reason in reasons:
        try:
            if d.check_trigger(config, "DIFFICULT", reason, refuse) != "automatic":
                problems.append("DIFFICULT + %s is not automatic" % reason)
        except Refused as exc:
            problems.append("DIFFICULT + %s refused: %s" % (reason, exc))
    # DIFFICULT alone is not a reason.
    for empty in ("", "difficult", "DIFFICULT", "large-task", "hard-debugging"):
        if not refused(lambda: d.check_trigger(config, "DIFFICULT", empty, refuse)):
            problems.append("DIFFICULT with trigger %r was accepted" % empty)
    if not refused(lambda: d.validate_stage_arguments("deliberate", "position", None, None,
                                                       None, refuse)):
        problems.append("a deliberate run without --trigger was accepted")

    for tier in tiers:
        try:
            if d.check_trigger(config, tier, "user-request", refuse) != "user":
                problems.append("user request on %s not recorded as the user's" % tier)
        except Refused as exc:
            problems.append("user request on %s refused: %s" % (tier, exc))

    disabled = json.loads(json.dumps(ROUTING))
    disabled["deliberation"]["enabled"] = False
    if not refused(lambda: d.load_deliberation(disabled, tiers, refuse)):
        problems.append("Debate Mode ran while disabled")
    for label, change in (
        ("no block", lambda r: r.pop("deliberation")),
        ("bad timeout", lambda r: r["deliberation"].update(timeout_seconds=0)),
        ("unknown tier", lambda r: r["deliberation"].update(trigger_tiers=["HARD"])),
        ("effort codex rejects", lambda r: r["deliberation"].update(effort="max")),
        ("user trigger is an auto trigger",
         lambda r: r["deliberation"].update(user_trigger="competing-approaches")),
    ):
        broken = json.loads(json.dumps(ROUTING))
        change(broken)
        if not refused(lambda: d.load_deliberation(broken, tiers, refuse)):
            problems.append("a routing file with %s was accepted" % label)

    # The Opus pin comes from the routing file, and is refused without an exact id.
    name, model_id = d.resolve_deliberation_model(ROUTING, config, refuse)
    if (name, model_id) != ("Claude Opus 5.5", "claude-opus-5-5"):
        problems.append("deliberation model resolved to %r" % ((name, model_id),))
    broken = json.loads(json.dumps(ROUTING))
    del broken["models"]["Claude Opus 5.5"]["id"]
    if not refused(lambda: d.resolve_deliberation_model(broken, config, refuse)):
        problems.append("an Opus entry without an id was accepted")
    # Opus having an id does not make it delegable for implementation.
    if not refused(lambda: d.resolve_model(ROUTING, "Claude Opus 5.5", refuse)):
        problems.append("Claude Opus became an OpenCode implementation model")
    return problems


# --------------------------------------------------------------------------
# The Opus side is Opus
# --------------------------------------------------------------------------

def envelope(usage, result="ok", is_error=False):
    return {"type": "result", "is_error": is_error, "result": result,
            "modelUsage": {name: {"outputTokens": tokens} for name, tokens in usage.items()}}


def check_model_verification():
    problems = []
    aux = ROUTING["deliberation"]["claude_auxiliary_model_prefixes"]
    cases = [
        ("opus alone", envelope({"claude-opus-5-5": 400}), True),
        ("opus with housekeeping", envelope({"claude-opus-5-5": 400,
                                             "claude-haiku-4-5-20251001": 9}), True),
        ("a different model answered", envelope({"claude-sonnet-5-5": 400}), False),
        ("fallback mid-run", envelope({"claude-opus-5-5": 100,
                                       "claude-sonnet-5-5": 300}), False),
        ("opus listed without output", envelope({"claude-opus-5-5": 0,
                                                 "claude-haiku-4-5": 50}), False),
        ("no usage at all", envelope({}), False),
        ("no envelope", None, False),
    ]
    for name, env, want in cases:
        verified, _served, note = d.verify_claude_model(env, "claude-opus-5-5", aux)
        if verified != want:
            problems.append("%s: verified=%s" % (name, verified))
        if not verified and not note:
            problems.append("%s: unverified with no reason" % name)

    raw = json.dumps(envelope({"claude-opus-5-5": 1}, result="text {\"stage\": 1}"))
    text, env = d.unwrap_claude_output("warning on stdout\n" + raw + "\n")
    if text != 'text {"stage": 1}' or env is None:
        problems.append("envelope after a stray line was not unwrapped: %r" % text)
    for junk in ("", "not json", '{"type": "assistant"}'):
        if d.unwrap_claude_output(junk)[1] is not None:
            problems.append("%r unwrapped as a result envelope" % junk)
    return problems


# --------------------------------------------------------------------------
# 12-14: the runner, end to end, against stub CLIs
# --------------------------------------------------------------------------

STUB = r"""#!/usr/bin/env python3
import json, os, sys, time
agent = os.path.basename(sys.argv[0])
brief = sys.stdin.read()
stage = "critique" if "(deliberate: critique)" in brief else "position"
record = os.environ["RECORD_DIR"]
n = len(os.listdir(record))
with open(os.path.join(record, "%03d-%s-%s.json" % (n, agent, stage)), "w") as f:
    json.dump({"argv": sys.argv[1:], "brief": brief, "cwd": os.getcwd()}, f)
behaviour = os.environ.get("STUB_%s" % agent.upper(), "ok")
sentinel = "%s-APPROACH" % agent.upper()
if stage == "position":
    report = {"stage": "position", "recommended_approach": sentinel,
              "assumptions": [], "risks": ["r"], "alternatives": [],
              "important_constraints": [], "verification_strategy": ["v"]}
else:
    report = {"stage": "critique", "strong_points": [], "concerns": ["c"],
              "missed_risks": [], "recommended_changes": [],
              "remaining_disagreement": [], "winner": agent}
if behaviour == "malformed-" + stage:
    report = {"stage": stage}
if behaviour == "exit-" + stage:
    sys.exit(3)
text = "Thinking done.\n```json\n%s\n```\n" % json.dumps(report)
if agent == "claude":
    model = os.environ.get("STUB_CLAUDE_MODEL", "claude-opus-5-5")
    print(json.dumps({"type": "result", "is_error": False, "result": text,
                      "modelUsage": {model: {"outputTokens": 321},
                                     "claude-haiku-4-5-20251001": {"outputTokens": 7}}}))
else:
    print("OpenAI Codex\n--------\n" + text + "tokens used\n10\n")
"""


def make_env(tmp):
    bin_dir, repo, work = tmp / "bin", tmp / "repo", tmp / "work"
    for path in (bin_dir, repo / ".git", work):
        path.mkdir(parents=True, exist_ok=True)
    for agent in ("claude", "codex"):
        stub = bin_dir / agent
        stub.write_text(STUB)
        stub.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = "%s:%s" % (bin_dir, env.get("PATH", "/usr/bin:/bin"))
    env["TMPDIR"] = str(work)
    return env, repo


def run_debate(tmp, tier="DIFFICULT", trigger="competing-approaches", **behaviour):
    record = tmp / ("record-%d" % len(list(tmp.glob("record-*"))))
    record.mkdir()
    env, repo = make_env(tmp)
    env["RECORD_DIR"] = str(record)
    for key, value in behaviour.items():
        env["STUB_%s" % key.upper()] = value
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "debate"), "--tier", tier,
         "--trigger", trigger, "--cwd", str(repo)],
        input="Decide how Sales Invoice approval permissions should be modelled.",
        capture_output=True, text=True, env=env, timeout=120,
    )
    calls = [json.loads(p.read_text()) | {"file": p.name} for p in sorted(record.iterdir())]
    result = json.loads(proc.stdout) if proc.returncode == 0 and proc.stdout.strip() else None
    return proc, result, calls


def check_runner(tmp):
    problems = []
    proc, result, calls = run_debate(tmp)
    if result is None:
        return ["the debate did not run: %s" % proc.stderr[-400:]]
    if result["status"] != "complete":
        problems.append("debate status %r, failures %r" % (result["status"], result["failures"]))
    # Exactly four runs: two positions, then two critiques. No third round.
    stages = sorted((c["file"].split("-", 1)[1]) for c in calls)
    if stages != ["claude-critique.json", "claude-position.json",
                  "codex-critique.json", "codex-position.json"]:
        problems.append("runs were %r" % stages)
    if result["stages_run"] != ["position", "critique"]:
        problems.append("stages run: %r" % result["stages_run"])
    positions = [c for c in calls if c["file"].endswith("position.json")]
    critiques = [c for c in calls if c["file"].endswith("critique.json")]
    if positions and critiques and max(int(c["file"][:3]) for c in positions) > min(
            int(c["file"][:3]) for c in critiques):
        problems.append("a critique started before both positions were in")

    # Independence: the same brief, and no position sees another answer.
    briefs = {c["brief"].split("## Requested output")[0] for c in positions}
    if len(briefs) != 1:
        problems.append("the two advisers were given different position briefs")
    for call in positions:
        if "APPROACH" in call["brief"] or "other adviser's first-stage" in call["brief"]:
            problems.append("%s's position brief carried another answer" % call["file"])
    # Each critique sees its own position and the other's, under the right headings.
    for call in critiques:
        agent = "claude" if "claude" in call["file"] else "codex"
        other = "codex" if agent == "claude" else "claude"
        own_at = call["brief"].find("## Your first-stage position")
        other_at = call["brief"].find("## The other adviser's first-stage position")
        if own_at < 0 or other_at < 0:
            problems.append("%s critique brief lacks a position section" % agent)
            continue
        if "%s-APPROACH" % agent.upper() not in call["brief"][own_at:other_at]:
            problems.append("%s critique: own position missing" % agent)
        if "%s-APPROACH" % other.upper() not in call["brief"][other_at:]:
            problems.append("%s critique: the other adviser's position missing" % agent)

    # The Opus side was Opus, and that is on the record.
    claude = result["participants"].get("claude") or {}
    if (claude.get("model"), claude.get("model_id"), claude.get("model_verified")) != (
            "Claude Opus 5.5", "claude-opus-5-5", True):
        problems.append("claude participant recorded as %r" % claude)
    if (result["participants"].get("codex") or {}).get("model_verified") is not None:
        problems.append("codex claims a model verification it never had")
    for call in calls:
        if "claude" in call["file"]:
            argv = call["argv"]
            if argv[argv.index("--model") + 1] != "claude-opus-5-5":
                problems.append("claude was run with --model %r" % argv[argv.index("--model") + 1])
        if Path(call["cwd"]).resolve() != (tmp / "repo").resolve():
            problems.append("%s ran in %s" % (call["file"], call["cwd"]))

    # Audit trail, outside the repository; no verdict anywhere; the volunteered winner
    # removed.
    directory = Path(result["directory"])
    for name in ("brief.md", "claude-position.json", "codex-position.json",
                 "claude-critique.json", "codex-critique.json", "debate.json"):
        if not (directory / name).is_file():
            problems.append("debate directory lacks %s" % name)
    if str(directory).startswith(str((tmp / "repo").resolve())):
        problems.append("debate artifacts were written into the repository")
    if any((tmp / "repo").iterdir()) and set(p.name for p in (tmp / "repo").iterdir()) != {".git"}:
        problems.append("the repository working tree changed")
    for name in ("claude-critique.json", "codex-critique.json"):
        data = json.loads((directory / name).read_text())
        if "verdict" in data or "verdict" in (data.get("agent_report") or {}):
            problems.append("%s carries a verdict" % name)
        if "winner" in (data.get("agent_report") or {}):
            problems.append("%s kept a self-declared winner" % name)
        if data.get("off_contract_keys") != ["winner"]:
            problems.append("%s off_contract_keys %r" % (name, data.get("off_contract_keys")))
    if result["synthesis"] != str(directory / "synthesis.md"):
        problems.append("no synthesis path for the orchestrator")
    if (directory / "synthesis.md").exists():
        problems.append("the runner wrote a synthesis; the decision is the orchestrator's")
    return problems


FAILURES = [
    # (name, behaviour, stage that failed, stages that ran, failing adviser)
    ("opus answered by another model", {"claude_model": "claude-sonnet-5-5"},
     "position", ["position"], "claude"),
    ("codex position malformed", {"codex": "malformed-position"}, "position", ["position"],
     "codex"),
    ("claude position crashed", {"claude": "exit-position"}, "position", ["position"], "claude"),
    ("codex critique malformed", {"codex": "malformed-critique"}, "critique",
     ["position", "critique"], "codex"),
    ("claude critique crashed", {"claude": "exit-critique"}, "critique",
     ["position", "critique"], "claude"),
]


def check_failures(tmp):
    problems = []
    for name, behaviour, stage, ran, agent in FAILURES:
        proc, result, calls = run_debate(tmp, **behaviour)
        if result is None:
            problems.append("%s: no result (%s)" % (name, proc.stderr[-200:]))
            continue
        if result["status"] != "incomplete":
            problems.append("%s: status %r - a failed side became a debate"
                            % (name, result["status"]))
        if result["stages_run"] != ran:
            problems.append("%s: stages run %r, wanted %r" % (name, result["stages_run"], ran))
        if result["positions"] or result["critiques"]:
            problems.append("%s: an incomplete debate still offers reports to decide on" % name)
        failed = {(f["agent"], f["stage"]) for f in result["failures"]}
        if (agent, stage) not in failed:
            problems.append("%s: failures %r do not name %s %s" % (name, failed, agent, stage))
        if not all(f["reasons"] for f in result["failures"]):
            problems.append("%s: a failure without a reason" % name)
        if stage == "position" and any(c["file"].endswith("critique.json") for c in calls):
            problems.append("%s: a critique ran without both positions" % name)
        if len(calls) > 4:
            problems.append("%s: %d runs - something was retried" % (name, len(calls)))
    return problems


def check_refusals(tmp):
    """Refused before anything runs: wrong trigger, wrong tier, disabled."""
    problems = []
    for tier, trigger in (("NORMAL", "competing-approaches"), ("FAST", "high-risk-decision"),
                          ("DIFFICULT", "difficult"), ("SMALL", "architectural-ambiguity")):
        proc, result, calls = run_debate(tmp, tier=tier, trigger=trigger)
        if proc.returncode != 2 or calls:
            problems.append("%s/%s: exit %s, %d runs" % (tier, trigger, proc.returncode, len(calls)))
    proc, result, calls = run_debate(tmp, tier="NORMAL", trigger="user-request")
    if result is None or result["status"] != "complete":
        problems.append("an explicit user request on NORMAL did not run: %s" % proc.stderr[-200:])
    return problems


def check_position_inputs(tmp):
    """load_position is the bound: only usable positions from the same brief, crosswise."""
    problems = []
    cwd = "/repo"
    digest = d.brief_digest("the question")
    base = {"mode": "deliberate", "stage": "position", "usable": True, "cwd": cwd,
            "brief_sha256": digest, "agent_report": POSITION}

    def write(name, **changes):
        path = tmp / name
        path.write_text(json.dumps(dict(base, **changes)))
        return str(path)

    good_other = write("other.json", agent="codex")
    good_own = write("own.json", agent="claude")
    try:
        if d.load_position(good_other, agent="claude", own=False, cwd=cwd, digest=digest,
                           fail=refuse) != POSITION:
            problems.append("a good counterpart was not returned intact")
        d.load_position(good_own, agent="claude", own=True, cwd=cwd, digest=digest, fail=refuse)
    except Refused as exc:
        problems.append("good positions refused: %s" % exc)

    bad = [
        ("a critique as input (a third round)", write("c.json", agent="codex", stage="critique"),
         False),
        ("an unusable position", write("u.json", agent="codex", usable=False), False),
        ("own position as the counterpart", write("s.json", agent="claude"), False),
        ("the other's position as own", write("o.json", agent="codex"), True),
        ("a different brief", write("b.json", agent="codex", brief_sha256="0" * 64), False),
        ("a different repository", write("r.json", agent="codex", cwd="/elsewhere"), False),
        ("a review result", write("v.json", agent="codex", mode="review"), False),
    ]
    for name, path, own in bad:
        if not refused(lambda: d.load_position(path, agent="claude", own=own, cwd=cwd,
                                               digest=digest, fail=refuse)):
            problems.append("critique input accepted: %s" % name)

    # A deliberation result is not a review to re-check.
    path = write("deliberate-as-review.json", agent="codex")
    if not refused(lambda: d.load_previous_findings(path, refuse)):
        problems.append("--previous-findings accepted a deliberate result")
    return problems


# --------------------------------------------------------------------------
# 13: the later review is untouched, and the skill says so
# --------------------------------------------------------------------------

def check_workflow_text():
    problems = []
    flow = SKILL[SKILL.index("## Workflow"):SKILL.index("## Task classification")]
    order = ["Debate Mode", "Implementation", "Codex REVIEW"]
    positions = [flow.find(step) for step in order]
    if -1 in positions or positions != sorted(positions):
        problems.append("the workflow does not place Debate Mode before implementation "
                        "and the Codex review after it")
    section = SKILL[SKILL.index("## Debate Mode"):SKILL.index("## Disagreement with a review")]
    for phrase in ("fresh `review` run", "never counts as one", "Difficulty alone is never a trigger",
                   "Debate: enabled | reason:", "Debate: complete | decision:",
                   "Debate: incomplete", "Do not fabricate the missing side"):
        if phrase not in section:
            problems.append("Debate Mode section lacks %r" % phrase)
    fast = SKILL[SKILL.index("## Fast path"):SKILL.index("## Delegation")]
    if "agent debate" not in fast:
        problems.append("the fast path no longer excludes debate")
    if "Claude Opus 5.5" in section:
        problems.append("the skill hardcodes the Opus model name instead of reading routing")
    # The review contract and its verdict semantics are what they were.
    if d.VERDICT_MODES != frozenset({"review", "test"}):
        problems.append("verdict modes changed: %r" % sorted(d.VERDICT_MODES))
    return problems


def main():
    failures = []
    failures += ["matrix: " + p for p in check_matrix()]
    failures += ["read-only: " + p for p in check_read_only()]
    failures += ["contract: " + p for p in check_contract()]
    failures += ["triggers: " + p for p in check_triggers()]
    failures += ["model: " + p for p in check_model_verification()]
    failures += ["workflow: " + p for p in check_workflow_text()]
    with tempfile.TemporaryDirectory() as tmp:
        failures += ["inputs: " + p for p in check_position_inputs(Path(tmp))]
    with tempfile.TemporaryDirectory() as tmp:
        failures += ["runner: " + p for p in check_runner(Path(tmp))]
    with tempfile.TemporaryDirectory() as tmp:
        failures += ["failure: " + p for p in check_failures(Path(tmp))]
    with tempfile.TemporaryDirectory() as tmp:
        failures += ["refusal: " + p for p in check_refusals(Path(tmp))]

    print("matrix, read-only, contract, triggers, model verification, critique inputs, "
          "runner end to end, %d failure paths, refusals and workflow text checked"
          % len(FAILURES))
    if failures:
        print("\nFAILED (%d):" % len(failures))
        for line in failures:
            print("  - %s" % line)
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
