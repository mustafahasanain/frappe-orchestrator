# Phase 01.5 Report

## What was built

- `hooks/guard.py` — the `PreToolUse` guard. Reads the hook payload on stdin, splits the
  Bash command into segments, and emits a JSON permission decision for three cases: ask
  before `git push`, deny `git add .` / `-A` / `--all`, ask before any execution against a
  live site database or Frappe instance. Everything else produces no output and passes
  through. Executable (`0755`).
- `hooks/hooks.json` — the hook configuration. One `PreToolUse` entry, matcher `Bash`,
  exec form (`"args": []`), script referenced as `${CLAUDE_PLUGIN_ROOT}/hooks/guard.py`,
  timeout 10s.
- `docs/BUILD_CONTRACT.md` — three amendments: a layout rule for `hooks/` and
  `hooks/hooks.json`; a "Phase 01.5 — Enforcement hook" scope entry; commit message rules
  (subject under 60 characters, no attribution trailers) added to Git rules so they bind
  every phase.
- `docs/reports/PHASE_01_5_REPORT.md` — this report.

`.claude-plugin/plugin.json` was not touched. Plugin hooks are discovered by convention at
`hooks/hooks.json`, so no manifest key is needed, which keeps the Phase 01 decision that
layout is defined in one place only.

## Spec coverage

| Requirement | Status | Note |
| --- | --- | --- |
| Contract: `hooks/` as a root-level component directory | Implemented | It was already named in the component list at line 39; the amendment adds the rule about `hooks/hooks.json` and convention-based discovery rather than restating it |
| Contract: Phase 01.5 scope entry allowing `hooks/` and a hooks configuration file, nothing else | Implemented | `### Phase 01.5 — Enforcement hook` |
| Contract: "Permanently out of scope" unchanged; hook refuses deployment, never performs it | Implemented | Section untouched; the new entry states the hook "decides only" and binds the section to hooks |
| Contract: commit message rules (added on review) | Implemented | Git rules section |
| One `PreToolUse` hook matched on `Bash` | Implemented | `hooks/hooks.json` |
| Reads tool input from stdin | Implemented | `json.load(sys.stdin)`, `tool_input.command` |
| Rule 1 — `git push` in any form | Implemented as **ask** | Changed from deny on your instruction; see Deviations |
| Rule 2 — deny `git add .` and `git add -A` | Implemented | `--all` included; `git add -- .` also caught |
| Rule 3 — ask on execution against a Frappe site | Implemented | `bench console` / `mariadb` / `execute` / `run`, any `bench` with `--site`, the `mysql` and `mariadb` clients, and inline `frappe.*` connection calls |
| Everything else passes through untouched | Implemented | `check()` returns `None` → no output, exit 0 → normal permission flow |
| Never blocks on an unrecognised command | Implemented | Verified against 8 unrelated commands; malformed and non-Bash payloads also exit 0 silently |
| Fast | Implemented | 30 ms per invocation measured |
| JSON output form, not bare exit 2 | Implemented | `hookSpecificOutput` with `hookEventName`, `permissionDecision`, `permissionDecisionReason`; the script never exits 2 |
| Field names verified against the current hooks reference | Implemented | See Verification |
| Reasons written as instructions to Claude | Implemented | Each names the corrective action; the site reason requires confirming the target site first |
| `${CLAUDE_PLUGIN_ROOT}`, executable script | Implemented | Exec form; `chmod +x` applied |
| No config file, allowlist system, or env-var escape hatch | Implemented | Rules are literals in the script |

## Decisions I made

- **Python, not bash + `jq`.** Both are available here. Commands routinely carry quotes,
  newlines, and heredocs, and `json.load` handles them where shell string-mangling would
  not. Cost is 30 ms per Bash call.
- **Exec form (`"args": []`)** rather than shell form. No shell re-interpretation of the
  hook command, and `${CLAUDE_PLUGIN_ROOT}` is substituted as a plain string, so a space in
  the install path cannot break the invocation.
- **Segment splitting on `; && || | & \n`.** Each segment is checked independently, so
  `bench console && git push` matches on both counts and `git status; git add .` is caught
  in its second segment. A deny outranks an ask when both appear.
- **`--all` added to the blanket-staging set** — the same flag as `-A`, spelled long.
- **Any `bench` invocation carrying `--site` asks**, not only the four named subcommands.
  The rule is "execution against a site", and `bench --site x migrate` is that. Cost:
  `bench --site x list-apps` also asks. It is an ask, not a deny.
- **`frappe.get_all` and `frappe.get_list` added** to the connection patterns beyond the
  four the skill names. The failure this phase exists to prevent — hunting for customers
  with a missing tax ID — is `get_all`-shaped.
- **The `frappe.*` regex runs on the raw segment**, not on tokens, so it also catches
  `python -c "..."` payloads and heredoc bodies.
- **No `tool_name` guard in the script.** The matcher handles it, and the script already
  ignores any payload without a string `tool_input.command`, so `BashOutput` and similar
  are inert regardless.

## Deviations

