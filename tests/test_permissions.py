#!/usr/bin/env python3
"""Permission behaviour: fewer needless prompts, the same or stronger protection.

    python3 tests/test_permissions.py

1. A corpus of routine commands, shaped after the audit's largest needless-prompt buckets
   (text inside briefs, grep patterns and heredocs; read-only SQL; multi-site rebuilds on
   development sites; the plugin's own scripts), is run through the hook as shipped at
   a084a44 and through the current hook. The current hook must prompt on none of them.
2. A corpus of commands that must stay protected - including wrapped forms the old hook
   missed - must every one be asked or denied.
3. The edit guard: Edit/Write is denied while a delegated writer is alive in the repo,
   asks for the plugin's own config, and is silent otherwise.
4. The delegated OpenCode policy, evaluated with OpenCode's own matcher semantics
   (docs/history/OPENCODE_MATCHER_REPORT.md §2.1-2.2), denies wrapped forms of every
   delegated deny rule.
5. Hook latency.

Each hook runs as a process with a payload on stdin, as Claude Code runs it, with all
state and config in a scratch directory.
"""

import json
import os
import re
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "hooks" / "guard.py"
sys.path.insert(0, str(ROOT / "scripts"))
import orchlib  # noqa: E402

BASELINE = "a084a44"
DELEGATE = str(ROOT / "scripts" / "delegate")
ORCH = str(ROOT / "scripts" / "orch")

# Routine work that should not raise a prompt. The development sites are listed in the
# scratch sites.json, which is the one-time step the user takes for their dev sites.
ROUTINE = [
    # briefs: trigger words in text handed to the dispatcher (BUG-05)
    DELEGATE + " --agent opencode --mode implement --tier SMALL --cwd /r <<'EOF'\n"
    "Use frappe.get_all to list customers.\nDo not run git add . or git push.\n"
    "Never run bench --site prod.example.com migrate.\nEOF",
    DELEGATE + " --agent codex --mode review --tier NORMAL --cwd /r --files a.py <<'EOF'\n"
    "The fix replaces frappe.db.sql with frappe.get_all; check git reset is not needed.\n"
    "EOF",
    # grep patterns and file-writing heredocs
    "grep -rn 'frappe.get_all' apps/myapp",
    "grep -rnE 'git push|git commit' docs/",
    "rg -n 'frappe.db.sql' myapp/",
    "cat > /tmp/notes.md <<'EOF'\nSteps: git push origin main; rm -rf build\nEOF",
    "echo 'remember frappe.db.commit() here'",
    "git log --oneline --grep 'git push'",
    # read-only SQL and multi-site work on listed development sites
    "bench --site dev.local mariadb -e \"SELECT name, enabled FROM tabUser LIMIT 5\"",
    "bench --site dev.local mariadb -e 'SHOW TABLES'",
    "bench --site a.local clear-cache && bench --site b.local clear-cache",
    "cd ~/frappe-bench && bench --site dev.local migrate 2>&1 | tail -30",
    "bench build --app myapp",
    "bench --site dev.local run-tests --app myapp --module myapp.tests.test_x",
    # the plugin's own scripts
    ORCH + " status --cwd /r",
    ORCH + " gate --cwd /r --tier SMALL --files a.py",
    ORCH + " models status",
]

# Must be asked or denied. (command, acceptable decisions)
PROTECTED = [
    ("git push origin main", {"ask"}),
    ("env GIT_SSH_COMMAND=x git push", {"ask"}),
    ("sudo -u frappe /usr/bin/git push", {"ask"}),
    ("timeout 60 git push", {"ask"}),
    ("bash -c 'git push --force'", {"ask"}),
    ("echo $(git push)", {"ask"}),
    ("git commit -m 'feat: x'", {"ask"}),
    ("git add -A", {"deny"}), ("git add .", {"deny"}), ("git add -u", {"deny"}),
    ("git add ./", {"deny"}),
    ("git reset --hard HEAD~1", {"ask"}), ("git checkout -- .", {"ask"}),
    ("git clean -fd", {"ask"}), ("git stash drop", {"ask"}),
    ("rm -rf node_modules", {"ask"}), ("find . -name '*.py' -delete", {"ask"}),
    ("find . -type d -exec rm -rf {} +", {"ask"}),
    ("bench --site prod.example.com migrate", {"ask"}),
    ("bench --site unlisted.local console", {"ask"}),
    ("bench --site client.local list-apps", {"ask"}),
    ("bench --site dev.local reinstall --yes", {"ask"}),
    ("bench --site dev.local restore backup.sql.gz", {"ask"}),
    ("bench drop-site dev.local", {"ask"}),
    ("bench --site dev.local mariadb -e \"DELETE FROM tabUser\"", {"ask"}),
    ("bench --site dev.local mariadb -e \"SELECT 1; DROP TABLE tabUser\"", {"ask"}),
    ("bench --site dev.local mariadb", {"ask"}),
    ("bench --site all migrate", {"ask"}), ("bench migrate", {"ask"}),
    ("bench update", {"ask"}), ("bench new-site test.local", {"ask"}),
    ("ssh prod-server 'bench --site erp.example.com backup'", {"ask"}),
    ("scp dump.sql prod:/tmp/", {"ask"}),
    ("mysql -u root -e 'select 1'", {"ask"}),
    ("python3 -c \"import frappe; frappe.init(site='prod.example.com'); frappe.connect()\"",
     {"ask"}),
    ("cat <<'EOF' | bash\ngit push\nEOF", {"ask"}),
    ("opencode run 'do it'", {"deny"}), ("codex exec 'review'", {"deny"}),
    ("claude -p 'decide'", {"deny"}),
    (ORCH + " sites allow client.local", {"ask"}),
    (ORCH + " models promote opencode-go/glm-5.3", {"ask"}),
    (ORCH + " models verify opencode-go/kimi-k3", {"ask"}),
]

