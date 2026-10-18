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

## Patch: bare agent invocation

Phase 03 added the delegation dispatcher, and with it a gap this hook is the only thing
that can close.

The dispatcher carries three things a bare CLI call does not: the model, effort, and
timeout resolved from `config/model-routing.json`; the OpenCode permission policy that
holds a delegated run inside the same push, staging, and live-site boundaries this hook
enforces; and the structured result contract that keeps an agent's self-report separate
from verification. A bare `opencode run` or `codex exec` typed as a Bash command skips all
three. Every boundary this hook exists to make unconditional would lapse the moment work
was delegated outside the dispatcher — and delegation is now the normal path.

Phase 03 was forbidden from touching `hooks/`, so it reported the command shape instead.
This patch is the decision that followed.

### The rule

A fourth rule in `hooks/guard.py`, alongside push, blanket staging, and live-site
execution:

```python
AGENT_CLIS = {
    "opencode": ("run", OPENCODE_OPTS_WITH_ARG),
    "codex": ("exec", CODEX_OPTS_WITH_ARG),
}
```

**Deny, not ask.** Same test that made blanket staging a deny and push an ask: deny is
free where a correct alternative always exists. For a bare agent run it does — the
dispatcher. For push it does not, which is why push stayed an ask.

**Matched on the subcommand, not the program.** `opencode` and `codex` are ordinary CLIs
with ordinary informational subcommands, and denying the program name would break them.
`AGENT_CLIS` maps each program to the one subcommand that starts an agent run, resolved
through the existing `subcommand()` helper — the same mechanism already used for `git` and
`bench`. Each program gets its own options-with-argument set, because `-c` is a boolean
(`--continue`) for OpenCode and takes a value (`--config`) for Codex; one shared set would
have mis-parsed one of them.

**The reason redirects rather than scolds.** It gives the exact dispatcher command to use
and says what a bare invocation skips. `CLAUDE_PLUGIN_ROOT` is exported to hook processes,
so the reason names the real absolute path to `scripts/delegate`; with the variable absent
it degrades to the relative path rather than producing a broken one.

### The dispatcher is not caught by its own rule

Confirmed, not assumed. The rule binds commands Claude runs through the Bash tool, which
is what `PreToolUse` with matcher `Bash` sees. `scripts/delegate` launches `opencode` and
`codex` with `subprocess.Popen` from its own process; those children are not Bash tool
calls and no hook runs for them.

Both halves were verified: a payload whose command is a `scripts/delegate …` invocation
passes through untouched (program name is `delegate`, which matches no rule), and the
dispatcher run end to end against a stub CLI still executed its child and returned
`status=completed`, `result_block=present`.

### Open questions from this patch

1. **The bypass is closed for the Bash tool, not for the process tree.** Anything that
   spawns `opencode` or `codex` without going through the Bash tool is invisible here, as
   it always has been. That is the same boundary Open question 1 below describes for
   `sudo mysql`, not a new class of gap.
2. **Option sets are best-effort.** An option that takes a separate argument, appears
   before the subcommand, and is missing from that program's set would cause
   `subcommand()` to return the option's value and the rule not to fire. The sets were
   built from each CLI's own help output and source, and the common forms are verified
   below, but they are literals and can drift as the CLIs change.
3. **The duplication set is now four rules in the hook.** Push, staging, and live-site are
   mirrored in `skills/orchestration/SKILL.md`; this fourth one is mirrored in that skill's
   `## Delegation` section and in `scripts/delegate`'s own permission policy. Nothing
   enforces that they stay in sync.

### Patch verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| 8 bare-invocation payloads | All `deny`: `opencode run "…"`, the full dispatcher-shaped `opencode run --agent build --auto --model … "…"`, `codex exec --sandbox read-only -`, `codex exec "…"`, `opencode -m … run "…"`, `codex -m … exec "…"`, `cd /repo && opencode run "…"`, `git status; codex exec "…"` |
| 11 pass-through payloads | All silent: `opencode models`, `opencode --help`, `opencode --version`, `codex --version`, `codex --help`, `opencode models \| grep run`, `opencode agent list`, `opencode debug config`, `opencode upgrade`, `npm run build`, `yarn run test` |
| 3 dispatcher-invocation payloads | All silent — relative path, absolute path, and with a stdin redirect |
| Dispatcher end to end with a stub CLI | `status=completed`, `exit_code=0`, `result_block=present`; the child CLI ran. The hook is not in that path |
| Regression, 11 payloads | Unchanged: `git push` / `--force` / `git -C … push` → ask; `git add .` / `-A` / `--all` → deny; `bench console`, `bench --site … migrate`, `bench execute …`, `mysql -u root -p`, inline `frappe.get_all` → ask |
| Regression, 7 pass-through payloads | Unchanged: `git add <path>`, `git status --porcelain`, `git commit -m "push the fix"`, `bench start`, `bench build`, `npm test`, `ls -la` |
| Malformed payloads (`not json`, `{}`, `{"tool_input":null}`, `{"tool_input":{"bash_id":"x"}}`) | Exit 0, no stdout, no stderr |
| Reason string with `CLAUDE_PLUGIN_ROOT` set | Names the absolute `…/scripts/delegate` |
| Reason string with the variable absent | Degrades to `scripts/delegate` |
| Timing, 10 invocations | 37 ms each |
| `git ls-files -s hooks/guard.py` | `100755` — exec bit retained |

