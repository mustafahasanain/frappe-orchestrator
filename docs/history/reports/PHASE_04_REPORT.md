# Phase 04 Report

> **`--mode test` is verified against the real Codex CLI**, closing the last unexercised
> mode — and the probe corrected a reason this repository had recorded as settled. See
> [Finding: what workspace-write actually refuses](#finding-what-workspace-write-actually-refuses).
>
> **Three containment gaps found, all now closed.** A bench command with no `--site`
> still acts on a site (closed in its own commit, under a Phase 01.5 amendment). The
> dispatcher's deny list had the same hole, so the two layers disagreed (closed by
> single-sourcing the rules, under a Phase 03 amendment). And underneath both, the
> delegated permission policy **was never reaching OpenCode at all** — see
> [Gap: the two layers disagreed, and neither was in force](#gap-the-two-layers-disagreed-and-neither-was-in-force).
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
- `config/command-boundaries.json`, `hooks/guard.py`, `scripts/delegate`,
  `tests/test_parser.py` — the mechanical rules moved into one data file that both
  consumers read, the drift test that fails by rule name, and the `WSLENV` fix that made
  the delegated permission policy actually reach the CLI. Authorised as a Phase 03 patch,
  contract amended, written up in the Phase 03 report.
- `docs/reports/PHASE_04_REPORT.md` — this report.

No helper script was written, and the Frappe operations skill itself ships prose with
nothing that fails silently. The tests added under the Phase 03 patch cover the shared
boundary data, which does fail silently — that is the whole reason it earned one. `config/`, `scripts/`, `.claude-plugin/`, and the phase documents were not
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

1. **Closed.** The dispatcher's deny list disagreed with the hook; the rules are now
   single-sourced and both engines are checked against them. What it uncovered is not
   closed and is not mine to decide: **a delegated OpenCode run executes in PowerShell**
   against `//wsl.localhost/...` UNC paths on this machine, where `bench` does not exist
   and `git status` fails on dubious ownership. Delegated implementation may not work here
   at all, and a run that cannot read the working tree still reports `status=completed`.
   That deserves its own look before the next delegated implement task.
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

## Gap: the two layers disagreed, and neither was in force

`scripts/delegate`'s `DENIED_BASH` is what holds a delegated **OpenCode** run inside the
same boundaries the hook enforces. After the hook commit, the two disagreed: `bench
migrate`, `clear-cache`, `install-app`, `backup`, `reinstall`, `trim-tables` and
`drop-site` asked when Claude ran them and were permitted when a delegated agent ran them.
A delegated run had wider access to live sites than the orchestrator.

Reported here as out of scope, then authorised as a Phase 03 patch, because the rule set
spans two phases' files and neither phase could fix it alone. **Not** by copying the
subcommand list into the dispatcher: the copy is the defect, and a third copy would agree
only until the next edit.

`config/command-boundaries.json` now holds the nine mechanical rules once. Both consumers
read it and each translates it into its own matching form. `tests/test_parser.py` fails by
rule name when either translation drops a rule, when the two disagree about one of its own
examples, or when the skill section a rule names does not exist. The full write-up, the
regression probes, and the live verification are in the Phase 03 report.

**And underneath it, the finding that matters more.** The verification asked for a
previously-permitted command to be refused. Nothing was refused — because the policy was
never delivered. `opencode debug config` resolved **zero** bash rules from it, not even
the `"*": "ask"` base, and a live delegated run executed `bench migrate` outright. The
`opencode` on this machine is the Windows build, and WSL forwards an environment variable
to a Windows process only if `WSLENV` names it; `OPENCODE_CONFIG_CONTENT` was being set in
an environment the CLI never saw. With `--auto` approving everything not explicitly
denied, and nothing denied, a delegated OpenCode run had unrestricted shell access.

So the divergence Phase 04 found was real but was not the live risk it appeared to be:
neither side of it was in force. Both are now. The fix is one variable
(`WSLENV=…:OPENCODE_CONFIG_CONTENT/w`), and the live run afterwards refuses `bench migrate`
by name with a hostile project config in place.

**Amended.** Everything in this section is true of the **Windows** OpenCode build, which is
what `opencode` resolved to when it was measured. A Linux `opencode` is now installed and
first on PATH, and it reads `OPENCODE_CONFIG_CONTENT` from the environment directly:
`WSLENV` set or unset, the resolved config is identical — 173 bash rules, base `"*": "ask"`,
zero `allow`, with a hostile project config in place. `WSLENV` is inert on this build. It is
kept anyway, because the Windows build is still installed and still second on PATH, and
there its absence is not a weakened policy but no policy at all. See the Phase 03 report for
the measurement, the decision, and its reasoning.

## The duplication map

Every rule that exists in more than one place, **after** the mechanical rules were
single-sourced. The map was produced first, then acted on for the rows that were pure
copies; what follows shows which rows collapsed and which are genuinely duplicated.

### Single-sourced (was: six rows of hand-maintained copies)

`config/command-boundaries.json` is now the only place these rules are written.
`hooks/guard.py` translates them into token matching, `scripts/delegate` into glob
patterns, and neither owns a rule.

| # | Rule | Source | Consumers | Kept in sync by |
| --- | --- | --- | --- | --- |
| 1 | Push is never automatic | `command-boundaries.json` rule `push` | hook (ask), delegated (deny) | `check_command_boundaries()`, by rule name |
| 2 | No blanket staging | rule `blanket-staging` | hook (deny), delegated (deny) | same |
| 3 | Live-site execution | rules `site-named`, `site-unnamed`, `database-client`, `frappe-connection` | hook (ask), delegated (deny except the snippet rule, which states why) | same, plus all 76 bench subcommands checked through both engines |
| 4 | Agent CLIs run through the dispatcher | rules `bare-agent-run`, `bare-agent-exec` | hook (deny) | same |
| 7 | The orchestrator owns the commit | rule `commit-inside-delegated-run` | delegated (deny); the hook deliberately does not, and says why | same |
| 5 | The dispatcher's own invocation — agents, modes, required arguments | `scripts/delegate` (`MODES`, `build_parser`, `REQUIRED_OUTSIDE_PARSER`) | `guard.py`'s bare-agent deny reason · `orchestration:231-234` · `--help` | `check_dispatcher_invocation()` — see below |

Three things are asserted that prose could not: that both translations catch each rule's
examples and leave its counter-examples alone, that the two engines agree wherever both
apply, and that a decision dropped to `null` carries a stated reason.

The rules are still *stated* in skill prose — that is the point of the hook existing at
all, since skill activation is stochastic — but the prose is no longer a copy that can
drift into being wrong about what is enforced: each rule names the skill section that
documents it, and the suite fails if that section disappears.

### Still genuinely duplicated

| # | Rule | Copies | Kept in sync by |
| --- | --- | --- | --- |
| 6 | Codex never implements | `orchestration:61,238` · `delegate:26` and its refusal message | nothing |
| 8 | BLOCKED is not a failed attempt | `orchestration:363-381` · `delegate` review contract text · `frappe-operations:211-221` (defers, does not restate) | nothing |
| 9 | Context and impact rules | `orchestration:181-205` (4 rules) · `skills/project-context/SKILL.md` (full) | nothing — deliberate, so the rules survive the second skill not loading |
| 10 | Deployment is refused, never performed | `orchestration:480-491,503` · `frappe-operations:11,190-192` · `templates/OPERATIONS.md:39` · `BUILD_CONTRACT.md:96,219-227` | nothing |
| 11 | A site is never guessed; dev site must be declared | `frappe-operations:123-148` · `orchestration:339-349` · `templates/OPERATIONS.md:11-14` · the `site-unnamed` rule's intent | the enforcement half is single-sourced; the guidance half is not |
| 12 | The bench subcommand set that resolves a site | `command-boundaries.json` · frappe's own CLI, from which it was derived | nothing — and unfixable here: the other copy is another project's source. The data records how to re-derive it |
| 13 | Which operations a diff requires | `frappe-operations:58-110` · each project's `docs/ai-context/OPERATIONS.md` | by design: the project overrides, and the skill says so |

### What is left, and what it would take

The remaining rows are of three kinds, and only one is a candidate for the same treatment:

- **Prose stating what a mechanism enforces** (5, 6, 8). These could be checked the way
  rule 3 now checks its skill sections — assert the sentence exists, not generate it. Row
  5 was the one with a live drift risk, because the hook's deny reason enumerates the
  dispatcher's modes and required arguments, and a mode added to `MODES` would not update
  that string. **Row 5 is now checked** — see below. Rows 6 and 8 are left as they were.
- **Deliberate redundancy** (9, 10, 11's guidance half). These exist because a skill may
  not load. Collapsing them would remove the property they were built for.
- **A copy of someone else's source** (12). Nothing in this repository can hold that in
  sync; the best available is the recorded derivation.

My recommendation, for what it is worth: row 5 is worth a check, the rest are not worth
touching. Rows 9 and 10 are load-bearing duplication and rows 12 and 13 are not really
duplication at all.

**Acted on.** Row 5 is checked; rows 9, 10 and 12 stay as they are, by decision rather
than by omission.

### Row 5, checked

Three places state how to invoke the dispatcher and none can be generated from it: the
hook's deny reason lives in a separate process with no reason to import the dispatcher,
the orchestration skill is prose, and `--help` is argparse's own. The prose stays
hand-written; what is enforced is that it still describes the dispatcher.

Two seams made that checkable. `build_parser()` lets the suite ask which arguments the
parser requires. `validate_invocation()` holds the agent/mode/model rules that were inline
in `main()`. `REQUIRED_OUTSIDE_PARSER` names `--cwd`, required by
`resolve_working_directory` rather than by argparse and otherwise invisible to
introspection — and the suite checks that declaration both ways, so it cannot become a
stale copy of itself.

`check_dispatcher_invocation()` fails when the hook's reason enumerates a different set of
agents or modes than the dispatcher accepts, when it omits a required argument, when a
skill invocation omits one, when a supported combination is undocumented, or when the
skill documents an invocation `validate_invocation()` would refuse. That last one is the
strongest form available here: the skill's lines are run through the same function a real
run goes through, so a documented-but-refused invocation fails as a test rather than as a
usage error one layer away from the mistake.

Five deliberate regressions confirm it fails loudly — a mode added to `MODES`, `--cwd`
dropped from the deny reason, `--tier` dropped from a skill line, the skill documenting
`codex --mode implement`, an agent dropped from the reason enumeration. Each fails by
name; the control passes. `hooks/guard.py` needed no change: its reason string was already
correct, and is now held that way.

The full write-up is in the Phase 03 report, where the dispatcher lives.

## OpenCode binary note

The `opencode` this phase and Phase 03 measured was the **Windows** build, reached from WSL
over `/mnt/c`. A Linux build is now installed, authenticated, and first on PATH:

```
/home/mustafa/.nvm/versions/node/v20.20.2/bin/opencode      1.18.21, ELF
/mnt/c/Users/…/AppData/Roaming/npm/opencode                 the Windows build
```

Three things change for this phase's record:

- **The `WSLENV` finding is build-specific.** The Linux binary receives the permission
  policy without it. Amended in place above.
- **The PowerShell/UNC observation is gone.** A delegated run now executes in `/bin/bash`
  on Linux, `bench` resolves to `/usr/local/bin/bench`, and `git` reads the work tree
  without the dubious-ownership refusal. That was an environment fact about the Windows
  build, not about the plugin — but it was the reason a delegated implementer could not run
  this project's own commands, and it no longer applies.
- **The delegated implement path now works end to end**, verified against the filesystem
  rather than the agent's report. It had never been exercised successfully before.

The re-runs are in the Phase 03 report, which is where the OpenCode findings were recorded.

**PATH order is the standing risk.** Both builds are installed. Nothing in this plugin
chooses between them, and a change of PATH order is silent — which is exactly how the
earlier findings came to be about a program nobody realised they were measuring. The
dispatcher now writes `agent_path` and `agent_real_path` into every `result.json` and every
`--dry-run`, so a run measured against the wrong build is visible in the record instead of
being reconstructed a phase later. The name alone does not settle it: nvm's `opencode` is a
symlink to a file called `opencode.exe` that is an ELF executable. Only the directory does.

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
| Boundary single-sourcing, drift probes, live deny run | See the Phase 03 report — 51 hook payloads unchanged, five regression probes, `bench migrate` refused live with a hostile project config in place |
| **Re-verified on the Linux OpenCode binary** | `OPENCODE_CONFIG_CONTENT` delivered natively (`WSLENV` set and unset are identical); hostile-config refusal re-run live, 5 refusals and a positive control; delegated implement run end to end, checked on disk. Full detail in the Phase 03 report |
| Row 5 checked | `check_dispatcher_invocation()`; five drift regressions each fail by name, control passes |
| `agent_path` in every result | Recorded and tested end to end against a stub CLI on a controlled PATH; four drift regressions fail by name |
| `python3 tests/test_parser.py`, after this patch | `38 cases, 3 timed, 8 strip, 9 boundary rules, mode matrix, invocation, agent path, adapters and --cwd checked` … `ok`, exit 0 |
| `git status --porcelain` before starting | Empty — clean working tree; nothing pre-existing was staged or reverted |
| Working tree after the probes | No probe artifact, delegation workspace, or scratch file reached this repository |

Not verified: the skill under a live session — see Open question 3. Nothing in this phase
was run against a real Frappe site, by design — and that is unchanged by the Linux binary
being reachable: a delegated run can now execute `bench`, and every bench subcommand that
resolves a site is denied inside one.