# Found by an adversarial review of the new hook: each was wrongly allowed, or wrongly
# left without a decision. (command, decisions that are acceptable)
REVIEW_FINDINGS = [
    # an allow must never carry a write it did not check
    ("bench build && echo '{\"development\": [\"client.local\"]}' > "
     "~/.config/frappe-orchestrator/sites.json", {None, "ask"}),
    ("bench build && echo key >> ~/.ssh/authorized_keys", {None, "ask"}),
    ("bench --site dev.local migrate > ~/.bashrc", {None, "ask"}),
    ("python3 -c \"import frappe; frappe.connect('dev.local'); import shutil; "
     "shutil.rmtree('/home')\"", {None, "ask"}),
    ("bench --site dev.local console <<'EOF'\nimport os\nos.system('rm -rf ~')\nEOF",
     {None, "ask"}),
    ("bench --site dev.local console <<'EOF'\nfrappe.db.sql('delete from tabUser')\nEOF",
     {None, "ask"}),
    ("bench --site dev.local mariadb -e \"SELECT 1; /*! DELETE FROM tabUser */\"", {"ask"}),
    ("bench --site dev.local mariadb -e \"SELECT 1 --1; DELETE FROM tabUser\"", {"ask"}),
    ("bench --site dev.local mariadb -e \"select 1\" -e \"drop table tabUser\"", {"ask"}),
    ("bench --site dev.local mariadb --execute=\"select 1\" -e \"delete from x\"", {"ask"}),
    ("bench --site dev.local mariadb -e \"select 1 \\! rm -rf ~\"", {"ask"}),
    (ORCH + " claude-default --app", {"ask"}),
    # lexing gaps: a command hidden from the rules
    ("echo \\ #; git push", {"ask"}),
    ("((x=1<<y))\ngit push", {"ask"}),
    ("cat <<EOF > notes.txt\n$(git push origin main)\nEOF", {"ask"}),
    ("echo $(echo \")\"; git push)", {"ask"}),
    ("case a in a) git push;; esac", {"ask"}),
    ("bash -c -- 'git push'", {"ask"}),
    ("env -S 'git push'", {"ask"}),
    ("$'git' push", {"ask"}),
    ("git \\\npush", {"ask"}),
]

# Routine inspection that must stay prompt-free after those fixes.
STILL_ROUTINE = [
    "bench --site dev.local console <<'EOF'\nprint(frappe.get_all('User', limit=5))\nEOF",
    "bench --site dev.local mariadb -e \"SELECT name FROM tabUser -- trailing comment\"",
    "bench --site dev.local migrate 2>&1 > /dev/null",
    "cat <<'EOF' > /tmp/x.md\n$(not run, quoted delimiter)\nEOF",
]

# Commands the old hook let through, which are protected now.
NEWLY_PROTECTED = [
    "env GIT_SSH_COMMAND=x git push", "sudo -u frappe /usr/bin/git push",
    "timeout 60 git push", "bash -c 'git push --force'", "echo $(git push)",
    "git add -u", "git add ./", "find . -type d -exec rm -rf {} +",
    "bench --site unlisted.local console", "bench update", "bench new-site test.local",
    "ssh prod-server 'bench --site erp.example.com backup'",
    "bench --site dev.local mariadb -e \"SELECT 1; DROP TABLE tabUser\"",
]


def scratch_config(tmp):
    config = Path(tmp) / "config"
    config.mkdir()
    (config / "sites.json").write_text(json.dumps({
        "development": ["dev.local", "a.local", "b.local"],
        "protected": ["client.local"],
    }))
    return config


