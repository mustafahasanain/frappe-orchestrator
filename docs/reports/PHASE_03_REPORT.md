# Phase 03 Report

## What was built

- `scripts/delegate` — the delegation dispatcher. One executable that runs either agent
  CLI against the current repository: resolves model/effort/timeout from the routing
  file, enforces the agent/mode matrix, creates a temporary workspace outside the
  repository, delivers the brief with an appended output contract, applies the delegated
  OpenCode permission policy, runs the CLI with a timeout, and emits a structured result.
  It contains no task, model, or review decisions. Adapters are two functions inside it.
- `config/model-routing.json` — three additive changes: a top-level `models` map giving
  each model an `executor` and, where delegated, a provider CLI `id`; `timeout_seconds`
  per tier; no change to `tiers`, `escalation_ladder`, or `special_models` beyond the
  added timeout field.
- `skills/orchestration/SKILL.md` — integration edits: workflow diagram now carries the
  environment-operations slot, diff re-inspection, and the three-way review outcome; new
  `### Who implements` (executor rule); `## Delegation` replaces `## Delegation briefs`
  and adds the dispatcher command, brief rules, and how to read a result; new
  `## The actual diff is authoritative`, `## Environment operations`, `## Review
  outcome` (with BLOCKED triage), and `## Tests` (verification depth, TEST-mode gate,
  durable vs temporary); fix loop gains the re-review rule and the `claude`-executor
  case; commit safety gains the pre-commit cleanup checklist.
- `skills/project-context/SKILL.md` — two sentence-level edits where the text deferred to
  "once the Phase 03 dispatcher exists". It exists.
- `docs/reports/PHASE_03_REPORT.md` — this report.

`hooks/`, `.claude-plugin/`, and the phase documents were not touched.

## Spec coverage

| Requirement (Phase 03) | Status | Note |
| --- | --- | --- |
| One dispatcher invokes both OpenCode and Codex | Implemented | `scripts/delegate`, `--agent` |
| Agent-specific CLI behaviour isolated in small adapters | Implemented | `adapt_opencode`, `adapt_codex`; nothing agent-specific outside them |
| Dispatcher handles CLI selection, cwd, brief delivery, model, effort, mode, timeout, exit status, structured result, missing-CLI detection, execution errors | Implemented | All present; effort is passed to OpenCode only — see Decisions |
| Dispatcher contains no planning, architecture, routing intelligence, regression reasoning, documentation logic, or commit decisions | Implemented | It reads routing values by key; it selects none of them |
| Temporary delegation workspace outside the repository | Implemented | `mkdtemp` under the system temp dir; `brief.md`, `agent-output.txt`, `agent-stderr.txt`, `result.json` |
| Agents share code through the Git working tree | Implemented | Brief carries no source; `cwd` is the repository |
| Concise brief contract | Implemented | `## Delegation → Briefs` in the skill |
| Implementation result contract (status, agent, model, summary, touched_files, commands_run, tests_run, warnings, exit_code) | Implemented | Split across dispatcher-observed top level and `agent_report` — see Decisions |
| Implementation result never means verification | Implemented | Structural: separate keys, and stated in the contract text the dispatcher appends and in the skill |
| Actual diff is authoritative; compare task + impact + result + diff | Implemented | `## The actual diff is authoritative` |
| Codex REVIEW mode, read-only toward production code | Implemented | `--sandbox read-only` |
| Codex REVIEW also covers Phase 02 onboarding analysis | Implemented | Context skill edit; same mode |
| Codex TEST mode, tests only | Implemented | `--sandbox workspace-write`; the "tests only, never production code" rule is contract text, not sandbox-enforced — see Limitations |
| REVIEW → TEST decision, not automatic for every task | Implemented | `## Tests` |
| PASS / FAIL / BLOCKED, exactly three states | Implemented | Review contract and `## Review outcome` |
| blocking / non_blocking findings only | Implemented | Same |
| Blocking findings drive the fix loop; non-blocking do not | Implemented | Same |
| BLOCKED is not an implementation failure; safe-local vs unsafe-external triage | Implemented | `### Handling BLOCKED` |
| Fix loop applies Phase 01's ladder without redefining it | Implemented | Phase 01 section kept; Phase 03 adds re-review-against-current-diff and the `claude`-executor case |
| Timeout support, classification-aware, centrally configurable | Implemented | `timeout_seconds` per tier |
| Timeout → BLOCKED with `blocker_reason`, not FAIL | Implemented | Verified with a stub |
| No background services, queues, daemons, task databases | Implemented | `subprocess` with a timeout; nothing else |
| Targeted quality gates, scope follows impact | Implemented | `## Tests`; selection strategy stays in the Phase 02 skill |
| Durable vs temporary tests; Claude decides persistence | Implemented | `## Tests` |
| Documentation / AI context update gate | Implemented | Already in the workflow and the Phase 02 skill; diagram updated |
| Pre-commit cleanup checklist | Implemented | `## Commit safety` |
| Task-owned staging only; no `git add .` | Implemented | Kept from Phase 01; now also denied inside delegated runs |
| Git push stays outside the automatic workflow | Implemented | Kept from Phase 01; now also denied inside delegated runs |
| Environment-operations slot opened, Frappe logic not implemented | Implemented | `## Environment operations`, explicitly a no-op |
| Reuses `config/model-routing.json`; no second routing mechanism | Implemented | The dispatcher reads that file and nothing else |
| Guarantees 1–21 | Implemented | Each maps to a row above; 6, 7, 10, 18, 19 have residual gaps recorded under Limitations |
| Review loop verified against the real Codex CLI | **Deferred** | Codex is not installed on this machine. See Limitations |
| Frappe operational commands | Deferred | Phase 04 owns them |