- **`git push` asks instead of denying.** Your instruction, and the reasoning is recorded
  here because it changes the shape of the rule: deny is only free where a correct
  alternative always exists. For staging it does — stage by path. For push it does not;
  sometimes pushing is the right action, and a hook that obstructs every legitimate push
  gets disabled, which is worse than no hook. The spec's rule is that push is never
  *automatic*, and an ask requires a human keystroke, so the rule still holds.
  `PUSH_REASON` accordingly tells Claude to confirm the target branch and remote with the
  user and state what will be pushed — not to hand the push off.
- **`mysql` and `mariadb` are matched as program names.** I argued for leaving them out on
  the grounds that they open no Frappe connection; you overruled it, correctly. They are a
  direct route to a live database while every other route is guarded, and covering them is
  the same two lines already used for `bench`, not an allowlist.

## Open questions

1. **Wrapped invocations are not matched** — `sudo mysql`, `env FOO=1 git push`. The
   program name is the wrapper, so no rule fires. Handling them means a prefix-stripping
   loop, which is the first step toward the config system that was ruled out. Verified as
   a real gap (`sudo mysql` passes through); left open deliberately.
2. **One false positive class.** The `frappe.*` regex matches prose, so
   `echo 'frappe.db is mentioned in a comment'` asks. Harmless direction — an ask on a
   harmless command, never a deny — and tightening it would mean parsing Python out of
   shell strings.
3. **Not verified under a live run.** The hook was exercised with 31 constructed payloads
   directly against the script, which confirms the decisions. It has not yet been observed
   firing inside a real session with the plugin installed. That needs a session where
   `bench console` is attempted and the confirmation prompt actually appears.
4. **Duplication is now real and intentional.** The push, staging, and live-site rules exist
   in both `skills/orchestration/SKILL.md` and `hooks/guard.py`. If one changes, the other
   must be changed with it. No mechanism enforces that; the contract entry says so in
   prose.

## Not built (correctly out of scope)

- Any hook on events other than `PreToolUse`, and any matcher other than `Bash`. Nothing
  asked for them.
- A config file, allowlist, or environment-variable escape hatch — explicitly excluded.
- Any deployment capability. The hook refuses; it never performs. Deployment remains
  permanently out of scope for every phase.
- Enforcement of the required orchestration preamble, task classification, or model
  routing. Those are guidance and stay in the skill; only the dangerous cases moved.
- Delegation dispatcher and agent adapters — Phase 03. Context templates — Phase 02.
  Frappe operations skill — Phase 04.

## Verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `claude plugin validate hooks --strict` | Not applicable — exit 1, "No manifest found in directory". This subcommand validates a plugin directory, not an individual component directory, so there is no per-component check for hooks |
| `python3 -c "json.load(open('hooks/hooks.json'))"` | `valid json` |
| `ls -l hooks/guard.py` | `-rwxr-xr-x` — executable bit set |
| `git ls-files -s hooks/guard.py` | `100755`. This repository has `core.fileMode = false` (WSL), so `chmod +x` alone was recorded as `100644` and the exec bit would have been lost on a fresh clone, breaking the exec-form invocation. Fixed with `git update-index --chmod=+x` before the commit |
| 31 constructed payloads piped to `hooks/guard.py` | All decisions as designed; every invocation exit 0. `git push`, `git push --force origin main`, `git -C /repo push` → ask. `git add .` / `-A` / `-- .` / `--all` → deny. `git add <paths>`, `git commit -m 'push the fix'`, `git status --porcelain`, `git log --oneline \| grep push` → pass through. `bench console`, `bench mariadb`, `bench --site X console/execute/run/migrate`, `mysql -u root -p`, `mariadb -u root`, inline `frappe.init`/`get_all`, heredoc body → ask. `bench start`, `bench build`, `cat …customer.json`, `npm test`, `ls -la` → pass through. `bench console && git push` → ask; `git status; git add .` → deny |
| Malformed payloads (`not json`, `{}`, `{"tool_input":null}`, `{"tool_input":{"bash_id":"x"}}`) | Exit 0, no stdout, no stderr — nothing is blocked when the payload is not understood |
| Timing, 10 invocations | 30 ms each |
| `ls -A .claude-plugin` | `plugin.json` only — layout rule holds |
| `find . -type f` (excluding `.git`) | `hooks/` is at the repository root alongside `skills/` and `config/` |
| Hooks reference cross-check | `docs.claude.com/en/docs/claude-code/hooks` now 301s to `code.claude.com/docs/en/hooks`. Fetched both that page and the plugins reference. Confirmed verbatim: `hookSpecificOutput` with `hookEventName: "PreToolUse"`, `permissionDecision` ∈ `allow` / `deny` / `ask`, `permissionDecisionReason`; stdin fields `tool_name` and `tool_input`; plugin hooks at `hooks/hooks.json` with a top-level `hooks` object keyed by event name; `${CLAUDE_PLUGIN_ROOT}` supported in hook commands in both exec and shell form. No field name was written from memory |
| `git status --porcelain` before starting | Empty — clean working tree; nothing pre-existing was staged or reverted |
