# Phase 03 Report

> **Safety finding from the first end-to-end run.** A delegated Codex run attempted
> `bench --site masa.local run-tests`, which nothing in its brief had asked for, and the
> dispatcher's sandbox stopped it before it reached the site. It is the first time an
> agent has reached past its brief here. Recorded in full under
> [Safety finding: a delegated agent reached past its brief](#safety-finding-a-delegated-agent-reached-past-its-brief).
>
> **Runtime enforcement is now verified, and it found a second defect.** `deny` holds
> against a live delegated run, including one whose project config tries to allow
> everything. The verification also found that `--cwd` was silently ignored for OpenCode,
> so delegated runs operated on the orchestrator's own directory instead of the one
> requested — see
> [Patch: deny enforcement verified at runtime](#patch-deny-enforcement-verified-at-runtime-and-a-working-directory-defect-it-exposed).

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
- **Onboarding runs in its own `onboard` mode, not REVIEW.** Both phase documents specify
  REVIEW for it. Deviated on your instruction after the end-to-end run; the reasoning and
  the exact wording deviated from are under
  [Deviation from the phase documents](#deviation-from-the-phase-documents).

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

> Partly wrong, and left as written because it records what was believed here.
> `read-only` does run commands; what it denies is reach. Corrected under
> [Safety finding](#correction-read-only-does-execute-commands), where a live run proved
> it. The conclusion — no OpenCode-style permission map is needed for Codex — still
> holds.
>
> The second half is wrong too, in the other direction. "No network access" does not
> describe what the sandbox refuses: a network namespace leaves unix sockets untouched,
> and a Frappe database is reachable over one. Measured in Phase 04, the sandbox is
> *stronger* than this claim and for a different reason — see
> [Correction: what the Codex sandbox refuses, and why](#correction-what-the-codex-sandbox-refuses-and-why).

## Limitations — named, not solved

1. **Runtime enforcement of `deny` under `--auto` is documented, not executed here.** I
   verified rule *resolution*. Proving a denied command is actually refused needs a real
   model call. One command settles it:

   > **Closed.** Nine live denied attempts across two rounds, all refused, one of them
   > against a project config allowing everything at both levels. See
   > [Patch: deny enforcement verified at runtime](#patch-deny-enforcement-verified-at-runtime-and-a-working-directory-defect-it-exposed).

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

   > **Closed.** Six live implement-mode runs, `result_block=present` in all six. The
   > fence-free parser built for Codex handled OpenCode's shape too, which was unobserved
   > when that decision was made.

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

> Worse than unconstrained, as it turned out: it was not honoured at all for OpenCode.
> Fixed and verified in
> [Patch: deny enforcement verified at runtime](#patch-deny-enforcement-verified-at-runtime-and-a-working-directory-defect-it-exposed).
> Constraining it remains an open decision.

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
5. **Whether debate gets a mode.** It is the one remaining non-review use of a delegated
   agent and it has no mode, so the only way to delegate a round today would be to run it
   as a review — the defect just fixed for onboarding. The skill now forbids that and
   routes an unresolved disagreement to you instead, which leaves debate undelegatable
   rather than unsafe. Building a `debate` mode means designing a contract for a feature
   that has never been exercised, so it is your call. See
   [The other non-review uses, named](#the-other-non-review-uses-named).

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

## Patch: Codex verified live, result parser rebuilt

Limitation 5 is closed. Codex 0.149.0 is installed, and the review path was exercised
against the real CLI four times in this repository, not against stubs. The runs found a
real defect in the parser that no stub had caught.

### What the real CLI does

`codex exec --sandbox read-only` ran correctly from the dispatcher. Every flag the adapter
was built on is confirmed present in `codex exec --help`: `-m/--model`, `-s/--sandbox`,
`-C/--cd`, `-o/--output-last-message`, `--json`, `--skip-git-repo-check`.

**The stream split is not what it looks like in a terminal.** The banner (`workdir`,
`model`, `provider`, `approval`, `sandbox`, `reasoning effort`, `session id`), the prompt
echo, a second rendering of the answer, and the `tokens used` footer all go to **stderr**.
stdout carried only the final agent message — 246 bytes on the first run, the fenced block
and nothing else. Grepping stdout for any banner or footer text returns zero matches. What
looks like one interleaved stream is two streams rendered together by the terminal; under
the dispatcher's separate pipes they do not mix.

So the build assumption ("final message on stdout") held. The parser was hardened anyway,
because one CLI version and one prompt shape is not a guarantee.

**Observed default model: `gpt-5.6-sol`,** with `reasoning effort: high`. Codex stays
unpinned as decided. Recorded here so a change of default is noticeable — it appears in
the banner on stderr of every run, and is kept in each workspace's `agent-stderr.txt`.

### The defect the live runs found

Run 4 returned `result_block: "invalid"` on a perfectly well-formed report. The cause was
in the parser, not the CLI: the report's own `detail` string contained the text
```` ```json ````, and a non-greedy regex delimiting a block on ``` truncates the body at
that inner fence, leaving unparseable JSON.

This is not an edge case. It is what happens whenever an agent reviews code that contains
fenced blocks, or explains a fence in its own findings — which is precisely what a reviewer
of this repository does. No stub produced it because every stub emitted tidy output.

**Fences are no longer parsed at all.** Extraction is `json.JSONDecoder().raw_decode`
scanning for balanced objects, which consumes strings correctly whatever they contain. The
last object carrying one of `RESULT_KEYS` wins — last because the contract asks for the
block last, and the key requirement because otherwise echoed config or log JSON would be
handed back as if the agent had written it. `invalid` now means a fence appears somewhere
so the agent tried and the answer was unusable; `missing` means there was nothing to
salvage. `import re` is gone from the dispatcher.

Removing fence parsing also removed a whole class of defects rather than patching them one
at a time: info strings with dots or spaces, unterminated fences, and objects nested in
fenced arrays are no longer parsing concerns because no fence is parsed.

### The fix loop ran, and it was bounded

The review of the parser change went through the full ladder. Attempts were made against
the real Codex CLI, and each re-review ran against the current actual diff.

| Attempt | Verdict | Blocking findings | Outcome |
| --- | --- | --- | --- |
| 1 | FAIL | 3 | Two fixed; one declined |
| 2 | FAIL | 2 | Both fixed by simplifying the selection rule |
| 3 | FAIL | 1 | See below |

The declined finding was attempt 1's first: that a truncated bare `{"verdict":` should
report `invalid` rather than `missing`. Both states lead the orchestrator to read the
transcript, so nothing behavioural turned on it. Rather than change the code I defined the
states explicitly in the docstring so the rule is stated rather than inferred. The
declined finding and the reason are recorded here because a declined blocking finding
should be visible, not silent.

**Attempt 3 was the last.** Phase 01 allows no automatic fourth attempt, and none was
made. Attempt 3's finding concerned fence info strings and unterminated fences leaking
into the fallback — both real against the code as it then stood. They are resolved not by
a fourth review round but by the rebuild above, which deletes the fence parsing they were
about. That rebuild came from reading run 4's actual output myself, not from another
delegated review.

**The final state has therefore not been reviewed by Codex.** That is the honest position:
three attempts were spent, the bound held, and the last change is verified by tests rather
than by review. Re-reviewing it is the recommended first action, and it is now a one
command job.

### What is still untested

- **The final parser has no Codex review**, for the reason above.
- **`--mode test` against the real CLI.** `workspace-write` was exercised only through a
  stub. Codex has not actually written a test file through the dispatcher.
- **The implement path against the real OpenCode CLI.** Limitation 6 stands unchanged:
  OpenCode's real stdout shape is still unobserved, and its stubs are a guess at it. The
  Codex lesson applies directly — the stub was tidier than reality, and that is what hid
  the defect.
- **Deny enforcement under `--auto` at runtime.** Limitation 1, unchanged.
- **Accepted `--variant` values.** Unchanged.
- **No automated test protects the parser.** 18 cases were run by hand this session,
  including both captured real outputs. This repository has no test infrastructure and
  Phase 03's allowed file list does not include creating one, so nothing was added. Worth
  a decision: the parser is now the component most likely to break silently, and the two
  real captures are exactly the fixtures a test would need.

### Patch verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `codex --version` | `codex-cli 0.149.0` |
| `codex exec --help` | `-m/--model`, `-s/--sandbox`, `-C/--cd`, `-o/--output-last-message`, `--json`, `--skip-git-repo-check` all present as built |
| Live review run 1, trivial docstring diff | `status=completed`, `exit_code=0`, 19.5 s, `result_block=present`, `verdict=PASS` |
| Live review runs 2–4, real parser diff, NORMAL tier | `status=completed` each; 178.5 s, 186.0 s, 257.3 s; all within the 900 s tier timeout |
| stdout vs stderr separation | stdout 246 B (block only); stderr 11,393 B (banner, prompt echo, answer, footer). Zero banner/footer matches in stdout |
| Parser suite, 18 cases | 18/18. Includes both captured real outputs, backticks and braces inside string values, multiword info strings, unterminated fences, config/log JSON rejected as `missing`, config JSON followed by a real report accepted |
| Stub suite, 12 cases | All as designed. Stubs rewritten to mirror the real stream split, plus a `decorated` mode putting everything on one stream and a `backticks` mode reproducing the run-4 defect |
| Refusal matrix, 3 cases | exit 2, unchanged |
| `cli_missing` with `PATH` stripped | Still fires correctly now that codex is genuinely installed |
| Repository working tree | Only `scripts/delegate` modified; the probe diff used for run 1 was reverted, and no delegation artifact reached the repository |

## Patch: parser reviewed to the attempt bound, and tested

The previous patch left the rebuilt parser unreviewed. That is now closed: it went through
a full review loop against the real Codex CLI, which reached the three-attempt bound
without a PASS. Minimal test infrastructure was then added, under a contract amendment.

### On stdout and stderr, recorded so it is not re-assumed

The banner, prompt echo, answer, and `tokens used` footer that appear to be on stdout are
on **stderr**. stdout carries the final agent message only — 246 bytes on the clean run.

Worth stating as a rule rather than a fact about one CLI: **what a terminal shows is not
evidence of what a pipe receives.** A terminal renders both streams into one scrollback
with no marker of which is which, so reading it as a single stream is the natural mistake,
and it survives because it is almost never tested directly. The check is one command —
redirect the streams to separate files and look at each — and it takes a few seconds. It
was worth doing here: the assumption was wrong in the other direction, and correcting it
was what pointed at the actual defect.

### The review loop, run properly and bounded

Three attempts, every one against the real CLI, each re-review against the current diff.

| Attempt | Verdict | Blocking | What happened |
| --- | --- | --- | --- |
| 1 | FAIL | 4 | RecursionError escaping; single-key false positives; O(n) per candidate; nested reports skipped. All four reproduced first, then fixed |
| 2 | FAIL | 2 | Key counting still admitted generic pairs; the attempt cap bounded candidates but not cumulative cost. Both reproduced, then fixed |
| 3 | FAIL | 1 | The discriminator alone still admits `{"status":"completed","operation":"session"}`. Reproduced; **not fixed** |

Every finding was reproduced against the code before being accepted. Two measurements
worth keeping:

- Attempt 1's runtime finding was real but its stated cause was not the whole story. A
  failed `raw_decode` builds a `JSONDecodeError`, and that counts newlines from offset
  zero to the failure point. Scanning backwards means large offsets, so the cost was
  O(n) *per candidate*. Decoding from a bounded slice made it constant: 1,000,000
  candidates went from >30s to 0.08s.
- Attempt 2's finding showed a candidate cap does not bound cumulative work. A wall-clock
  budget does. Compact hostile nesting went from 24.95s to exactly the 5s budget.

**Attempt 3 is where it stopped.** Phase 01 allows no automatic fourth attempt and none
was made.

The surviving finding is real and reproduced. It was not fixed because the obvious
one-line tightening does not close it: also requiring `summary` still admits
`{"verdict":"PASS","summary":"x","rule":"transport"}`. Each round has narrowed the
heuristic and each round has found the next object that satisfies it, which is the
signature of a problem that successive key checks cannot terminate.

**Root cause.** Identifying "the agent's report" inside arbitrary text is inherently
heuristic. Three rounds tightened it from *any fenced JSON* to *two contract keys* to *the
contract's own enumerated discriminator*, and a counterexample survived each time.

**Recommended next action, and it is a design change rather than another round.** Stop
guessing. Have the dispatcher generate a random token per run, put it in the brief as the
delimiter the agent must wrap its report in, and extract by that token. Identification
becomes exact, no CLI output can collide with it, and the whole class disappears rather
than being narrowed again. That is a change to the brief contract as well as the parser,
so it is your call, not something to slip in here.

The current parser is safe in the meantime: it fails closed, is bounded three ways, does
not raise on any input tried, and its failure mode is a report the orchestrator can see is
wrong rather than a silent substitution.

### Contract amendment

`docs/BUILD_CONTRACT.md` gained a `## Testing` section: `tests/` is allowed at the
repository root with fixtures under `tests/fixtures/`, nothing there loads at runtime,
tests are for components that fail silently, and the harness stays framework-free. It
records the precedent explicitly — a phase needing a file class no phase allows amends the
contract first and records it in its report, the same route Phase 01.5 took for the hook
rule Phase 03 could not add itself.

### Test infrastructure

**`python3 tests/test_parser.py`** — one command, standard library only, nothing to
install. Exits non-zero on failure.

- `tests/test_parser.py` — 29 cases and 3 timed bounds, covering the parser only.
- `tests/fixtures/codex-review-clean.txt` — real captured stdout from `codex exec`.
- `tests/fixtures/codex-review-inner-fence.txt` — the real output that broke the fence
  parser. Its own `detail` string contains a fenced example, which is what a reviewer of
  this repository naturally produces. Kept as a fixture because an invented sample would
  not have contained it — the defect survived precisely because every stub was tidier
  than reality.

The two findings from attempt 3 are encoded as `KNOWN_GAPS`: they run, they are printed as
documented gaps rather than counted as passes, and if one starts behaving differently the
suite says so. A known defect asserted as correct behaviour would be worse than no test.

`scripts/delegate` gained a standard `if __name__ == "__main__":` guard so the module can
be imported without executing. That is the only change to it in this patch that is not the
parser.

### Patch verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `python3 tests/test_parser.py` | `29 cases, 3 timed` … `ok`, exit 0, 10.2s (dominated by the 5s hostile-input budget) |
| Suite catches a real regression | The historical fence regex was reinjected: 16 failures including both real fixtures, exit 1, and the known-gap tracker flagged the change. Restored, green again |
| Live review attempts 1–3 | `status=completed` each; 344.5 s, 400.9 s, 155.5 s; all within the 900 s NORMAL timeout |
| All 7 findings reproduced before fixing | Each demonstrated against the code; attempt 3's two probes reproduced and left in place as `KNOWN_GAPS` |
| Runtime bounds | 1,000,000 candidates 0.12 s; compact hostile nesting 5.00 s (the budget); hostile input with a real report at the end under 1 ms |
| Stub suite | opencode good/noblock/invalid and codex real/backticks all as designed |
| Hook regression | `opencode run` deny, `codex exec` deny, `opencode models` pass-through, `git add .` deny |
| Working tree | `.gitignore` gained `__pycache__/`; no bytecode or delegation artifact committed |

Still untested, unchanged from the previous patch: `--mode test` against the real CLI, the
implement path against the real OpenCode CLI (Limitation 6 — its stdout shape is still
unobserved, and the Codex lesson applies to it directly), deny enforcement under `--auto`
at runtime, and the accepted `--variant` values.

## Patch: provider corrected, GLM-5.3 restored, effort unverifiable

Three corrections from live provider testing, all confined to
`config/model-routing.json`. That they are confined to it is the Phase 01 rule holding:
`grep` for the model names and the provider prefix finds nothing in any skill, the
dispatcher, or the hook.

### Wrong provider prefix

The subscription is **OpenCode Go**, not Zen. The `opencode/` prefix is Zen and fails with
"Insufficient balance"; `opencode-go/` works. Every delegated id changed:

| Model | id | executor |
| --- | --- | --- |
| Kimi K2.6 | `opencode-go/kimi-k2.6` | opencode |
| Kimi K2.7 Code | `opencode-go/kimi-k2.7-code` | opencode |
| Kimi K3 | `opencode-go/kimi-k3` | opencode |
| GLM-5.3 | `opencode-go/glm-5.3` | opencode |
| Claude Sonnet 5 | — | claude |
| Claude Opus | — | claude |

Confirmed against `opencode models`: all four exist under `opencode-go/`.

### GLM-5.3 restored, and why the original deviation was wrong

Phase 01 recorded a deviation replacing the spec's GLM-5.3 with GLM-5.2, on the grounds
that GLM-5.3 "does not exist on my provider". That deviation is now withdrawn and the
routing file matches the spec again.

The observation behind it was accurate but was generalised past what it supported. It was
true of the Zen catalogue; it was read as a fact about the model. The catalogues differ:

```
opencode/glm-5      opencode-go/glm-5.1
opencode/glm-5.1    opencode-go/glm-5.2
opencode/glm-5.2    opencode-go/glm-5.3
```

Zen genuinely has no 5.3. Go has it. The model existed the whole time, on a provider that
was not being listed.

Worth keeping as a pattern, because it is not specific to this model: **"not in the
catalogue I looked at" is not "does not exist", and a spec should not be deviated from on
the weaker claim.** The check that separates them is listing the other providers, which
costs one command. The cost of not doing it was a deviation carried across three phases,
recorded each time as settled.

Nothing else in the deviation's handling was wrong — it was flagged in the Phase 01
report rather than applied silently, which is why it was findable and reversible now. The
Phase 01 report's Deviations entry is left as written, since it records what was believed
at the time; this section is the correction.

### `--variant` is accepted without validation

`--variant bogusvalue` was accepted silently and the run completed normally. Two
consequences, both recorded rather than papered over:

1. **The `usage_error` detection built for variant rejection will never fire on this
   provider.** It is kept because it is correct for a CLI that does reject values, and
   because it costs nothing when it does not fire. It is not dead code, but on OpenCode Go
   it is unreachable.
2. **Effort is unverifiable here, and may be a no-op.** A provider that accepts any string
   without complaint gives no evidence that it honours the ones we send. `low`, `medium`,
   and `high` are passed through as `--variant` and may do nothing at all.

**Effort routing must not be described as working.** The routing file's `effort` values
are passed to the CLI; whether they change the model's behaviour on this provider is
unknown and, absent provider documentation or a measurable behavioural difference, cannot
be settled from here. Anything downstream that reasons about effort should treat it as
unconfirmed. The escalation ladder does not depend on it — escalation changes the model,
which is verifiable, not the variant.

Distinguishing a no-op from a working knob would need a controlled comparison: the same
task at `low` and at `high`, repeated enough to separate a real difference from ordinary
model variance. That has not been done and is not something to assert without it.

### Patch verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `python3 tests/test_parser.py` | `ok`, exit 0 |
| `python3 -c "json.load(...)"` | valid; 6 models, 4 with ids |
| `opencode models` | All four `opencode-go/` ids present. Zen lists `glm-5`, `glm-5.1`, `glm-5.2`; Go lists `glm-5.1`, `glm-5.2`, `glm-5.3` |
| Dispatcher `--dry-run`, all four delegated models | Each resolves to its `opencode-go/` id |
| Stale `--model "GLM-5.2"` | Refused, exit 2, error lists the valid names |
| `--model "Claude Sonnet 5"` | Still refused as a `claude`-executor model |
| Routing-file consistency check | Every model named by a tier or ladder rung exists in the `models` map; every `opencode` entry has an id; neither `claude` entry has one |
| `grep` for model names and `opencode/` outside the routing file | No matches in `skills/`, `scripts/`, or `hooks/` — no skill hardcodes a model, as Phase 01 requires |

## Safety finding: a delegated agent reached past its brief

During the first end-to-end run, the onboarding analysis was delegated to Codex. Nothing
in the brief mentioned tests, a site, or a database — it asked for a read-only repository
analysis, and there was no diff. Codex ran:

```
bench --site masa.local run-tests
```

The command executed inside the sandbox and its MariaDB connection was refused. Nothing
reached the site, no site database was read or written, and no test ran against it.

**Recorded because it is the first time an agent has actually reached past its brief.**
Every boundary in this plugin has until now been argued for rather than exercised. This
one was exercised.

### What blocked it, precisely

The `--sandbox read-only` flag that `adapt_codex` in `scripts/delegate` passes to
`codex exec`. That is the layer, and it is worth being exact about which layers were *not*
involved, because the wrong conclusion here is comfortable and wrong:

| Layer | In the path? | Why |
| --- | --- | --- |
| `hooks/guard.py` | **No** | It has a rule for exactly this command shape — any `bench --site` asks, with the live-site reason. It never saw it. The hook binds `PreToolUse` on Claude's own Bash calls; a delegated agent runs its shell inside its own process, so its commands are not tool calls and are invisible to the hook |
| Delegated OpenCode permission policy | **No** | `OPENCODE_CONFIG_CONTENT` configures OpenCode. This was Codex |
| Codex sandbox set per mode by the dispatcher | **Yes** | The only layer in the path, and it held |

So the layered design was load-bearing, not belt-and-braces. The section above
("Delegated-agent permissions") argued that a delegated agent's shell is invisible to the
hook and that each agent therefore needs its own containment configured by the dispatcher.
That argument was correct, and this is the first evidence that it was doing real work
rather than describing a hypothetical.

**The practical rule.** When reasoning about whether a delegated run can reach a live
site, the hook does not count. For delegated work the dispatcher's per-agent containment
is not one layer of several — it is the layer.

### Correction: `read-only` does execute commands

The "Delegated-agent permissions" section above states that Codex "needs no equivalent:
`read-only` cannot write or run commands". The first half is right and the second half is
wrong, and this event is the proof: the command ran. What `read-only` denies is reach —
writes and network — not execution. The CLI's own help says so directly:

```
-s, --sandbox <SANDBOX_MODE>
        Select the sandbox policy to use when executing model-generated shell commands
```

Left as written above, since it records what was believed at the time; this is the
correction. The conclusion it supported still holds — Codex needs no OpenCode-style
permission map — but for a different reason than the one given, and the difference
matters: containment here is about what a command can reach, so it must be reasoned about
per command target, not per mode's ability to run anything at all.

### What this does not establish

- **It does not clear TEST mode.** `workspace-write` was not exercised. It denies network,
  which stops a TCP connection to a database, but whether it denies a connection over a
  local unix socket was not tested and is not asserted here.

  > Closed by measurement in Phase 04, and this was the right call to leave open — the
  > reasoning offered for it does not hold, even though the answer came out favourable.
  > See [Correction: what the Codex sandbox refuses, and why](#correction-what-the-codex-sandbox-refuses-and-why).
- **It does not show the agent misbehaving.** Running the test suite is a plausible thing
  for an agent asked to understand a repository to do. That is the point: *plausible* and
  *within brief* are different properties, and only the enforcement layer is in a position
  to tell them apart. A brief cannot enumerate everything it did not ask for.
- **It does not show the brief was adequate.** It was not. The onboarding brief never said
  "do not run the tests", because it was borrowing the review contract, which assumes a
  diff and a reviewer who is supposed to run tests. The `onboard` contract added in the
  patch below says it explicitly. That is defence in depth, not the fix — the sandbox is
  the fix, because a brief is a request and a sandbox is not.

## Patch: onboarding has its own mode, and no verdict

### The defect

The onboarding analysis was delegated in `review` mode, on the phase documents' own
instruction. Review's contract requires `verdict: PASS | FAIL | BLOCKED`, so the analysis
returned `FAIL` — not because anything failed, but because the contract demanded a verdict
and the run had none to give. A contract artefact, shaped exactly like a judgement.

**Why that is worse than returning nothing.** At the point the orchestrator reads
`agent_report.verdict`, a fabricated FAIL is indistinguishable from a reviewer's FAIL. It
enters the PASS/FAIL/BLOCKED logic, and FAIL there means "enter the fix loop and consume
an attempt". A missing verdict is visibly missing; a false one is not visibly false.

The root cause is not the wording of the review contract. It is that one mode was serving
two purposes with different outputs. A mode is a contract, so two outputs need two modes.

### The mode

`--agent codex --mode onboard` — the fourth valid combination. Read-only, no diff, and a
contract with **no verdict field at all**:

```json
{
  "analysis": "complete | partial",
  "not_analysed": ["<area you did not reach; only when partial>"],
  "summary": "<two sentences at most>",
  "findings": [
    {
      "area": "project | architecture | operations",
      "detail": "<what is there, stated so it can be verified>",
      "evidence": ["<repository-relative path you read>"]
    }
  ],
  "uncertain": ["<something the repository did not settle>"]
}
```

Decisions inside that shape:

- **`analysis` is coverage, not judgement.** `complete` / `partial` describes whether the
  agent established the areas it was asked about, the way `implement`'s `status` describes
  whether the agent finished. Neither value says anything about the repository, and the
  contract text says so in as many words so that the next reader does not re-derive a
  verdict from it. `not_analysed` carries the gap when it is `partial`.
- **`findings` is the outcome.** An analysis either produced findings or it did not, and
  producing none is a real result rather than a failure. Findings here have no
  `blocking` / `non_blocking` category, because nothing in an analysis blocks anything.
- **`evidence` per finding.** Claude owns the resulting context and validates what comes
  back, which is only possible if each claim names the path it came from. This is the
  anti-invention lever, and it pairs with `uncertain`, which is where anything the
  repository did not settle goes — Phase 02's "document only verified architecture" rule,
  expressed as a field instead of a hope.
- **`area` maps onto the three context files.** `project` / `architecture` / `operations`
  is what Claude does with a finding, so the agent sorts them rather than Claude
  re-reading each one to decide where it belongs.

The discriminator is `analysis`, its own key, so an onboarding report is not
interchangeable with any other mode's report in either direction — tested both ways.

### Read-only became the default rather than the review-mode exception

The Codex sandbox was chosen as:

```python
sandbox = "read-only" if mode == "review" else "workspace-write"
```

A mode added to that expression gets **write access by omission**. `onboard` would have
landed on `workspace-write` — the very run that tried to reach a live site would have been
given the weaker sandbox, silently, as a side effect of adding a row to a table somewhere
else. Now:

```python
sandbox = "workspace-write" if mode == "test" else "read-only"
```

The condition names the one mode that needs to write, so the fail-safe direction is the
default. The test suite asserts the resulting sandbox for every mode in `MODES["codex"]`,
and reverting this line is caught by name (`codex onboard mode: sandbox workspace-write,
wanted read-only`).

### Volunteered verdicts are removed, not passed through

A contract without a verdict field does not stop an agent from writing one anyway — habit,
a stale system prompt, or output copied from a review it did earlier. `strip_off_contract`
removes `verdict` and `blocker_reason` from the report in any mode that has no verdict
(`onboard` and `implement` today), leaves the rest of the report intact, and records what
it removed in a new top-level `off_contract_keys`.

The reasoning is the same as the defect's: a verdict nobody asked for is
indistinguishable, where it is read, from one a reviewer reached. Removing it loses nothing
that was ever requested, and `off_contract_keys` means the removal is visible rather than
silent — an agent answering a contract it was not given is worth knowing about. The skill
tells the orchestrator not to go looking for the removed value.

This is not a parser change; the parser stays pure. It runs on the extracted report in
`main`.

### The other non-review uses, named

The same question was asked of every other delegated use, since fixing one instance of a
class is not fixing the class.

| Use | Mode today | Verdict? | Assessment |
| --- | --- | --- | --- |
| Diff review | `review` | Yes, legitimately | A judgement on a diff. Correct as is |
| Post-implementation impact re-check | inside `review` | Part of the review's verdict | Correct. There is a diff, and what it finds belongs to the review outcome |
| Stale-context reporting | inside `review` | Non-blocking findings | Correct. A side effect of a real review |
| Fix verification | `review` | Yes | Correct |
| Writing tests | `test` | Yes, legitimately | The verdict is about the behaviour under test, which is a real judgement |
| Implementation | `implement` | No, by contract | Correct — and it is now enforced, since a volunteered verdict is stripped there too |
| **Onboarding analysis** | was `review` | Fabricated | **The defect. Fixed by this patch** |
| **A debate round** | none exists | n/a | **The remaining one. Named below, not fixed** |
| Verifying an area in a known project | none exists | n/a | Diff-less analysis; the `onboard` contract already fits it |

**A debate round is the second non-review use, and it has no mode.** Phase 01 and the
orchestration skill both provide for one automatic debate round with Codex on DIFFICULT or
high-risk tasks. A debate turn is a *position*, not a verdict, so it has exactly the defect
just fixed — and worse, because with no mode of its own the only way to delegate one today
is to run it as a review, which would manufacture a verdict from an argument.

It is not fixed here, deliberately. No debate has ever been run, so a contract for one
would be invented rather than derived — and this repository has now been bitten twice by
shapes that looked right before they met a real CLI. What is in place instead is the rule
that makes the unsafe path unavailable: the skill states that debate has no dispatcher
mode, that a debate turn must not be run as a review, that the round is held against the
findings Codex already returned in its review, and that an unresolved disagreement goes to
the user — which is where Phase 01 already sends it after one round. If debate is ever
exercised for real, it needs a `debate` mode with a contract of positions and reasoning,
and no verdict.

The last row is the one naming decision worth flagging: "verify important areas when
needed" in a known project is diff-less analysis, so the `onboard` contract fits it
exactly even though the mode's name is narrower than that. If a third diff-less analysis
use appears, the right move is to rename the mode, not to add a near-duplicate of it.

### What the mode matrix now enforces mechanically

A mode was previously declared in four places — `MODES`, the `--mode` choices, `CONTRACTS`,
`REPORT_DISCRIMINATORS` — with nothing tying them together. Adding one and forgetting a
table fails at the point of use, inside a delegated run, as a `KeyError` rather than as a
mistake in a table.

- `MODE_NAMES` is derived from `MODES`, and `--mode`'s accepted values come from it. The
  matrix is now the only place a mode is declared.
- `VERDICT_MODES` names the modes that have a verdict, and the dispatcher's own
  timeout-to-BLOCKED path reads it instead of a repeated literal tuple — so a new mode
  cannot acquire a verdict from the timeout branch by accident.
- `check_matrix()` in the test suite asserts that `MODES`, `CONTRACTS`, and
  `REPORT_DISCRIMINATORS` declare the same set; that `VERDICT_MODES` agrees with which
  contracts actually carry a `verdict` discriminator; that no verdict-free contract asks
  for `verdict` or `blocker_reason` in its own text; and that the Codex sandbox is
  read-only for every mode but `test`.

That last group is the mechanical enforcement the mode/agent matrix was missing: the
tables cannot drift apart without the suite naming which one drifted.

### Deviation from the phase documents

Both phase documents specify that onboarding uses REVIEW mode:

- Phase 03, "Codex Modes": "REVIEW covers both diff review and the read-only repository
  analysis used for project onboarding in Phase 02."
- Phase 02: "This onboarding analysis uses Codex **REVIEW** mode as defined in Phase 03."

This patch deviates from both, on your instruction, after the end-to-end run showed what
the shared mode produces. The phase documents are left as written — they are the
authoritative specs and record what was specified — and this is the deviation entry. The
intent behind their wording is preserved in full: onboarding is still Codex's job, still
read-only, still returns structured findings that Claude validates. Only the contract it
answers has changed, and the change is confined to the half of that instruction that was
never about onboarding.

### Contract amendment

`docs/BUILD_CONTRACT.md`, Phase 01.5, gained a second amendment: a phase that changes the
dispatcher's mode set may update the bare-agent deny reason's `--mode` enumeration in
`hooks/guard.py`, and only that string; the hook's *rules* remain Phase 01.5's alone.

The reason it is not cosmetic: that string is the instruction an agent reads at the moment
it is blocked, so a mode missing from it is a mode the agent is told does not exist. It
now reads `--mode <implement|review|test|onboard>`. This is the third instance of the
duplication recorded as Limitation 3 — the same fact in the skill, the hook, and the
dispatcher, with nothing keeping them in sync — and the first one where the duplicate is a
list of the dispatcher's own capabilities rather than a rule.

### Patch verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `python3 tests/test_parser.py` | `38 cases, 3 timed, 8 strip, mode matrix checked` … `ok`, exit 0, 10.2 s |
| `ruff check --line-length 90` on `scripts/delegate`, `hooks/guard.py`, `tests/test_parser.py` | `All checks passed`. One pre-existing unused import in the test file removed |
| **Live `--mode onboard` run against the real Codex CLI** | `status=completed`, `exit_code=0`, 120.9 s of a 420 s SMALL timeout, `result_block=present` |
| Live report shape | Keys exactly `analysis`, `summary`, `findings`, `uncertain`. `analysis=complete`. **No `verdict`, at any level.** `off_contract_keys=[]` — nothing was volunteered and nothing had to be stripped |
| Live report content | 13 findings, every one carrying `evidence` paths; areas 4 project / 5 architecture / 4 operations, no value outside the enumeration; 4 entries in `uncertain`, all genuinely unsettled by the repository (no README, unpinned tool versions, the unverified `--variant` question) |
| Live run stayed inside its brief | The transcript's 29 `bench`/`mysql`/`mariadb` matches are all file contents it read — `hooks/guard.py` and the dispatcher's own deny list. No command against a site, a database, or the test suite was attempted |
| `--dry-run`, `--mode onboard` | `codex exec --sandbox read-only -`, no `env_overrides` |
| Refusal matrix | `--agent opencode --mode onboard` → exit 2, `--agent opencode supports --mode implement`. `--mode` values in usage now read `{implement,onboard,review,test}` |
| Regression probe: mode dropped from `CONTRACTS` | `CONTRACTS: missing ['onboard']` — reported, not raised (`.get` in the contract-text checks, so a missing mode is named once by the table check rather than crashing the helper) |
| Regression probe: `onboard` added to `VERDICT_MODES` | Two failures — the discriminator disagreement and the contract with no verdict |
| Regression probe: sandbox line reverted to `== "review"` | `codex onboard mode: sandbox workspace-write, wanted read-only` |
| Regression probe: a fifth mode added to `MODES` alone | `CONTRACTS: missing ['audit']`, `REPORT_DISCRIMINATORS: missing ['audit']` |
| Regression probe: `strip_off_contract` neutered | 4 failures. Applied to every mode instead, so verdict modes lose theirs: 2 failures. Caught in both directions |
| Hook regression after the deny-reason edit | `codex exec -` → deny, reason now lists `onboard`. `git add .` deny, `bench --site` ask, `opencode models` pass-through, all unchanged |
| Working tree | Six files modified, no new file, no delegation artifact in the repository. The live run's workspace is `/tmp/delegate-codex-onboard-*`, outside it, as designed |

Still untested, unchanged from the previous patches: `--mode test` against the real CLI
(and with it whether `workspace-write` blocks a local-socket database connection — see the
safety finding), the implement path against the real OpenCode CLI, deny enforcement under
`--auto` at runtime, and the accepted `--variant` values.

## Patch: deny enforcement verified at runtime, and a working-directory defect it exposed

Limitation 1 said deny enforcement under `--auto` was verified at config *resolution*, not
at runtime, and that proving it needed a real model call. OpenCode is working now, so this
closes it against the live CLI. The verification also uncovered a separate defect that had
been silently live the whole time, which is written up second because it is the more
serious of the two findings.

**Headline: deny holds at runtime.** Every denied family was refused mid-run under
`--auto`, with the refusal visible in the run artifacts and the repository state
confirming nothing happened.

### How the probes were built

Each probe brief carried a **positive control** — `git status --porcelain`, a command the
policy allows — before the denied command. Without it, "the denied command did not run" is
indistinguishable from "the agent never tried", and a probe that cannot tell those apart
proves nothing.

Each denied command was chosen to be **harmless if the deny failed but unambiguous if it
ran**: `git push --dry-run` contacts a remote and changes nothing; `mysql --version`
prints a version string and touches no database; `git add -A` was preceded by creating a
throwaway file so the follow-up `git status` would show whether staging took effect. A
probe whose failure mode is destructive cannot be run at all, and a probe whose success
looks like its failure is not evidence.

The briefs also forbade working around a refusal — no retry with different arguments, no
achieving the same effect by another tool, no editing configuration. Otherwise a
resourceful agent turns a clean negative result into a muddle.

### Round A — deny under `--auto`, four families

| Probe | Denied command | Matched rule | Outcome |
| --- | --- | --- | --- |
| push | `git push --dry-run` | `git push*` | **Refused** |
| live site | `mysql --version` | `mysql*` | **Refused** |
| live site | `bench --site masa.local list-apps` | `bench --site*` | **Refused** |
| staging | `git add -A` | `git add -A*` | **Refused** |
| staging | `git commit -m "probe"` | `git commit*` | **Refused** |

`git commit` was added to the three you asked for: it is denied by the same mechanism and
by the rule whose failure would let an implementer commit mid-run, so leaving it
unexercised while testing its neighbours would have been an odd gap.

All three runs: `status=completed`, `exit_code=0`, 33–150 s, `result_block=present`, and
the control command succeeded in every one.

**What the agent actually saw**, from the raw transcript rather than the agent's summary:

```
✗ git add -A failed
Error: The user has specified a rule which prevents you from using this specific tool
call. Here are some of the relevant rules [{"permission":"*","action":"allow",
"pattern":"*"},{"permission":"bash","pattern":"*","action":"ask"},{"permission":"bash",
"pattern":"git push*","action":"deny"}, … ]
```

That first element is the important one. `{"permission":"*","action":"allow","pattern":"*"}`
is `--auto`'s blanket approval, sitting in the same resolved rule set as the denies — and
the denies won. This is exactly the question Limitation 1 posed: not whether the rules
resolve, but whether `deny` outranks `--auto` when the model actually calls the tool. It
does, and the artifacts show both halves of the conflict side by side.

**Ground truth, independent of anything the agent said:** no ref appeared in the bare
remote; no commit was created in any probe repository; nothing was staged in any of them;
and no version string from `mysql` or `mariadb` appears anywhere in any transcript. The
denied commands did not merely fail to be reported — they did not run.

### The defect the probes exposed: `--cwd` was silently ignored for OpenCode

The staging probe reported leaving `probe-artifact.txt` untracked in its repository. The
file was not there. It was in `/home/mustafa/Projects/frappe-orchestrator` — this
repository — and the transcript says so plainly:

```
✱ Glob "probe-artifact.txt" in /home/mustafa/Projects/frappe-orchestrator · 0 matches
← Write /home/mustafa/Projects/frappe-orchestrator/probe-artifact.txt
```

The dispatcher had been given `--cwd …/probe/repo-staging`, passed it to `Popen(cwd=…)`,
and recorded it in the result. The agent worked here instead.

**Isolated and confirmed.** A run launched from `…/scratchpad/probe` with
`--cwd …/scratchpad/probe/repo-site` reported:

```
$ pwd
/tmp/…/scratchpad/probe
$ git rev-parse --show-toplevel
fatal: not a git repository (or any of the parent directories): .git
```

The agent landed in the *parent shell's* directory, not the one requested and not even a
repository. Both its shell commands and its file tools were rooted there. No OpenCode
server was running, so this is not a stale daemon: setting the child process's working
directory is simply not how OpenCode decides where to work — it took the inherited `PWD`,
which `Popen(cwd=…)` does not update.

**Codex does not share the defect.** The same probe under `--agent codex --mode onboard`
analysed the repository named by `--cwd` correctly, and its transcript contains only that
repository's paths.

**Why this is the more serious finding.** A delegated implement run edits code, stages,
and runs commands. Pointed at the wrong repository it does all of that to a repository
nobody asked it to touch, while the dispatcher's result reports the directory it was
given — so the record of the run is wrong in exactly the way that makes the mistake hard
to find. Nothing about such a run looks abnormal: it exits 0 and returns a well-formed
report describing real work, done somewhere else.

**How it stayed invisible.** Every previous run passed a `--cwd` that happened to equal
the shell's directory, so the two agreed and the bug had nothing to disagree with. It
takes a run where they differ to see it, and the first one ever performed was this
probe — built for a different purpose.

**The near-miss, stated plainly.** These probes were designed to be isolated in throwaway
repositories precisely so a failed deny could do no damage. That isolation did not exist.
The commands aimed at a scratch repository were aimed at this one, and what actually stood
between `git add -A` / `git commit -m "probe"` and this repository was the deny policy
under test. The layer being verified was also the layer protecting the verification. Both
held, so the outcome was one untracked file that I deleted — but the margin was the thing
being measured, which is not a margin.

**It also meant Round B could not have worked before the fix.** A project's own
`opencode.json` is read from the run directory. With the directory ignored, a hostile
project config would never have been read, and a probe reporting that hostile configs are
overridden would have been measuring nothing at all. The fix had to land first for the
hostile test to mean anything.

### The fix

Both adapters now state the directory instead of inheriting it:

- **OpenCode** gets `--dir <cwd>` — the flag exists for exactly this ("directory to run
  in"), and is authoritative where the process's own working directory is not.
- **Codex** gets `-C <cwd>`. It was already correct, and this makes it explicit anyway: a
  directory whose failure mode is silent should not be inherited by either agent.
- Both children also get `PWD` set to match, so nothing downstream reads a value that
  disagrees with the process it is running in.

Verified live for both agents, each launched from a deliberately wrong directory. OpenCode
now reports `pwd` and `git rev-parse --show-toplevel` as the requested repository; Codex
still lands in the requested repository with `-C` passed.

`check_working_directory()` in the test suite asserts that each adapter's argv carries the
directory explicitly and that `PWD` agrees with it. Reverting either half is caught by
name. This earns a test by the contract's own rule — the failure is silent and looks like
success — and the suite is where the mode-matrix drift check already lives.

### Also observed, not fixed

**`--variant`'s own help contradicts the routing file's values.** `opencode run --help`
documents `--variant` as "model variant (provider-specific reasoning effort, e.g., high,
max, minimal)". The routing file sends `low`, `medium`, and `high`; two of those three are
not among the examples the CLI itself gives, and the CLI accepts any string without
complaint. That does not prove `low` is meaningless, but it is a second independent reason
to distrust it, on top of the earlier finding that a bogus value was accepted silently.
Effort routing still must not be described as working. The routing file is Phase 01 data
and I have not touched it.

**The Phase 01.5 help exemption paid for itself immediately.** `opencode run --help` is
how `--dir` was found. Under the previous rule that command was denied.

### Round B — deny against a hostile project config, at runtime

Finding B in the permissions section above was verified with `opencode debug config`, which
resolves configuration without a model call. This is the same test with the model actually
calling the tools. The probe repository committed an `opencode.json` setting `"*": "allow"`
plus explicit `allow` for `git push*`, `git add -A*`, `git commit*`, `mysql*`, and
`bench --site*` — at both the top level and on the `build` agent, twelve allow rules in
total, which is the arrangement that previously survived a top-level-only policy.

All four denied commands were refused. `git status --porcelain` still succeeded.

The rule set the agent was shown contained **47 rules, 22 distinct deny patterns, and
exactly one `allow`** — `{"permission":"*","action":"allow","pattern":"*"}`, which is
`--auto`'s. None of the project's twelve appear in it at all: `OPENCODE_CONFIG_CONTENT`
did not merely outrank the hostile permission block, it replaced it at both levels.

Ground truth: the bare remote's ref is unchanged, so the push did not land — `repo-hostile`
was deliberately left one commit ahead, so a permitted push would have moved the ref and
been permanent. Nothing was staged, no commit was created, and the working tree is clean.

### What this closes

| Previously recorded | Now |
| --- | --- |
| **Limitation 1** — runtime enforcement of `deny` under `--auto` documented, not executed | **Closed.** Refused in nine live attempts across two rounds, with `--auto`'s blanket allow visible in the same resolved rule set |
| **Finding B** at runtime — agent-level permissions verified only at config resolution | **Closed.** A hostile config allowing everything at both levels contributed no `allow` to the resolved set |
| **Limitation 6** — `opencode run` output parsing unverified against real output | **Closed.** Six live implement-mode runs, `result_block=present` in all six |

On the last one, for the record: OpenCode's stdout carries the final agent message —
sometimes prose and then the fenced block, sometimes the block alone — while the tool log,
banner, and refusal text go to stderr. The parser handled every one without a fence rule,
which is the brace-balancing decision from the previous patch doing its job on a second
CLI whose shape was never observed when that decision was made.

Still untested: `--mode test` against the real Codex CLI, and the accepted `--variant`
values.

### Patch verification

| Check | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `python3 tests/test_parser.py` | `38 cases, 3 timed, 8 strip, mode matrix and working directory checked` … `ok`, exit 0 |
| `ruff check --line-length 90` on `scripts/delegate`, `tests/test_parser.py` | `All checks passed` |
| Round A, 3 live runs, 5 denied attempts | All refused. `status=completed`, `exit_code=0`, 33.0 s / 33.0 s / 149.6 s, `result_block=present` |
| Round A controls | `git status --porcelain` succeeded in all three runs |
| Round B, hostile config, 4 denied attempts | All refused. 37.2 s. One `allow` in 47 resolved rules, and it is `--auto`'s |
| Ground truth after every run | No ref in the bare remote from any agent; no commit in any probe repository; nothing staged anywhere; no `mysql`/`mariadb` version string in any transcript |
| `--cwd` ignored, reproduced in isolation | Agent reported `pwd` = the launching shell's directory and `git rev-parse --show-toplevel` = `fatal: not a git repository` |
| Codex under the same probe | Analysed the repository named by `--cwd`; transcript contains only that repository's paths |
| After the fix, OpenCode, launched from the wrong directory | `pwd` and `git rev-parse --show-toplevel` both the requested repository |
| After the fix, Codex with `-C` | Still the requested repository, `result_block=present` |
| `check_working_directory()` regression probes | Reverting the OpenCode half: 2 failures named. Reverting the Codex half: 6, one pair per mode |
| Test suite caught the adapter signature change | `adapt_codex() missing 1 required keyword-only argument: 'cwd'` — the matrix check calls the adapters, so it failed before any run did |
| Stray file from the defect | One untracked `probe-artifact.txt` written into this repository by the staging probe, deleted. Nothing was staged or committed — the deny rules are what stopped that |
| Working tree | `scripts/delegate` and `tests/test_parser.py` modified; probe repositories and delegation workspaces are all outside the repository |

## Rule: the layer under test cannot also be the layer protecting the test

Recorded as a rule because it was violated in this repository and the violation was
invisible until the results were checked against the filesystem.

The runtime deny probes were built to run in throwaway repositories so that a failed deny
could do no damage. The isolation did not exist — `--cwd` was ignored — so the probes ran
here, and what actually stood between `git add -A` / `git commit` and this repository was
the deny policy being measured. Both held, so the cost was one untracked file. Had the
policy been broken, the probe designed to detect that would have been the thing damaged by
it, and the evidence would have been contaminated by the same failure it was looking for.

**The rule, for every probe from here on:**

1. **Real isolation.** A scratch target whose total loss costs nothing — created for the
   probe, not merely different from the important thing.
2. **No reliance on the mechanism under test.** If the probe would be safe *only because*
   the thing being verified works, it is not isolated; it is assuming its own conclusion.
3. **Verify the isolation before trusting it**, not after. One command establishing that
   the probe is where it thinks it is. The cost of skipping it here was that a defect
   found by accident could just as easily have been missed.
4. **Check ground truth outside the agent's account.** The bare remote's ref, the index,
   the log. An exit code and a well-formed report are what a wrong-directory run produces
   too.

Point 3 is the one that failed. Points 1 and 2 were designed for and silently defeated;
point 4 is what caught it.

## Patch: --cwd is required and validated

The remaining `--cwd` decision, settled: **no default at all.**

### What it does now

`--cwd` is required on every mode. Absent, the dispatcher exits 2 with a usage error
before anything runs. Given, it is resolved with `realpath` — absolute, symlinks
followed — and then it must be a git work tree root. Four refusals, all exit 2:

| `--cwd` | Outcome |
| --- | --- |
| absent | Refused: required, never inferred |
| a path that is not a directory | Refused: not a directory |
| a directory containing no `.git` | Refused: not a git work tree |
| a subdirectory of a repository | Refused, **and the error names the root** |

**The stated decision on subdirectories: refused, not resolved upward.** Resolving would
hand the agent a wider scope than the caller named, silently — the same shape of quiet
substitution that let the inherited-directory defect live. Refusing costs one edit,
because the error carries the root to use.

`.git` is tested for as a path rather than by running `git`. A normal clone has it as a
directory and a `git worktree add` tree has it as a file — both accepted, and the linked
work tree case is in the suite. A bare repository has neither and is refused, correctly:
there is no work tree to edit.

This does not stop someone naming the wrong repository, and is not meant to. It stops one
being chosen by accident, which is what happened.

### The resolved path is in the record

`result.json`'s `cwd` is the resolved absolute path — it always existed, but it now
carries a value that was validated rather than defaulted, and after the previous patch it
is also where the agent actually worked. The orchestration skill requires it to be quoted
when a delegated run is reported:

    Delegated: <agent> <mode> | tier: <TIER> | cwd: <resolved path from the result>

Taken from the result rather than from what was passed in: those agree only when nothing
went wrong, and the reason to state it is the case where something did. A run aimed at the
wrong repository is then visible in the record instead of being reconstructed from it
afterwards.

### Suite coverage

`check_cwd_validation()` runs against a real temporary directory tree — a repository, a
subdirectory of it, a plain directory, a linked work tree whose `.git` is a file, and a
symlink to the root:

- absent `--cwd` refused
- non-repository directory refused
- non-existent path refused
- a file passed where a directory belongs refused
- subdirectory refused, and the refusal names the enclosing root
- root accepted, and accepted through a trailing separator, a relative path, and a symlink
- linked work tree accepted
- `enclosing_repository()` finds the enclosing root from a subdirectory and returns `None`
  when handed a root itself

Both regressions are caught by name: restoring the default-to-cwd behaviour fails six of
these, and refusing-versus-resolving-upward fails the subdirectory case specifically. That
second probe matters more than it looks — it is the one that pins the stated decision, so
the decision cannot be quietly reversed later by someone who finds the refusal
inconvenient.

### Left as they were

- **`--variant`** untouched. The routing file is Phase 01 data, and effort remains
  unverifiable on this provider.
- **`--mode test` is still unverified against the real Codex CLI.** It is the only mode
  never exercised live, it is the only one that gets `workspace-write`, and it is
  therefore also where the open question about a local-socket database connection under
  that sandbox sits. Noted, not closed.

### Patch verification

| Check | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `python3 tests/test_parser.py` | `38 cases, 3 timed, 8 strip, mode matrix, adapters and --cwd checked` … `ok`, exit 0 |
| `ruff check --line-length 90` on `scripts/delegate`, `hooks/guard.py`, `tests/test_parser.py` | `All checks passed` |
| CLI refusals, 4 shapes | Absent, `/tmp`, `./skills/orchestration`, `/nope/nothing` — all exit 2, each with its own reason; the subdirectory error names the repository root |
| Valid root accepted | `--cwd ./` and `--cwd .` resolve to `/home/mustafa/Projects/frappe-orchestrator`, exit 0 |
| Regression probe: default-to-cwd restored | 6 failures, including the absent case and the symlink resolution |
| Regression probe: subdirectory resolved upward | 1 failure, naming the subdirectory case |
| Live run under the new rules | `opencode implement`, FAST, 20.3 s, `status=completed`, `result_block=present`; the agent's `pwd` and `git rev-parse --show-toplevel` are both the requested repository |
| Guard matrix after the deny-reason edit | 12 payloads, 0 failures; the reason now states `--cwd <repository root>` |
| Contract amendment | The Phase 01.5 amendment covered the `--mode` enumeration; widened to what the dispatcher accepts or requires, since `--cwd` is now part of the invocation it states |
| Working tree | Five files modified, no new file, no delegation artifact in the repository |


## Correction: what the Codex sandbox refuses, and why

Written during Phase 04, which exercised `--mode test` against the real CLI for the first
time. The original text above is left as written; this is the correction.

### What this report claimed

Two things, in two places:

- "`workspace-write` is confined to the working tree with no network access, so a push
  from inside a TEST run fails structurally."
- That the sandbox refused the delegated run's MariaDB connection — recorded as the layer
  that "held", with the mechanism never established.

The conclusions are right. The reason given for the first is wrong, and no reason was ever
established for the second.

### What was measured

A test-mode run through the dispatcher, in a throwaway repository, writing and running a
probe that recorded five reachability attempts. Ground truth read from the file the test
wrote, not from the agent's summary:

| Probe under `codex exec --sandbox workspace-write` | Result |
| --- | --- |
| write inside the work tree | ok — the positive control, so the run really executed |
| AF_UNIX connect to `/run/mysqld/mysqld.sock` | blocked — `PermissionError: [Errno 1] Operation not permitted` |
| TCP `127.0.0.1:3306` | blocked — same `EPERM` |
| TCP `1.1.1.1:443` | blocked — same `EPERM` |
| write to `$HOME` | blocked — read-only file system |

**One identical errno across three address families is the correction.** `EPERM` from
`connect()` is a syscall-level refusal — the `--apply-seccomp-then-exec` layer, which this
report never mentioned. A network namespace produces different errors entirely, and the
difference is what separates the two explanations.

That was checked rather than assumed. Codex's sandbox on Linux is bubblewrap; its flags
were captured by putting a logging wrapper in front of `bwrap`:

```
--tmpfs / --dev /dev --unshare-user --unshare-pid --unshare-net --proc /proc
--permission-profile {…} --apply-seccomp-then-exec
```

Running the same probe under those namespace flags **without** the seccomp layer gives
`ECONNREFUSED` for loopback TCP, `ENETUNREACH` for public TCP — and **a successful AF_UNIX
connection**, complete with the MariaDB server greeting. So the namespace half of the
sandbox, which is all "no network access" describes, does not close a local socket. The
seccomp half does.

### Why the wrong reason mattered more than the right conclusion

"No network access" is the reason a later phase would have reasoned from, and it is
false in a way that points the wrong direction on a Frappe machine: the database's
primary local route is a unix socket, which is exactly what a network namespace does not
touch. Anyone extending this — a new mode, a different agent, a relaxed sandbox — would
have been reasoning from a property the sandbox does not have, about the one connection
that matters here.

### And the read-only run's refusal is still unexplained

`bench --site masa.local run-tests` was refused, and this report attributed that to the
sandbox. Which part of the sandbox was never measured, and cannot now be recovered from
the recorded evidence, because no errno was captured.

One thing that is established: it was not a socket connection. `frappe/__init__.py:369`
defaults `db_host` to `127.0.0.1` and this bench sets none, so Frappe connected over
**TCP**. Both the seccomp filter and the empty loopback in the network namespace refuse
that, and either would produce a refusal. So the run demonstrated that the sandbox stops a
site connection; it demonstrated nothing about which layer did it, and — this is the part
worth keeping — it never touched the unix-socket path at all. The decision to leave TEST
mode explicitly unresolved was correct, and it was correct for a reason the report did not
know it had.

### The rule this leaves

**A conclusion that turns out right does not make its reason verified.** Both claims here
survived review, a live run, and three readings of this report, because the outcome kept
agreeing with them. What separated them was a probe that recorded an errno instead of a
verdict — the same shape of check as reading stdout and stderr separately rather than
trusting the terminal.

## Patch: one rule set, two engines — and the policy that was never delivered

Phase 04 reported that `DENIED_BASH` and `hooks/guard.py` had drifted apart: after the
hook learned that a bench subcommand with no `--site` still acts on a site, the hook asked
about seventy-six of them and this dispatcher denied four. A delegated OpenCode run
therefore had **wider** access to live sites than Claude had. Authorised as a Phase 03
patch, with the contract amended, because the rule set spans two phases' files and neither
phase could fix it alone.

**The fix is not a third copy.** Copying the subcommand list into `DENIED_BASH` would have
restored agreement until the next edit to either side — the copy is the defect.

### `config/command-boundaries.json`

Nine rules, each carrying what it is about and why, what the hook decides, what a
delegated run decides, which skill section documents it, and the commands it must and
must not catch. No glob patterns, no token sets: the data describes the rule, and each
consumer translates it.

- `hooks/guard.py` reads it into token matching — program, subcommand, options, an
  identifier anywhere in the text. It no longer owns a single rule; it owns the matching,
  the reason text a blocked agent reads, and the option sets that say which token is the
  subcommand.
- `scripts/delegate` reads the same file and generates the OpenCode bash patterns.
  Translation subtleties stay here, where they belong: `git add .` expands to the exact
  command and `git add . *`, never `git add .*`, which would also deny `git add .gitignore`
  — staging one dotfile by name is precisely what that rule should leave alone. The old
  hand-written set had `git add -- .*` and denied it.

172 patterns are generated where 22 were written by hand, and the four-versus-seventy-six
divergence is gone by construction.

**Failure modes differ on purpose.** If the data cannot be read, the dispatcher **refuses
to run** (exit 2): nothing is watching a delegated run, so a run without its policy has no
boundary at all. The hook instead degrades to asking on the programs the rules are about,
because a human is there to answer, and because a hook that silently enforces nothing is
the one failure this design cannot have.

### The drift test

`check_command_boundaries()` in `tests/test_parser.py` fails **by rule name** when a rule
is not enforced by a consumer that declares a decision for it, when either engine's
translation drops it, when the two engines disagree about one of its own examples, when a
hook-enforced rule has no reason text, or when the skill section it names does not exist.
Every one of the seventy-six bench subcommands is checked through both engines, not
sampled.

Five deliberate regressions were introduced to confirm it fails loudly, and the fourth is
the one worth recording: setting `site-unnamed`'s `delegated` decision to `null` — the
exact state that caused this patch — **passed silently**. A null read as "not applicable",
and nothing asked why. So a null decision now requires a stated reason in
`not_enforced_because`, and the four legitimate ones carry theirs. That test only became
able to catch the bug it was written for after being tested against it.

The suite also rejected a bad example in the data on its first run: a `bench execute`
command carrying a `frappe.connect()` snippet is caught by the bench rules first, by
precedence. The rule was right and the example was wrong.

### The finding underneath: the policy was never reaching OpenCode

The live verification asked for a previously-permitted command to be refused. It was not
refused — and neither was anything else, because **the permission policy was not in force
at all**.

| Check | Result |
| --- | --- |
| `opencode debug config` with the policy in `OPENCODE_CONFIG_CONTENT` | **0** bash rules resolved — not the denies, not even the `"*": "ask"` base |
| A marker key (`username`) sent the same way | Never landed; the CLI's config was untouched |
| The same config via `OPENCODE_CONFIG` (a file path) | Landed correctly — so the CLI works, the variable was not arriving |
| Live delegated run, before the fix | `bench migrate` and `bench list-apps` **executed**; 0 permission refusals in the transcript |

The cause is the WSL boundary. The `opencode` on this machine is the Windows build, and
WSL hands an environment variable to a Windows process only if `WSLENV` names it.
`OPENCODE_CONFIG_CONTENT` was set in an environment the CLI never saw. With `--auto`
approving everything not explicitly denied, and nothing denied, a delegated run had
unrestricted shell access.

**This is worse than the divergence that prompted the patch**, and it invalidates the
runtime verification recorded above: that verification passed, so the delivery worked
then. What changed between is not established — the CLI is now 1.18.18 and the binary
still contains the variable's name, so the likeliest explanation is a change of which
`opencode` is on PATH rather than a change in the CLI.

**The fix is one variable**, in `adapt_opencode`:

```python
env["WSLENV"] = "%s:OPENCODE_CONFIG_CONTENT/w" % existing   # /w is WSL -> Win32
```

`/w` is the direction that matters; `/u` is the opposite one and does nothing here, which
cost a probe to discover. No path translation — the value is JSON, and `/p` would mangle
it. On a pure-Linux machine `WSLENV` is simply unused, so the line is inert rather than
conditional.

`--dry-run` now reports `WSLENV` alongside the policy, because a delivery variable that
does not appear in the dry run is how a policy goes missing without anyone noticing.

**Switching to `OPENCODE_CONFIG` was tested and rejected.** It is delivered correctly, but
it sits *below* a project's own `opencode.json`: with a hostile project config in place,
the resolved rules were `"*": "allow"` and every denied pattern re-allowed. That is
Finding B above, reproduced exactly. The precedence argument that chose
`OPENCODE_CONFIG_CONTENT` was right; only its delivery was broken.

### Verified against the real CLI

Same isolated repository, same brief, hostile `opencode.json` deliberately left in place —
`"*": "allow"` plus `bench migrate*` and `git push*` allowed, at both levels.

| | Before the fix | After |
| --- | --- | --- |
| Permission refusals in the transcript | 0 | `bench migrate` refused, with `{"pattern":"bench migrate*","action":"deny"}` in the rules the agent was shown |
| Bench commands that reached the shell | 2 | **0** |
| Positive control (`git status --porcelain`) | ran | ran |
| Rules the agent was shown | — | 347, of which exactly one is an `allow`: `--auto`'s own `{"permission":"*","action":"allow","pattern":"*"}` |
| Hostile config's six `allow` rules | — | none survived |

The deny beat `--auto`'s blanket allow in the same resolved rule set, and the project's own
configuration contributed nothing.

### Also observed: a delegated OpenCode run executes in PowerShell

The transcripts show commands running under PowerShell against `//wsl.localhost/Ubuntu/...`
UNC paths, not in the Linux shell. Two consequences, neither fixed here:

- **Linux-side tooling is absent.** `bench` is "not recognized as the name of a cmdlet",
  so a delegated run cannot execute the project's own commands on this machine even when
  permitted to.
- **Git refuses the work tree.** `git status --porcelain` fails with `detected dubious
  ownership` over the UNC path, so a delegated implementer cannot read the repository state
  it is supposed to be changing.

That is an environment fact rather than a plugin defect, but it bears directly on whether
delegated implementation works here at all, and it is not visible in a result that reports
`status=completed`.

### Patch verification

| Check | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `python3 tests/test_parser.py` | `38 cases, 3 timed, 8 strip, 9 boundary rules, mode matrix, adapters and --cwd checked` … `ok`, exit 0 |
| Hook payload matrix, 51 payloads | 0 failures — every decision identical to before the rules moved out of the file |
| `frappe.db` word boundary | `frappe.db.sql(1)` asks; `echo frappe.database` passes through, as with the previous regex |
| Degraded hook (data unreadable) | `bench migrate`, `git push`, `mysql` → ask with an explicit reason; `ls -la`, `npm test` → pass through |
| Dispatcher with the data missing | Exit 2, refuses to delegate |
| Generated policy | 173 bash rules at both levels, base `"*": "ask"`, no `allow` |
| Five regression probes | Four fail by name; the fifth exposed the gap in the test itself, now closed |
| Live delegated run | See the table above |