## Decisions I made

- **`executor` lives on the model, not on each tier and ladder entry.** You asked for it
  per routing entry. `Kimi K2.7 Code` appears in four entries and `Claude Sonnet 5` in
  two, so per-entry would reintroduce exactly the drift problem the `models` map was
  created to remove. It is still explicit data in the routing file and never inferred
  from a name, which was the stated requirement. A rename that misses the `models` map
  fails loudly — the dispatcher refuses with "unknown model" and lists the valid names —
  rather than silently guessing. Say the word and I will move it per-entry.
- **`--model` is a display name, resolved by the dispatcher.** Claude passes the same
  name it prints in the preamble; the dispatcher looks up the provider id. One lookup
  point, and an unfilled placeholder fails with a clear message instead of reaching the
  CLI as a bogus id.
- **`--model` is rejected for Codex.** Codex is unpinned, so accepting a flag that does
  nothing would be a second, silent semantic for the same option. When you want Codex
  pinned it is a one-line change.
- **Adapters are two functions in `scripts/delegate`, not `scripts/adapters/`.** Your
  approval, and it matches the contract's "fewer files is better" and the phase's "the
  dispatcher may contain minimal agent-specific adapters".
- **Result shape separates observation from claim.** Dispatcher-observed facts are at the
  top level; the agent's own account is nested under `agent_report`. The spec lists these
  as one flat set, but flattening would put the agent's `status` next to the dispatcher's
  and invite exactly the conflation the phase spends a section warning against.
- **Both CLIs are run with `cwd` set rather than `-C` / `--dir`.** One mechanism, two
  fewer flags to get wrong.
- **Effort is passed to OpenCode only** (`--variant`). Codex's effort flag is not
  something I could verify without the CLI installed, and I would rather omit a flag than
  guess one.
- **`git commit*` is in the delegated deny set**, beyond the three rules `guard.py`
  enforces. The orchestrator creates the commit after review passes; an implementer that
  commits mid-run bypasses diff inspection and the cleanup checklist.
- **`"*": "ask"` is the permission base, not `"allow"`.** If `--auto` is ever absent or
  ineffective, the failure mode is a run that stalls, not a run that does anything.
- **Timeouts:** FAST 180 s, SMALL 420 s, NORMAL 900 s, DIFFICULT 1800 s. NORMAL and
  DIFFICULT exceed the foreground command limit, so the skill instructs backgrounding for
  those tiers and the dispatcher prints its workspace path to stderr immediately so a cut
  short run is still recoverable.
- **The dispatcher exits 0 whenever it produced a result**, including failed, timed out,
  and missing-CLI runs; exit 2 means the invocation was wrong. The result is the product,
  and `status` carries the outcome.

## Deviations

- **`executor` on the model rather than per routing entry** — see Decisions. Deviates
  from the literal instruction; the stated requirement (explicit in the file, never
  inferred from the name) holds.
- **The illustrative `adapters/` directory in the phase document was not created.** The
  phase permits adjusting exact names and says the dispatcher may contain the adapters.

