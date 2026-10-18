#!/usr/bin/env python3
"""Synthetic end-to-end runs of the five representative tasks. SYNTHETIC: stub agents.

    python3 tests/test_scenarios.py

Each scenario is driven the way the orchestration skill drives a real task, through the
real dispatcher, gate and hook, with stub `opencode` and `codex` CLIs that apply a fixed
patch or return a fixed review. Nothing reaches a provider. What is measured is the
orchestration itself: which agents run, how many Codex reviews happen, and how many
permission prompts the commands raise under the current hook and under the hook at
a084a44. Wall-clock estimates use the audit's measured medians per agent run and are
labelled as estimates; they are not timings of real models.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "scripts"))
import test_permissions as perms  # noqa: E402
import test_review_gate as gates  # noqa: E402

DELEGATE = str(ROOT / "scripts" / "delegate")
ORCH = str(ROOT / "scripts" / "orch")

# Audit medians (frappe-orchestrator-audit-2026-10-18.md §4.3): OpenCode implement ~160 s
# wall, Codex review ~135 s, 1.9 review rounds per task; a failed FAST run 3-5 s. Sonnet
# and the orchestrator's own checks have no audit measurement; 45 s is an assumption.
EST = {"opencode": 160, "codex": 135, "sonnet": 45, "failed_fast": 5}
BASELINE_ROUNDS = 1.9

OPENCODE_STUB = """#!/usr/bin/env python3
import os, subprocess, sys
if sys.argv[1:2] == ["models"]:
    print("stub/model"); sys.exit(0)
subprocess.run(["git", "apply", os.environ["STUB_PATCH"]], cwd=os.environ["PWD"], check=True)
print('```json\\n{"status": "completed", "summary": "applied", "touched_files": []}\\n```')
"""

CODEX_STUB = """#!/usr/bin/env python3
import sys
sys.stdin.read()
print('```json\\n{"verdict": "PASS", "summary": "ok", "findings": []}\\n```')
"""

BRIEFS = {
    "FAST": "Rename the Customer Name label to Client Name in sales_note.json.",
    "SMALL": "In utils.total(), fix the sign: it should use frappe.utils.flt and add, "
             "not subtract. Do not run git add . or bench.",
    "NORMAL": "Add a Priority select (Low/High) to Sales Note; validate that High needs a "
              "note; toggle reqd in the form; expose priorities via frappe.get_all-free "
              "whitelisted API.",
}


def patch_for(change):
    """The unified diff a scenario's change produces, from a scratch copy of the app."""
    with tempfile.TemporaryDirectory() as tmp:
        path = gates.repo(tmp)
        change(path)
        subprocess.run(["git", "-C", str(path), "add", "-N", "."], check=True)
        return subprocess.run(["git", "-C", str(path), "diff"], capture_output=True,
                              text=True, check=True).stdout


def run(argv, env, stdin=""):
    proc = subprocess.run(argv, input=stdin, capture_output=True, text=True, env=env,
                          timeout=120)
    return json.loads(proc.stdout) if proc.stdout.strip() else {"error": proc.stderr[-300:]}


def heredoc(command, brief):
    return "%s <<'EOF'\n%s\nEOF" % (command, brief)


# The user's own work in progress, present before every task: one tracked file edited and
# one untracked note. A task must leave both exactly as they were.
USER_DIRTY = {"myapp/hooks.py": "app_name = 'myapp'\n# user: trying something\n",
              "myapp/NOTES.md": "user notes, not part of any task\n"}


def changed_paths(patch_text):
    return sorted({line[6:] for line in patch_text.splitlines() if line.startswith("+++ b/")})