Not verified: the rule firing inside a live session. Open question 3 above stood for the
original three rules and stands for this one.

## Patch: informational agent invocations pass through

The bare-agent rule denied `codex exec --help`. The rule matches on the subcommand, and
`exec` is the subcommand, so it fired exactly as written — on a command that starts no
run, contacts no provider, and executes nothing. It just prints usage text.

**Why that is worth a patch rather than a shrug.** A deny that fires on nothing dangerous
teaches the reader that the rule is noise. The next deny it issues is the one that
matters, and it arrives with the credibility the false one spent. The rule's own reason
text tells the agent to go through the dispatcher instead — advice that makes no sense for
`--help`, which the dispatcher does not offer, so the only available next move is to work
around the hook. Every part of that is worse than the rule not firing.

### The rule

`--help`, `-h`, or `--version` anywhere in the segment now exempts an agent-CLI
invocation. Two constraints on that, both load-bearing:

**Whole tokens, not a substring of the segment.** The brief is an argument to these CLIs,
so `codex exec "explain the --help output"` mentions the flag without carrying it. A
substring test over the raw segment would exempt a real delegated run for quoting a word,
which converts a false positive into a bypass — a strictly worse trade. `INFO_FLAGS`
is intersected with the token list `shlex` already produced for the rule.

**Scoped to this rule alone.** The live-site rules deliberately do not take the same
exemption, because there the flag can be inert rather than suppressing:

```
python3 -c "frappe.connect()" --help
```

The interpreter ignores the extra argument and the snippet still runs. `--help` suppresses
execution only for a program that parses it, and a rule cannot know which those are. For
the two agent CLIs it can: both are argument-parsing programs whose subcommand is the
thing being matched. That reasoning does not transfer, so neither does the exemption —
`git push --help` still asks, `git add -A --help` is still denied, and
`bench --site … console --help` still asks.

### Patch verification

| Check | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `ruff check --line-length 90 hooks/guard.py` | `All checks passed` |
| 21 payloads through `check()`, 0 failures | See the three groups below |
| Newly exempt, 5 payloads | Silent: `codex exec --help`, `codex exec -h`, `codex exec --version`, `opencode run --help`, `opencode run -h` |
| Real runs still denied, 6 payloads | `codex exec -`, `codex exec --sandbox read-only -`, `opencode run --agent build --auto --model x '…'`, and the three quoting cases — `codex exec "explain the --help output"`, `opencode run --agent build 'add -h to the parser'`, `codex exec -c model="x" "run --version somewhere"` |
| Exemption is not global, 6 payloads | `git push --help` → ask; `git add -A --help` → deny; `bench --site masa.local console --help` → ask; `mysql --help` and `mysql --version` → ask; `python3 -c "frappe.connect()" --help` → ask |
| Pre-existing pass-throughs | Unchanged: `codex --version`, `opencode --help`, `opencode models`, `git status --porcelain` |
| End to end through `main()` | `codex exec --help` → no stdout at all (allowed); `codex exec -` → `deny` with the reason string |

Neither `-h` nor `--help` appears in `OPENCODE_OPTS_WITH_ARG` or `CODEX_OPTS_WITH_ARG`, so
`subcommand()` does not consume either as an option's value and the token survives to be
matched. That is checked by the `codex exec -h` and `opencode run -h` cases rather than by
inspection.

## Patch: a bench command with no `--site` still acts on a site

Phase 04 asked which Frappe operations a change requires, and the question exposed a hole
on the side of the live-site rule the hook was already guarding.

`bench --site dev.local migrate` asked. `bench migrate` passed through untouched. The
second is not a site-free command — it is the same command with the site left unstated,
and frappe's CLI supplies one from configuration: `default_site` in
`common_site_config.json`, then `currentsite.txt`
(`frappe/utils/bench_helper.py:49`). So it acts on whichever site the bench was last
pointed at.

That is worse than the case already covered. `bench --site x migrate` at least says which
site it means and is wrong only if `x` is wrong. `bench migrate` names no site at all, and
the one it acts on is invisible in the command, in the transcript, and in any later reading
of what happened. It is the No-Site-Guessing failure with nothing on screen to guess from.