## Delegated-agent permissions — how the boundary is held

A delegated agent runs its own shell commands inside its own process, where the
Phase 01.5 `PreToolUse` hook cannot see them. Without something else, every boundary
Phase 01.5 enforces would lapse the moment work is delegated.

**Mechanism.** OpenCode has a permission system with per-command-pattern rules and `deny`
as a first-class outcome (verified against the published schema at
`https://opencode.ai/config.json`: `permission.bash` accepts `{pattern: ask|allow|deny}`).
The CLI's own help for `--auto` reads "auto-approve permissions that are not explicitly
denied", and the docs state that explicit `deny` rules remain enforced in auto mode.

**Delivery.** The dispatcher sets `OPENCODE_CONFIG_CONTENT` in the child environment only.
Nothing is written to the target repository and the user's own config is untouched. That
variable is the highest-precedence ordinary config layer — above a project's own
`opencode.json`, unlike `OPENCODE_CONFIG`, which sits below it.

**Finding B — the bypass that would have been missed.** Agent-level permissions resolve
separately from top-level ones and take precedence. With only a top-level `permission`
set, a project's `agent.build.permission.bash: {"git push*": "allow"}` survived
completely untouched — the config would have looked correct and been inert. The
dispatcher therefore writes the rules at **both** levels and pins `--agent build` so a
project cannot redirect the run to a primary agent with looser permissions.

Verified with `opencode debug config`, which resolves configuration with no model calls,
against a deliberately hostile project `opencode.json` setting `"*": "allow"`,
`"git push*": "allow"`, `"bench --site*": "allow"`, and `"git commit*": "allow"` at both
levels. Resolved result: 23 rules at each level, `*` → `ask`, every denied pattern →
`deny`, and no `allow` remaining anywhere in the `build` agent's bash rules.

Denied families: `git push`, `git commit`, blanket `git add`, and live-site execution
(`bench console` / `mariadb` / `execute`, any `bench --site`, `mysql`, `mariadb`).

**Codex** needs no equivalent: `read-only` cannot write or run commands, and
`workspace-write` is confined to the working tree with no network access, so a push from
inside a TEST run fails structurally.

## Limitations — named, not solved

1. **Runtime enforcement of `deny` under `--auto` is documented, not executed here.** I
   verified rule *resolution*. Proving a denied command is actually refused needs a real
   model call. One command settles it:

   ```
   OPENCODE_CONFIG_CONTENT="$(echo x | scripts/delegate --agent opencode --mode implement \
     --tier SMALL --model 'GLM-5.2' --dry-run \
     | python3 -c 'import json,sys; print(json.load(sys.stdin)["env_overrides"]["OPENCODE_CONFIG_CONTENT"])')" \
     opencode run --agent build --auto "run this command and report the result: git push --dry-run"
   ```

2. **Pattern matching against chained commands is unverified.** The docs say bash
   patterns match "parsed commands" but show no example with `&&`, `;`, or a pipe.
   `guard.py` splits on separators; OpenCode's parser is its own. A `git push` buried in
   a compound command may or may not match.
3. **The same rules now exist in three places** — skill prose, `hooks/guard.py`, and
   `scripts/delegate` — in three different matching engines, with nothing keeping them in
   sync. Phase 01.5 recorded this cost for two; it is three now.
4. **Codex TEST mode can still commit.** `workspace-write` blocks the network but permits
   local writes, including to `.git`. Codex has an execpolicy `.rules` mechanism — the
   presence of `--ignore-rules` implies it — but Codex is not installed, so I did not
   write that file blind. That is the path to closing this.
5. **The review loop is unverified against the real Codex CLI.** Codex is not installed on
   this machine. The adapter was built from source-verified flags (`codex exec`;
   `-m/--model`, `-C/--cd`, `-s/--sandbox` confirmed in `SharedCliOptions`; sandbox values
   and `-` for stdin confirmed in the non-interactive docs) and exercised only with stubs.
   Stub coverage is not CLI coverage. The whole Codex half of this phase — REVIEW, TEST,
   and every PASS/FAIL/BLOCKED path that depends on a real verdict — needs a live run
   before it can be called working. `--dry-run` prints the exact argv to check against
   `codex exec --help` once it is installed.