def baseline_guard(tmp):
    """The hook and its rules as shipped at the baseline commit, or None."""
    base = Path(tmp) / "baseline"
    files = {"hooks/guard.py": base / "hooks" / "guard.py",
             "config/command-boundaries.json": base / "config" / "command-boundaries.json"}
    for source, target in files.items():
        proc = subprocess.run(["git", "-C", str(ROOT), "show", "%s:%s" % (BASELINE, source)],
                              capture_output=True)
        if proc.returncode != 0:
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(proc.stdout)
    return files["hooks/guard.py"]


def decide(guard, env, payload):
    started = time.monotonic()
    proc = subprocess.run([sys.executable, str(guard)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=30)
    elapsed = time.monotonic() - started
    if proc.returncode not in (0, 2):
        return "error:%d" % proc.returncode, elapsed, proc.stderr
    if not proc.stdout.strip():
        return None, elapsed, ""
    out = json.loads(proc.stdout)["hookSpecificOutput"]
    return out["permissionDecision"], elapsed, out.get("permissionDecisionReason", "")


def bash(command):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": command}}


# OpenCode's wildcard matcher and evaluator, ported from the report (§2.1, §2.2).
def oc_match(value, pattern):
    value = value.replace("\\", "/")
    regex = re.sub(r"[.+^${}()|\[\]\\]", lambda m: "\\" + m.group(0),
                   pattern.replace("\\", "/"))
    regex = regex.replace("*", ".*").replace("?", ".")
    if regex.endswith(" .*"):
        regex = regex[:-3] + "( .*)?"
    return re.match("^" + regex + "$", value, re.S) is not None


def oc_decision(command, rules):
    found = [action for pattern, action in rules.items() if oc_match(command, pattern)]
    return found[-1] if found else "ask"


def check_delegated_policy():
    problems = []
    sys.path.insert(0, str(ROOT / "scripts"))
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("delegate_mod", DELEGATE)
    spec = importlib.util.spec_from_loader("delegate_mod", loader)
    d = importlib.util.module_from_spec(spec)
    loader.exec_module(d)
    rules = json.loads((ROOT / "config" / "command-boundaries.json").read_text())["rules"]
    policy = d.opencode_permissions(rules)["permission"]["bash"]
    if list(policy)[0] != "*":
        problems.append("the '*' base is not first, so findLast order is wrong")
    checked = 0
    for rule in rules:
        if rule.get("delegated") != "deny":
            continue
        for example in rule["examples"]:
            if "\n" in example:
                continue
            forms = [example, "/usr/bin/" + example, "env X=1 " + example,
                     "sudo " + example, "bash -c '%s'" % example, "timeout 30 " + example,
                     'sh -c "%s"' % example]
            for form in forms:
                checked += 1
                if oc_decision(form, policy) != "deny":
                    problems.append("%s: delegated policy does not deny %r" % (rule["name"], form))
        # Counter-examples are checked against the rule's own unwrapped patterns, as the
        # boundary suite does: wrapper tolerance is meant to over-match text that merely
        # mentions a command, and another rule may legitimately deny the same command.
        own = {pattern: "deny" for pattern in d.rule_patterns(rule)}
        for counter in rule.get("not_examples") or []:
            if oc_decision(counter, own) == "deny":
                problems.append("%s: delegated policy denies %r" % (rule["name"], counter))
        # A wrapper prefix must never turn a short program name into a substring match.
        for word in ("git add hooks/guard.py", "git commit --amend --no-edit"):
            hits = [p for p in d.denied_bash([rule]) if oc_match(word, p)]
            if hits and rule["name"] not in ("commit", "rebase-inside-delegated-run"):
                problems.append("%s: %r is denied via %r" % (rule["name"], word, hits[0]))
    size = len(json.dumps(d.opencode_permissions(rules)))
    if size > 100000:
        problems.append("the delegated policy is %d bytes, near the 128 KiB env limit" % size)
    return problems, checked, size


def main():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        config = scratch_config(tmp)
        env = dict(os.environ, FRAPPE_ORCHESTRATOR_CONFIG=str(config),
                   FRAPPE_ORCHESTRATOR_STATE=str(Path(tmp) / "state"), TMPDIR=tmp)
        old = baseline_guard(tmp)

        # --- 1. routine work ---------------------------------------------------
        new_prompts, old_prompts, latencies = [], [], []
        for command in ROUTINE:
            decision, elapsed, reason = decide(GUARD, env, bash(command))
            latencies.append(elapsed)
            if decision in ("ask", "deny") or (decision or "").startswith("error"):
                new_prompts.append((command, decision, reason[:100]))
            if old:
                # The old hook's convention: .local is a development site, so the same
                # sites are development sites to it without any listing.
                old_command = command.replace(DELEGATE, "/x/scripts/delegate")
                odecision, _, _ = decide(old, env, bash(old_command))
                if odecision in ("ask", "deny"):
                    old_prompts.append(command)
        for command, decision, reason in new_prompts:
            failures.append("routine command prompted (%s): %r - %s"
                            % (decision, command[:80], reason))

        # --- 2. protected work -------------------------------------------------
        unprotected_before = []
        for command, allowed in PROTECTED:
            decision, elapsed, _ = decide(GUARD, env, bash(command))
            latencies.append(elapsed)
            if decision not in allowed:
                failures.append("protected command decided %r, wanted %s: %r"
                                % (decision, sorted(allowed), command[:80]))
        if old:
            for command in NEWLY_PROTECTED:
                odecision, _, _ = decide(old, env, bash(command))
                if odecision not in ("ask", "deny"):
                    unprotected_before.append(command)

        for command, allowed in REVIEW_FINDINGS:
            decision, _, _ = decide(GUARD, env, bash(command))
            if decision not in allowed:
                failures.append("review finding regressed: %r decided %r, wanted %s"
                                % (command[:90], decision, sorted(map(str, allowed))))
        for command in STILL_ROUTINE:
            decision, _, reason = decide(GUARD, env, bash(command))
            if decision in ("ask", "deny"):
                failures.append("routine inspection now prompts (%s): %r - %s"
                                % (decision, command[:80], reason[:80]))
        # The lexer is linear: a long command with many `#` must not run past the hook's
        # timeout, which Claude Code treats as non-blocking.
        started = time.monotonic()
        decide(GUARD, env, bash("echo " + "a # b\n" * 30000 + "git push"))
        if time.monotonic() - started > 3:
            failures.append("a 180 KB command took %.1fs to assess" % (time.monotonic() - started))

        # --- 3. the edit guard -------------------------------------------------
        repo = Path(tmp) / "repo"
        (repo / ".git").mkdir(parents=True)
        target = str(repo / "app.py")

        def edit(path, tool="Edit"):
            return {"hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(repo),
                    "tool_input": {"file_path": path, "old_string": "a", "new_string": "b"}}

        decision, _, _ = decide(GUARD, env, edit(target))
        if decision is not None:
            failures.append("an ordinary edit got a decision: %r" % decision)
        decision, _, _ = decide(GUARD, env, edit(str(config / "sites.json"), "Write"))
        if decision != "ask":
            failures.append("editing the plugin's sites.json decided %r, wanted ask" % decision)
        orchlib_env = dict(env)
        orchlib_env.update({orchlib.ENV_RUN: "standin", orchlib.ENV_MODE: "implement",
                            orchlib.ENV_CWD: str(repo.resolve())})
        writer = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                  env=orchlib_env)
        try:
            state = Path(tmp) / "state" / "active"
            state.mkdir(parents=True, exist_ok=True)
            (state / "standin.json").write_text(json.dumps({"dispatcher_pid": 0}))
            decision, _, reason = decide(GUARD, env, edit(target))
            if decision != "deny" or "still active" not in reason:
                failures.append("an edit beside a live delegated writer decided %r" % decision)
            decision, _, _ = decide(GUARD, env, edit(str(Path(tmp) / "elsewhere.py")))
            if decision is not None:
                failures.append("an edit outside the writer's repo was blocked: %r" % decision)
        finally:
            writer.kill()
            writer.wait()
        decision, _, _ = decide(GUARD, env, edit(target))
        if decision is not None:
            failures.append("the edit guard still blocked after the writer ended: %r" % decision)
        if (state / "standin.json").exists():
            failures.append("the stale registry entry was not cleaned up")

    # --- 4. delegated policy ---------------------------------------------------
    policy_problems, policy_checked, policy_size = check_delegated_policy()
    failures += policy_problems

    # --- report ----------------------------------------------------------------
    print("Routine commands that raised a prompt (synthetic corpus, %d commands):"
          % len(ROUTINE))
    if old:
        print("  hook at %s: %d   current hook: %d" % (BASELINE, len(old_prompts),
                                                        len(new_prompts)))
        print("Protected commands the baseline let through, now asked or denied: %d of %d"
              % (len(unprotected_before), len(NEWLY_PROTECTED)))
        if len(old_prompts) <= len(new_prompts):
            failures.append("no prompt reduction against the baseline")
    else:
        print("  (baseline commit not available; comparison skipped)")
    print("Delegated policy: %d wrapped forms checked, %d bytes" % (policy_checked, policy_size))
    print("Hook latency: median %.0f ms, max %.0f ms over %d calls" % (
        statistics.median(latencies) * 1000, max(latencies) * 1000, len(latencies)))
    if failures:
        print("\nFAILED (%d):" % len(failures))
        for line in failures:
            print("  - %s" % line)
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
