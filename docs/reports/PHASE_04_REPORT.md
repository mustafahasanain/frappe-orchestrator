# Phase 04 Report

> **`--mode test` is verified against the real Codex CLI**, closing the last unexercised
> mode — and the probe corrected a reason this repository had recorded as settled. See
> [Finding: what workspace-write actually refuses](#finding-what-workspace-write-actually-refuses).
>
> **Two containment gaps found.** One is closed, in its own commit under a Phase 01.5
> amendment: a bench command with no `--site` still acts on a site. The other is open and
> is not mine to close — `scripts/delegate`'s deny list has the same hole, so the two
> layers now disagree. See
> [Gap not closed](#gap-not-closed-the-dispatchers-deny-list-has-the-same-hole).
>
> **The duplication map** this phase was asked to produce, rather than add to, is at
> [The duplication map](#the-duplication-map).

## What was built

- `skills/frappe-operations/SKILL.md` — the Frappe operations skill. Decides which bench
  operations a diff requires (build, migrate, clear-cache, restart), where they run
  (bench directory, not the repository root), how the site is resolved and why it is
  always named, what needs confirmation and what is refused outright, how each operation
  is verified, what a failure means, and where the whole step sits in the Phase 03
  workflow. Carries the required plan line.
- `skills/orchestration/SKILL.md` — one integration edit. `## Environment operations` said
  "None are defined yet, so this step is currently a no-op"; it now names the new skill by
  `${CLAUDE_PLUGIN_ROOT}` path and carries the four rules that must hold when that skill is
  not read.
- `skills/project-context/templates/OPERATIONS.md` — one hint comment. The Setup
  assumptions section now asks for the development site by name, because that is the fact
  the no-site-guessing rule depends on and it previously had nowhere to live.
- `docs/BUILD_CONTRACT.md` — two amendments: Phase 04's allowed list gains integration
  edits (Phases 02 and 03 both had it; its absence here was an oversight), and the
  Phase 01.5 entry gains the fifth hook rule. The second landed in the earlier commit.
- `docs/reports/PHASE_03_REPORT.md` — a correction. Its account of what the Codex sandbox
  refuses was right in conclusion and wrong in reason; the original text stands with
  pointers to the correction, per that report's own convention.
- `hooks/guard.py`, `docs/reports/PHASE_01_5_REPORT.md` — the fifth rule, committed
  separately before this phase.
- `docs/reports/PHASE_04_REPORT.md` — this report.

No helper script was written. No test was added: this phase ships prose, and nothing in it
fails silently. `config/`, `scripts/`, `.claude-plugin/`, and the phase documents were not
touched.

## Spec coverage

| Requirement (Phase 04) | Status | Note |
| --- | --- | --- |
| Determine required operations from diff + context + rules | Implemented | `## The default is nothing` |
| Do not run build/migrate/clear-cache/restart by default | Implemented | Same section, and the plan line makes each `no` explicit |
| Operation plan before executing | Implemented | `## Required plan line`; one line, all four fields always present |
| build — when frontend assets change | Implemented | `### build`, scoped `--app` |
| migrate — when schema or metadata changes | Implemented | `### migrate` |
| clear-cache — only with a reason | Implemented | `### clear-cache`, `hooks.py` named as the real case |
| restart — only when the runtime requires it | Implemented | `### restart`; the worker/scheduler distinction, `OPERATIONS.md` decides |
| `OPERATIONS.md` overrides generic assumptions | Implemented | `## The project overrides these rules` |
| Local development sites handled | Implemented | `## Site resolution` |
| Verification after operations, proportional | Implemented | `## Verification`, one row per operation |
| Site resolution from context, bench config, or user | Implemented | `## Site resolution` |
| No site guessing; dev site only when explicitly identified | Implemented | Same, plus the template hint that gives it somewhere to be recorded |
| One site → run; multiple or unclear → stop and ask | Implemented | Same |
| Site-independent commands may run without resolution | Implemented | `bench build`, marked site-independent |
| Multi-site benches not migrated broadly | Implemented | `## Confirmation and refusal`; never `--site all`, never a loop |
| Multi-app: stay scoped to the affected app | Implemented | `bench build --app <app>` is the default shape |
| `install-app` never inferred | Implemented | `## Confirmation and refusal` |
| Destructive migration stops for confirmation | Implemented | Same, with what counts as destructive |
| Operation failure → BLOCKED, with cause triage | Implemented | `## When an operation fails`, four causes, defers to Phase 03's handling |
| Operations before dependent verification | Implemented | `## Where this fits in the workflow` |
| Integration with the Phase 03 loop | Implemented | Same section; the orchestration skill's slot now points here |
| Executed by Claude directly, not via the dispatcher | Implemented | `## Operations are never delegated` — and now with a measured reason |
| Remote/demo/production refused, not confirmed | Implemented | Opening paragraph and `## Confirmation and refusal`, both deferring to the orchestration skill's boundary |
| Routine operations as thin wrappers | Implemented | `## Routine operations`, six command shapes |
| No dedicated Frappe agent, no operations framework | Implemented | One Markdown file; no script, no config, no state |
| Guarantees 1–15 | Implemented | Each maps to a row above. 15 is structural: nothing in this phase can reach a remote host |
| Project-specific operations documented in `OPERATIONS.md` | Implemented | `## The project overrides these rules`, plus the template |

## Decisions I made

- **No helper script.** The phase allows "any local operation helper the phase explicitly
  requires", and it requires none. Every decision here — does this diff need a migration,
  is this site a development site, is this migration destructive — is judgement over a
  diff and a prose document. A script encoding it would be a second rule engine to keep in
  sync with the skill, which is the problem this phase was asked to map, not add to.
- **The plan line always prints all four operations.** A line that listed only what was
  required would make "I did not consider restart" and "restart is not needed" look
  identical. `build no | migrate no | clear-cache no | restart no | site: n/a` is shown in
  the skill as the common, complete answer, so emitting it does not read as failure.
- **`bench build --app <app>`, not `bench build`.** A bare build rebuilds every app in the
  bench. Scoping it to the changed app follows the phase's own multi-app rule, and costs a
  flag.
- **The live-site boundary is pointed at, never restated.** The skill has a section whose
  entire content is that the rule lives in the orchestration skill and `hooks/guard.py`,
  and that this skill decides only which operations a change requires. That is a
  deliberate non-duplication, given what the map below shows.
- **`--site` is always written explicitly**, even where bench would resolve one. This is
  Phase 04's own no-site-guessing rule expressed as a command shape rather than a second
  copy of a hook rule — and it is what makes the operation a decision instead of a
  configuration lookup.
- **Restart rules defer to `OPERATIONS.md` rather than asserting Frappe behaviour.** Two
  defaults are stated because they are load-bearing and stable — the dev server reloads
  Python, workers and the scheduler do not — and everything beyond that is the project's to
  declare.
- **The Phase 03 correction went in this commit, not the hook commit.** The evidence comes
  from this phase's probe, and the hook commit is about the hook.

## Deviations

- **The contract was amended twice**, both recorded in it and above. Phase 04's allowed
  list gained integration edits, which Phases 02 and 03 already had; the Phase 01.5 entry
  gained the fifth rule. Both follow the route the contract itself lays down.
- **The skill is 253 lines**, longer than the two context templates it leans on. The phase
  document is unusually prescriptive about operation-by-operation behaviour, and every
  section maps to a requirement in the table above.

## Open questions

1. **`scripts/delegate`'s deny list now disagrees with the hook.** Detailed below. It is
   the one thing found this phase that is still open, and it is a rules change to a
   Phase 03 file, so it is not mine to make.
2. **Nothing verifies the plan line, as nothing verifies the other two.** The preamble, the
   impact line, and now the operations plan line are all skill prose. The hook sees Bash
   commands, not missing output. This is the same gap Phase 02 recorded, one line longer.
3. **No live run of this skill.** Every phase so far has needed a real session before
   anything could be called working, and this one has had none: no task has yet gone
   implementation → operations → review in a real Frappe repository. Worth testing first: a
   `.js`-only change (should propose build, no migrate, no site) and a DocType field
   addition (should propose migrate, and stop if no development site is recorded).
4. **`bench drop-site` and `bench new-site` remain unguarded**, deliberately — they name
   their site as an argument, so they fail the rule's stated test. Destructive and
   unguarded is still worth your decision.
5. **Codex 0.146.0 is older than the 0.149.0 Phase 03 verified against.** Below.

## Not built (correctly out of scope)

- Any remote operation: SSH, demo, production, server inventory, remote bench selection,
  project-to-server mapping, remote git pull, rollback, remote database operations. Refused
  by the skill, permanently out of scope for every phase.
- A deployment script, deployment configuration, or any invocation of one.
- A Frappe agent, an operations framework, an operation registry, or a state file — all
  named as non-goals.
- Any change to `config/model-routing.json`, `scripts/delegate`, or `.claude-plugin/`.
- Any new hook rule in this commit. The one this phase needed was reported, amended into
  Phase 01.5, and committed separately, per the precedent.
- A refactor of the duplication mapped below. Explicitly deferred to you.

## Finding: what workspace-write actually refuses

`--mode test` had never been run against the real Codex CLI. It is the only mode granted
`workspace-write`, so it is where Frappe operations and the sandbox meet, and the open
question attached to it was whether that sandbox blocks a local-socket database
connection. Both are now settled.

**The mode works end to end.** A real run through the dispatcher, in a throwaway
repository: `status=completed`, `exit_code=0`, 81.1 s of a 420 s SMALL timeout,
`result_block=present`, `off_contract_keys=[]`, `verdict=PASS`, one test file written and
run. Codex wrote `tests/test_environment_reach.py` faithful to the brief and left
`src/calc.py` untouched, which is the "tests only, never production code" rule holding in
the one mode that could break it.

**The answer is no — workspace-write does not let a local-socket connection through.**
Ground truth from the results file the test wrote, read directly rather than taken from the
agent's summary:

| Probe | Result |
| --- | --- |
| write inside the work tree | ok — positive control; the run really executed commands |
| AF_UNIX connect to `/run/mysqld/mysqld.sock` | blocked — `PermissionError: [Errno 1] Operation not permitted` |
| TCP `127.0.0.1:3306` | blocked — same `EPERM` |
| TCP `1.1.1.1:443` | blocked — same `EPERM` |
| write to `$HOME` | blocked — read-only file system |

**The errno is the finding, not the refusal.** One identical `EPERM` across three address
families is a syscall-level denial — the `--apply-seccomp-then-exec` layer. It is not the
network namespace, which produces different errors, and it is not the filesystem.

That distinction is not academic, and it is why this is recorded as a finding rather than a
line in a table. Phase 03 justified Codex needing no OpenCode-style permission map by
saying `workspace-write` "is confined to the working tree with no network access". Running
the identical probe under codex's own namespace flags **without** its seccomp filter —
captured by putting a logging wrapper in front of `bwrap` — gives `ECONNREFUSED`,
`ENETUNREACH`, and **a successful AF_UNIX connection to MariaDB, greeting and all**. So the
property Phase 03 named does not close the socket. A different property, which that report
never identified, does.

I reached the wrong conclusion myself on the way here, from exactly that reproduction, and
said so before designing anything around it. What separated the two answers was running the
real thing and recording an errno instead of a verdict.

**What this means for Phase 04:** a delegated Codex run cannot reach a site database, for a
verified reason. That does not license delegating Frappe operations — see the next two
sections for why the rule holds regardless.

## Finding: a delegated Codex run writes to user-level configuration

The first (failed) run added an entry to `~/.codex/config.toml`:

```toml
[projects."<the probe repository>"]
trust_level = "trusted"
```

Nothing in the plugin accounts for this. The dispatcher creates its workspace outside the
repository, and every verification so far has checked that no delegation artifact reaches
the working tree — which is true, and which is not the same claim as containment. A
delegated run modifies the user's own Codex configuration, outside the repository,
persistently, and marks a directory trusted for every future Codex run on this machine.

**Anything stating that a delegated run is confined to the work tree is wrong as stated.**
Writes to the repository are confined; the agent process is not the only writer, and the
CLI itself is outside that boundary. No mitigation is built here — this is named, not
solved. The stale scratchpad entry was removed after the probes, leaving the 15 real
entries intact.

## Hook gap found and closed

`bench --site dev.local migrate` asked. `bench migrate` passed through — and is not
site-free: frappe resolves a site from `default_site`, then `currentsite.txt`
(`frappe/utils/bench_helper.py:49`), so it acts on whichever site the bench was last
pointed at, named nowhere. Ten shapes were affected, `install-app` among them, which is the
one command the phase says must never be inferred.

Reported rather than fixed inside this phase, then closed in its own commit under a
Phase 01.5 amendment: `SITE_SUBCOMMANDS` went from four entries to the 75 that frappe's own
CLI resolves a site for, derived from the command definitions rather than filtered by which
look dangerous. It asks, matching the `--site` form rather than being weaker than it. Full
write-up and verification are in the Phase 01.5 report.

## Gap not closed: the dispatcher's deny list has the same hole

`scripts/delegate`'s `DENIED_BASH` is the layer that holds a delegated **OpenCode** run
inside the same boundaries. Checked against the same command shapes:

| Command | `DENIED_BASH` |
| --- | --- |
| `bench --site dev.local migrate` | denied by `bench --site*` |
| `bench console`, `mysql -u root` | denied |
| `bench migrate` | **no pattern matches** → falls to `"*": "ask"` → `--auto` approves it |
| `bench clear-cache`, `bench install-app <app>`, `bench backup`, `bench reinstall`, `bench trim-tables`, `bench drop-site <site>` | **same** |

So after the hook commit the two layers disagree: the same command asks when Claude runs it
and executes silently when a delegated OpenCode agent runs it. The `--auto` flag makes this
concrete — an `ask` is auto-approved, and there is no human in that process to ask.

I did not fix it. It is a rules change to a Phase 03 file, and the contract's Phase 01.5
amendment permits touching only the deny *reason* string. The fix is mechanical — the same
subcommand set, as `"bench <sub>*"` patterns — and it is your call. Until then,
`## Operations are never delegated` in the new skill is not stylistic advice, which is why
the skill states the reason rather than the rule alone.

## The duplication map

Every rule that now exists in more than one place. **Nothing keeps any row in sync.** No
test asserts agreement between a skill and the hook, or between the hook and the
dispatcher; each pairing is prose in the contract saying they must match. This is a map,
not a proposal — no row was refactored.

| # | Rule | Copies | Kept in sync by |
| --- | --- | --- | --- |
| 1 | Push is never automatic | `skills/orchestration/SKILL.md:478`, `:499` · `hooks/guard.py:94` (ask) · `scripts/delegate:60-61` (deny) · `docs/BUILD_CONTRACT.md:233` | nothing |
| 2 | No blanket staging | `orchestration:473` · `guard.py:32,99,167` (deny) · `delegate:67-74` (deny, 9 patterns) · `BUILD_CONTRACT.md:234` | nothing |
| 3 | Live-site execution needs confirmation | `orchestration:505-524` (`### Live site access`) · `guard.py:45-65,125,184` · `delegate:75-85` | nothing. **Three matching engines**: a prose list, a token/subcommand parser, and glob patterns |
| 4 | Agent CLIs run through the dispatcher | `orchestration:220-241` · `guard.py:71-74,104-112` (deny) | nothing |
| 5 | The dispatcher's own invocation — modes, `--cwd`, `--model` | `orchestration:231-234` · `guard.py:106-107` (inside the deny reason) · `delegate:27,352-356,549,560` | the contract permits updating the hook's reason string; nothing checks it |
| 6 | Codex never implements | `orchestration:61,238` · `delegate:26,574` | nothing |
| 7 | The orchestrator owns the commit | `orchestration:463-475` · `delegate:62-64` (`git commit*` denied) | nothing |
| 8 | BLOCKED is not a failed attempt | `orchestration:363-381` · `delegate:146-148` (contract text) · `frappe-operations:211-221` (defers, does not restate) | nothing |
| 9 | Context and impact rules | `orchestration:181-205` (4 rules) · `skills/project-context/SKILL.md` (full) | nothing; the duplication is deliberate, for when the second skill does not load |
| 10 | Deployment is refused, never performed | `orchestration:480-491,503` · `frappe-operations:11,190-192` · `templates/OPERATIONS.md:39` · `BUILD_CONTRACT.md:96,219-227` | nothing |
| 11 | A site is never guessed; dev site must be declared | `frappe-operations:123-148` · `orchestration:339-349` · `templates/OPERATIONS.md:11-14` · `guard.py:34-44,114-122` | nothing. **New this phase** — three of those four are new or newly edited |
| 12 | The bench subcommand set that resolves a site | `guard.py:45-64` (75 entries) · frappe's own CLI, from which it was derived | nothing. Drifts when frappe adds a command; the file records how to re-derive |
| 13 | Which operations a diff requires | `frappe-operations:58-110` · each project's `docs/ai-context/OPERATIONS.md` | by design: the project overrides, and the skill says so |

Three observations, offered because the map is what was asked for:

- **Row 3 is the expensive one.** The same rule in three engines, and the Phase 03 report
  already flagged that chained-command matching differs between them. Row 11 has just
  joined it at four copies.
- **Rows 1, 2, and 3 are duplicated on purpose and correctly** — the hook exists because
  skill activation is stochastic. Duplication is the mechanism, not the defect. What is
  missing is anything that fails when the copies disagree, which is exactly how row 3 came
  to have the hole this phase found in one copy and not the others.
- **The one place a duplicate is checked** is `tests/test_parser.py`'s mode matrix, which
  asserts that four tables inside `scripts/delegate` agree. That is the shape a check would
  take for the rest: a test that reads both copies and compares them. Row 12 could not be
  checked that way — its other copy is frappe's source, not this repository's.

## Codex version note

`codex-cli 0.146.0` is installed. Phase 03 verified the review path against **0.149.0** —
the stream split the parser depends on, the flag set the adapter is built on, the live
review loop, and the onboarding mode. That is a version going backwards, and everything
Phase 03 called verified was verified on a build that is no longer running here.

Today's run confirms `codex exec`, `--sandbox`, `-C`, and stdin delivery still behave as the
adapter expects on 0.146.0, and the parser handled its output. The review, onboard, and
implement paths were not re-run. Worth knowing rather than assuming: the auth session also
expired between the two, which cost this phase its first probe attempt.

## Verification

| Check | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `claude plugin validate skills --strict` | `✔ Validation passed` (exit 0) — three skills now |
| `python3 tests/test_parser.py` | `38 cases, 3 timed, 8 strip, mode matrix, adapters and --cwd checked` … `ok`, exit 0 |
| **Live `--mode test` run against the real Codex CLI** | `status=completed`, `exit_code=0`, 81.1 s, `result_block=present`, `verdict=PASS`, `off_contract_keys=[]` |
| Test-mode run stayed in contract | Wrote `tests/test_environment_reach.py`, ran it, left `src/calc.py` untouched |
| Sandbox probe, ground truth | Read from the results file the test wrote, not the agent's summary; no stray file in `$HOME`; positive control passed |
| Probe isolation | Throwaway git repository created for it in the scratchpad, verified as its own work tree root before use, distinct from this repository |
| Unsandboxed baseline | All five probes reachable, so every "blocked" result is a refusal and not an absent service |
| `bwrap` flag capture | Codex's sandbox flags recorded via a logging wrapper; the no-seccomp reproduction is what shows the network namespace alone leaves AF_UNIX open |
| Hook, 51 payloads | 0 failures — decision and reason identity both asserted. Committed separately; full matrix in the Phase 01.5 report |
| `scripts/delegate` deny list vs the same commands | 7 of 10 unmatched — the gap reported above, not fixed |
| `git diff --stat` on the orchestration skill | 20 insertions, 3 deletions — the `## Environment operations` body only |
| `git diff --stat` on the template | 8 insertions, 2 deletions — one hint comment |
| `ls -A .claude-plugin` | `plugin.json` only — layout rule holds |
| `find . -type f` | `skills/frappe-operations/` is at the repository root alongside the others |
| `git status --porcelain` before starting | Empty — clean working tree; nothing pre-existing was staged or reverted |
| Working tree after the probes | No probe artifact, delegation workspace, or scratch file reached this repository |

Not verified: the skill under a live session — see Open question 3. Nothing in this phase
was run against a real Frappe site, by design.