6. **`opencode run` output parsing is unverified against real output.** The dispatcher
   extracts the last fenced JSON block from stdout. If OpenCode's default formatting wraps
   or decorates that block, extraction degrades to `result_block: "missing"` with the
   transcript path — honest failure, not a crash, but it means no structured report.

## Hook implications — for your decision, not implemented

`hooks/` was not touched. Two command shapes now exist that the hook could guard:

- **`delegate` invocations themselves.** The dispatcher already refuses the dangerous
  combinations (`--agent codex --mode implement`, delegating a `claude`-executor model,
  an unfilled model id) with exit 2. A hook rule would be defence in depth against a
  future edit that loosens the dispatcher, not new coverage today.
- **Bypassing the dispatcher.** Nothing stops a direct `opencode run …` or `codex exec …`
  typed as an ordinary Bash command, which would carry none of the permission policy. A
  `PreToolUse` rule that asks on bare `opencode`/`codex` invocations would close that, and
  it is the gap I would close first.

Also worth a decision: `--cwd` is not constrained to the current repository.

## Open questions

1. **Model ids.** Three entries still hold `<supply provider id>`: `Kimi K2.6`,
   `Kimi K2.7 Code`, and `Kimi K3`. `GLM-5.2` is filled in as `opencode/glm-5.2`.
   `Claude Sonnet 5` and `Claude Opus` are `executor: "claude"` and correctly have no id.
   The dispatcher refuses to delegate to a model whose id is still a placeholder.
2. **OpenCode effort values.** Effort is passed as `--variant low|medium|high`. Variant
   names are provider-specific; confirm your provider accepts those three, or tell me what
   to map them to.
3. **Pinning Codex to a model.** No reviewer entry exists in the routing file and `--model`
   is currently rejected for Codex. If you want it pinned, it needs a `models` entry and
   two lines in the adapter.
4. **Live-run verification.** Every phase so far has needed a real session before anything
   could be called working, and this one adds two external CLIs. Worth testing first: a
   FAST delegated task end to end, and a denied `git push` inside a delegated run.

## Not built (correctly out of scope)

- Frappe operational commands and the logic that selects them — Phase 04. This phase only
  opens the slot and marks it a no-op.
- Background services, queues, daemons, watchdogs, schedulers, persistent task databases,
  permanent task logs, token accounting, agent conversation archives — forbidden by the
  contract and the phase document.
- A generic agent framework or a third adapter. Two agents, two functions.
- A second routing mechanism. The dispatcher reads `config/model-routing.json` and nothing
  else.
- Any change to `hooks/` — excluded by your instruction; implications reported above.
- A Codex `.rules` execpolicy file — not written blind while the CLI is absent.
- Deployment, remote operations, infrastructure or server state, `git push` automation —
  permanently out of scope for every phase.

## Verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `claude plugin validate skills --strict` | `✔ Validation passed` (exit 0) |
| `python3 -c "json.load(...)"` on `config/model-routing.json` | valid; `models` has 6 entries |
| `ast.parse` on `scripts/delegate` | parses |
| Refusal matrix, 6 cases | `codex --mode implement`, `opencode --mode review`, delegating `Claude Sonnet 5`, placeholder id, unknown model, `--model` with codex — all refused, exit 2, each with a corrective message |
| `--dry-run`, codex review | `['codex','exec','--sandbox','read-only','-']`, brief on stdin, timeout 900 |
| `--dry-run`, codex test | `['codex','exec','--sandbox','workspace-write','-']`, timeout 1800 |
| `--dry-run`, opencode implement | `['opencode','run','--agent','build','--auto','--model','opencode/glm-5.2','--variant','low',<brief>]`, timeout 420, 23 bash rules at both levels |
| `opencode debug config` vs. hostile project config | Without the override: `*` → `allow`, `git push*` → `allow` (bypass reproduced). With it: `*` → `ask`, all denied patterns → `deny`, at top level and on `agent.build`; no `allow` left |
| Stub: well-formed result | `status=completed`, `exit_code=0`, `result_block=present`, `agent_report` parsed |
| Stub: missing JSON block | `status=completed`, `result_block=missing`, `agent_report=null` |
| Stub: malformed JSON block | `status=completed`, `result_block=invalid`, `agent_report=null` |
| Stub: non-zero exit | `status=failed`, `exit_code=3` |
| Stub: timeout, implement | `status=timeout`, `blocker_reason=timeout`, process killed |
| Stub: timeout, review | `status=timeout`, `blocker_reason=timeout`, `verdict=BLOCKED` |
| Real `codex` absent | `status=cli_missing`, `error="codex is not installed or not on PATH. Nothing was run."` |
| Workspace inspection | `/tmp/delegate-opencode-implement-*` containing `brief.md`, `agent-output.txt`, `agent-stderr.txt`, `result.json`; brief carries the appended output contract |
| `git status --porcelain` after all runs | Only the four intended files. No delegation artifact reached the repository |
| `git ls-files -s scripts/delegate` | `100755` — exec bit recorded |
| `ls -A .claude-plugin` | `plugin.json` only — layout rule holds |
| `git status --porcelain` before starting | Empty |