def scenario(name, tier, change, expected, old_guard, tmp):
    work = Path(tmp)
    bin_dir = work / "bin"
    bin_dir.mkdir()
    for stub, body in (("opencode", OPENCODE_STUB), ("codex", CODEX_STUB)):
        (bin_dir / stub).write_text(body)
        (bin_dir / stub).chmod(0o755)
    patch = work / "change.patch"
    patch.write_text(patch_for(change))
    repo = gates.repo(work / "repo")
    for rel, body in USER_DIRTY.items():
        (repo / rel).write_text(body)
    config = perms.scratch_config(work)
    env = dict(os.environ, PATH="%s:%s" % (bin_dir, os.environ["PATH"]),
               FRAPPE_ORCHESTRATOR_STATE=str(work / "state"),
               FRAPPE_ORCHESTRATOR_CONFIG=str(config), CODEX_HOME=str(work / "codex"),
               STUB_PATCH=str(patch), TMPDIR=tmp)
    brief = BRIEFS.get(tier, BRIEFS["NORMAL"])
    commands, calls = ["git status --porcelain"], []

    if tier == "FAST":
        # The skill's FAST recipe: status, the Sonnet subagent (edits through Claude Code's
        # own tools, so no dispatcher call), then one call for the diff and the gate.
        subprocess.run(["git", "-C", str(repo), "apply", str(patch)], check=True)
        calls.append("sonnet")
        files = changed_paths(patch.read_text())
        command = "git diff -- %s; %s gate --cwd %s --tier FAST --files %s" % (
            " ".join(files), ORCH, repo, " ".join(files))
        commands.append(command)
        gate = run([ORCH, "gate", "--cwd", str(repo), "--tier", "FAST", "--files"] + files, env)
    else:
        command = heredoc("%s --agent opencode --mode implement --tier %s --cwd %s"
                          % (DELEGATE, tier, repo), brief)
        commands.append(command)
        result = run([sys.executable, DELEGATE, "--agent", "opencode", "--mode", "implement",
                      "--tier", tier, "--cwd", str(repo), "--model", "stub/model"],
                     env, brief)
        calls.append("opencode")
        gate = result.get("review_gate") or {}
        files = result.get("files_changed") or []
        if result.get("status") != "completed":
            return {"name": name, "error": result}
        if set(files) & set(USER_DIRTY):
            return {"name": name, "error": "the user's dirty files were reported as the "
                                           "task's: %r" % files}
        commands.append("git diff -- %s" % " ".join(files))
    review = gate.get("review")
    if review == "required":
        command = heredoc("%s --agent codex --mode review --tier %s --cwd %s --files %s"
                          % (DELEGATE, tier, repo, " ".join(files)), brief)
        commands.append(command)
        verdict = run([sys.executable, DELEGATE, "--agent", "codex", "--mode", "review",
                       "--tier", tier, "--cwd", str(repo), "--files"] + files, env, brief)
        calls.append("codex")
        review = "passed" if verdict.get("verdict") == "PASS" else str(verdict.get("verdict"))
    # No commit and no staging at the end: the task ends with the change in the tree.
    untouched = all((repo / rel).read_text() == body for rel, body in USER_DIRTY.items())
    staged = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--name-only"],
                            capture_output=True, text=True).stdout.split()
    head_moved = subprocess.run(["git", "-C", str(repo), "rev-list", "--count", "HEAD"],
                                capture_output=True, text=True).stdout.strip() != "1"

    prompts_new = sum(1 for c in commands
                      if perms.decide(perms.GUARD, env, perms.bash(c))[0] in ("ask", "deny"))
    prompts_old = None
    if old_guard:
        prompts_old = sum(
            1 for c in commands
            if perms.decide(old_guard, env, perms.bash(c.replace(DELEGATE, "/x/scripts/delegate")))[0]
            in ("ask", "deny"))
    estimate = sum(EST[c] for c in calls)
    baseline = (EST["opencode"] + BASELINE_ROUNDS * EST["codex"]
                + (2 * EST["failed_fast"] if tier == "FAST" else 0))
    return {"name": name, "tier": tier, "calls": calls, "review": review,
            "expected_review": expected, "prompts_new": prompts_new, "prompts_old": prompts_old,
            "commands": commands, "user_files_untouched": untouched, "staged": staged,
            "committed": head_moved, "invalid_files": gate.get("invalid_files"),
            "estimate_s": estimate, "baseline_estimate_s": baseline}


SKILL = ROOT / "skills" / "orchestration" / "SKILL.md"
IMPLEMENTER = ROOT / "agents" / "implementer.md"