Ten shapes that passed through before this patch, each of which acts on a configured site:

```
bench migrate            bench install-app <app>   bench restore <file>
bench clear-cache        bench uninstall-app <app> bench reinstall
bench backup             bench trim-tables         bench set-admin-password <pw>
bench run-tests
```

### The rule

`SITE_SUBCOMMANDS` was four entries (`console`, `mariadb`, `execute`, `run`) and is now
the full set of bench subcommands that resolve a site. The bench branch splits in two:

```python
if name == "bench":
    if "--site" in tokens:
        return "ask", SITE_REASON
    if subcommand(tokens, BENCH_OPTS_WITH_ARG) in SITE_SUBCOMMANDS:
        return "ask", UNNAMED_SITE_REASON
```

**Ask, not deny.** The `--site` form asks, and the no-flag form is the same operation with
less information on the command line. Making it deny would have been a stricter rule for
the weaker case; making it pass through — the previous behaviour — was a rule that was
quietly weaker exactly where it had least to go on. It asks, uniformly.

**The set is derived, not judged.** Every `@click.command` in `frappe/commands/*.py` whose
body calls `get_site(context)` or reads `context.sites` — 75 subcommands. The test is
*does bench resolve a site for this command*, not *does this command look dangerous*.
Those come apart: `bench list-apps` is harmless and `bench trim-tables` is not, and they
pick their site by the identical mechanism. A set filtered by apparent danger would have
kept the hole open for whichever command the filter underrated. The comment in the file
records how to re-derive it against a newer frappe, so it is refreshed rather than
appended to by hand.

**A separate reason, because it is a different mistake.** `SITE_REASON` tells the caller to
confirm which single site to target. `UNNAMED_SITE_REASON` says what is actually wrong —
the site is being resolved from configuration rather than named — and gives the correction:
`bench --site <site> <subcommand>`, with the site taken from the project's
`OPERATIONS.md` or the user. A reason that named the wrong problem would send the agent to
re-check a site it never chose.

### Deliberately not covered

Three adjacent classes fail the stated test and were left alone rather than swept in:

- **Positional-site commands** — `bench drop-site <site>`, `bench new-site <site>`. Both
  destructive, neither able to act on a site chosen by configuration, because the site is
  an argument. This rule is about an unnamed site; a wrong named site is a different
  problem and this is not the place to pretend otherwise.
- **Bench-level multi-site commands** — `bench update`, `bench backup-all-sites`. These
  act on every site in the bench rather than resolving one, so they belong to the
  broad-multi-site question, not this one.
- **`bench build`, `bench start`, `bench setup …`** — genuinely site-free. Still pass
  through, which is the point: `bench build` is the one Frappe operation Phase 04 can run
  without resolving a site at all, and a rule that stopped it would make the hook noise.

Each is named here so the gap is on the record rather than discovered again later.

### Patch verification

| Check | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `python3 -c "ast.parse(...)"` on `hooks/guard.py` | parses |
| 51 payloads through `check()` | 0 failures — decision *and* reason identity asserted, so a right decision with the wrong reason text fails |
| New rule, 17 payloads | All ask with `UNNAMED_SITE_REASON`: `migrate`, `clear-cache`, `install-app`, `list-apps`, `backup`, `restore`, `reinstall`, `trim-tables`, `uninstall-app`, `set-admin-password`, `run-tests`, `console`, `mariadb`, `execute`, `bench migrate --skip-failing`, `cd … && bench migrate`, and `bench -s dev.local migrate` |
| `bench -s dev.local migrate` | Asks as unnamed, correctly: `bench` has no `-s` option (`Error: No such option: -s`), so that command names no site |
| `--site` form, 5 payloads | Unchanged: still ask, still `SITE_REASON`, including `--site all` |
| Site-free bench commands, 7 payloads | Still pass through: `build`, `build --app`, `start`, `setup requirements`, `version`, `--help`, `init` |
| Regression, the four existing rules, 20 payloads | Unchanged: push → ask; blanket add → deny; `mysql`/`mariadb`/inline `frappe.get_all` → ask + `SITE_REASON`; bare `opencode run` / `codex exec` → deny; `--help` forms and `opencode models` → pass through; `scripts/delegate …` → pass through |
| Precedence | `bench migrate && git push` → ask; `bench migrate; git add .` → deny (deny still outranks ask) |
| 4 malformed payloads | Exit 0, no stdout, no stderr |
| End to end through `main()` | `bench migrate` → `ask` with the full reason string |
| Timing, 10 invocations | 22 ms each |
| `git ls-files -s hooks/guard.py` | `100755` — exec bit retained |

Not verified: the rule firing inside a live session, which has stood open for every rule in
this hook since the first one.