Not verified: anything requiring a real model call — see Limitations 1, 5, and 6.

## Patch: model ids and variant tolerance

Two changes after the phase commit. Open question 1 is closed; open question 2 is not, and
the dispatcher was changed to behave honestly while it stays open.

### Model ids

The three placeholders in the `models` map were replaced with ids confirmed from
`opencode models`:

| Model | id | executor |
| --- | --- | --- |
| Kimi K2.6 | `opencode/kimi-k2.6` | opencode |
| Kimi K2.7 Code | `opencode/kimi-k2.7-code` | opencode |
| Kimi K3 | `opencode/kimi-k3` | opencode |
| GLM-5.2 | `opencode/glm-5.2` | opencode |
| Claude Sonnet 5 | — | claude |
| Claude Opus | — | claude |

No placeholders remain, and the two `claude`-executor models correctly still have no id.
The routing file diff is three lines.

### Variant values are still unverified

`opencode run --help` describes `--variant` as "model variant (provider-specific reasoning
effort, e.g., high, max, minimal)". Those examples are not the `low` / `medium` / `high`
the routing file's `effort` uses, and the accepted set is provider-specific. It cannot be
settled without a real model call, so it stays unverified here.

The dispatcher was made tolerant rather than confident. No list of accepted variants was
hardcoded — that would be guessing at provider behaviour, and would go stale silently.

**Pass-through.** If an effort value is present it is passed as `--variant <value>`,
unchanged. `--effort ''` omits the flag entirely, which is the escape hatch and the
discriminating test. `--effort` now distinguishes "not given" (fall back to the tier's
effort) from "given as empty" (omit the flag); previously an empty value fell through to
the tier default.

**Surfacing a rejection.** `--variant` is the only argument the dispatcher passes whose
accepted values are unverified; every other flag was confirmed against the CLI's own help
or source. A CLI that rejects an argument exits before producing any output, so that
combination — non-zero exit, empty stdout, and a `--variant` in the argv — is reported as
`status: "usage_error"` instead of a generic `failed`, with an error naming the exact
variant value, the re-run that isolates it, and the CLI's stderr.

The signal is structural, not text matching, so it does not encode any assumption about
how a particular CLI words its errors. It is also not a certainty: a startup failure with
no output and an argument rejection look alike from outside the process. The message says
so and gives the test that separates them rather than asserting a cause. An agent that
ran and then failed produces output, so it stays a plain `failed`.

Once the accepted values are known, the fix is a value change in `config/model-routing.json`
and nothing in the dispatcher.

### Patch verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `python3 -c "json.load(...)"` on the routing file | valid |
| `git diff` on the routing file | 3 insertions, 3 deletions — the id values only |
| All four delegated models, `--dry-run` | Each resolves to its id; no placeholder refusal remains |
| Stub rejects `--variant` (non-zero, empty stdout) | `status=usage_error`, error names `--variant low`, the `--effort ''` re-run, and the stderr |
| Stub fails after producing output | `status=failed`, `exit_code=3` — unchanged, not reclassified |
| Same rejection with `--effort ''` | `status=failed` — with no variant passed, the variant cannot be the cause, and it is not blamed |
| `--effort ''` vs. default, `--dry-run` | `--variant` absent and present respectively |
| Refusal matrix, 5 cases | All still exit 2 |
| Codex review via stub | `status=completed`, `result_block=present`, `verdict=PASS`, argv `['codex','exec','--sandbox','read-only','-']` |
| Real `codex` absent | `status=cli_missing` — unchanged |

Still not verified: which `--variant` values the provider accepts, and everything in
Limitations 1, 5, and 6 above.