def check_skill_contract():
    """The instructions the model follows. These pin the text; whether the model obeys it
    is what an interactive trial shows (the first one: an end-of-task commit prompt and a
    memory note took a 25 s FAST task to 134 s)."""
    failures = []
    skill, implementer = SKILL.read_text(), IMPLEMENTER.read_text()
    if re.search(r"(?i)then commit|commit,? unless the user", skill):
        failures.append("the skill still commits by default")
    for needle in ("No commit, no staging", "unless the user explicitly asks for a commit",
                   "No memory or notes", "Write memory only when the user asks"):
        if needle not in skill:
            failures.append("the skill lost %r" % needle)
    fast = skill[skill.index("**FAST → Sonnet.**"):skill.index("**SMALL / NORMAL")]
    if len(re.findall(r"^\d\. ", fast, re.M)) != 3 or "codex" in fast.lower():
        failures.append("the FAST recipe is not the three steps: %r" % fast)
    if "orch gate" not in fast or "no checks" not in fast:
        failures.append("the FAST recipe lost the gate or the no-checks brief")
    for needle in ("`git add`/`commit`", "memory or notes files", '"FAST: no checks"'):
        if needle not in implementer:
            failures.append("the implementer lost %r" % needle)
    return failures


def check_explicit_commit_still_asks():
    """No automatic commit does not mean an unguarded one: when the user does ask, the hook
    still prompts, and blanket staging is still denied."""
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, FRAPPE_ORCHESTRATOR_CONFIG=str(perms.scratch_config(Path(tmp))),
                   FRAPPE_ORCHESTRATOR_STATE=str(Path(tmp) / "state"))
        decision = perms.decide(perms.GUARD, env, perms.bash(
            "git add myapp/utils.py && git commit -m 'feat: x'"))[0]
        if decision != "ask":
            failures.append("an explicit commit no longer asks: %s" % decision)
        decision = perms.decide(perms.GUARD, env, perms.bash("git add -A"))[0]
        if decision != "deny":
            failures.append("blanket staging is no longer denied: %s" % decision)
    return failures


def main():
    failures, rows = [], []
    with tempfile.TemporaryDirectory() as tmp:
        old_guard = perms.baseline_guard(tmp)
        for index, (name, tier, change, expected, _names) in enumerate(gates.SCENARIOS):
            with tempfile.TemporaryDirectory() as case:
                row = scenario(name, tier, change, expected, old_guard, case)
            rows.append(row)
            if "error" in row:
                failures.append("%s: %r" % (name, row["error"]))
                continue
            want = "passed" if expected == "required" else "not_required"
            if row["review"] != want:
                failures.append("%s: review %s, wanted %s" % (name, row["review"], want))
            if tier == "FAST" and "codex" in row["calls"]:
                failures.append("%s: FAST ran Codex" % name)
            if row["prompts_new"] != 0:
                failures.append("%s: %d prompts, wanted 0" % (name, row["prompts_new"]))
            if any(re.search(r"(^|&&|;)\s*git\s+(add|commit)\b", c.split("\n")[0])
                   for c in row["commands"]):
                failures.append("%s: the flow staged or committed" % name)
            if row["staged"] or row["committed"]:
                failures.append("%s: staged %r / committed %s" % (name, row["staged"],
                                                                 row["committed"]))
            if not row["user_files_untouched"]:
                failures.append("%s: the user's own uncommitted files changed" % name)
            if row["invalid_files"]:
                failures.append("%s: valid files reported invalid: %r" % (name, row["invalid_files"]))
            if tier == "FAST" and (len(row["commands"]) != 2 or row["calls"] != ["sonnet"]):
                failures.append("%s: FAST took %d orchestrator commands and %s, wanted 2 and "
                                "sonnet only" % (name, len(row["commands"]), row["calls"]))
    failures += check_skill_contract()
    failures += check_explicit_commit_still_asks()

    print("SYNTHETIC scenario runs (stub agents; times are estimates from audit medians)\n")
    print("%-62s %-9s %-24s %-13s %-9s %s" % ("scenario", "tier", "agents", "review",
                                               "prompts", "est. time vs baseline"))
    for row in rows:
        if "error" in row:
            continue
        print("%-62s %-9s %-24s %-13s %-9s ~%ds vs ~%ds" % (
            row["name"][:62], row["tier"], "+".join(row["calls"]), row["review"],
            "%s (was %s)" % (row["prompts_new"], row["prompts_old"]),
            row["estimate_s"], row["baseline_estimate_s"]))
    if failures:
        print("\nFAILED (%d):" % len(failures))
        for line in failures:
            print("  - %s" % line)
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
