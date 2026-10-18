# Phase 02 Report

## What was built

- `skills/project-context/SKILL.md` — the context skill. Defines where AI context lives
  and its secrets and current-truth rules, how context is read without triggering a full
  rescan, bootstrap (including the near-empty-project case), the targeted initial
  repository analysis and its Frappe/Next.js starting points, analysis ownership before and
  after Phase 03, the required `Impact:` line, post-implementation impact validation
  against the real diff, the targeted regression strategy and full-suite escalation
  conditions, the context update rule, and the stale-context rule.
- `skills/project-context/templates/PROJECT.md` — orientation template. Purpose, stack,
  main code locations, major areas, conventions. Length cap in a comment at the top.
- `skills/project-context/templates/ARCHITECTURE.md` — impact-reasoning template. Major
  modules, key data, APIs and integrations, hooks/overrides/jobs, critical flows, coupling
  and risky areas. Length cap in a comment at the top.
- `skills/project-context/templates/OPERATIONS.md` — verification template. Setup
  assumptions, development, tests (including how to run a targeted subset), lint/type-check/
  build, verification steps, gotchas. Length cap in a comment at the top.
- `skills/orchestration/SKILL.md` — five integration edits, all additive except the
  preamble rewording: the required preamble line gains a `context: <present|absent>` field
  and a second read-only carve-out; the reclassification line matches; the Codex role gains
  post-implementation impact review, targeted test selection, stale-context reporting, and
  onboarding analysis; the workflow diagram gains context read/bootstrap, impact analysis,
  the diff-based impact re-check, and the context-update step; a new
  `## Project context and impact` section names the context skill by path and carries the
  four rules that must hold even when it is not read; the fast path gains the context read
  and the lightweight impact check.
- `docs/reports/PHASE_02_REPORT.md` — this report.

Templates live inside the skill, not in `docs/`, because they are loaded at runtime and the
contract states that nothing in `docs/` is loaded at runtime. They are referenced as
`${CLAUDE_PLUGIN_ROOT}/skills/project-context/templates/`.

`config/model-routing.json`, `hooks/`, and `.claude-plugin/plugin.json` were not touched.

## Spec coverage

| Requirement (Phase 02) | Status | Note |
| --- | --- | --- |
| Repository-owned context at `docs/ai-context/` with exactly three files | Implemented | `## Where context lives`; three templates, and an explicit rule against a fourth file |
| Git-tracked, committed, pushed, portable across machines | Implemented | Stated in `## Where context lives` |
| Readable by all agents | Implemented | Plain Markdown in the repository; agents read the working tree |
| Secrets rule | Implemented | In the skill and repeated in each template's top comment |
| `PROJECT.md` short, orientation only, not architecture | Implemented | Template capped at ~60 lines, sections are orientation-level |
| `ARCHITECTURE.md` documents only meaningful architecture | Implemented | Cap comment states the "do not enumerate everything" rule in the file itself |
| `OPERATIONS.md` development/testing/verification, no remote deployment control | Implemented | Closing comment in the template states the boundary |
| Automatic context bootstrap when `docs/ai-context/` is missing | Implemented | `## Bootstrap`, plus the mandatory `context:` preamble field that forces the check |
| New/empty project: implement first, bootstrap once structure exists | Implemented | `## Bootstrap`; reported as `context: absent` with a one-line note |
| Initial analysis is architecture-level, not an exhaustive read | Implemented | `### Initial repository analysis` |
| Frappe and Next.js starting points, without assuming every structure exists | Implemented | Same section |
| Codex owns onboarding analysis once Phase 03 exists; Claude does it until then | Implemented | `### Who runs the analysis`, REVIEW mode named |
| Known/newly built project needs no onboarding scan | Implemented | Same section |
| Incomplete understanding: no invented conclusions | Implemented | `### Incomplete understanding` |
| Context usage on future tasks; no automatic full rescan | Implemented | `## Reading context`, and rule 1 in the orchestration section |
| Context update rule, per-file examples, affected section only | Implemented | `## Context update rule` |
| Current truth, not history | Implemented | `## Where context lives` |
| Stale context rule, repository wins | Implemented | `## Stale context`, and rule 3 in the orchestration section |
| Context verification without a full rescan | Implemented | Closing line of `## Stale context` |
| Impact analysis on every meaningful task, lightweight | Implemented | Required `Impact:` line, every tier |
| Ephemeral task impact map, not persisted | Implemented | Stated in `## Impact analysis`; nothing writes it to the repository |
| Pre-implementation impact analysis sent to the implementer | Implemented | Closing paragraph of `## Impact analysis` |
| Post-implementation impact validation, real diff has priority | Implemented | `## Post-implementation impact validation`, five verification points |
| Targeted regression strategy, Codex's selection inputs | Implemented | `## Targeted regression strategy` |
| Full suite not default; escalation needs a stated reason | Implemented | Same section, seven conditions, reason required |
| FAST/SMALL avoid analysis overhead | Implemented | Fast path flow; "no architecture-wide analysis for a trivial change" |
| NORMAL/DIFFICULT may expand reads before and regression scope after | Implemented | `## Impact analysis` |
| No persistent impact infrastructure | Implemented | None created; the prohibition is also restated in the skill |
| Claude / Codex / implementation-agent responsibilities | Implemented | Split across the context skill and the orchestration skill's `### Codex` role |
| Guarantees 1–9 | Implemented | Structural (1–3, 9) or stated as rules (4–8) |
| Guarantee 10 — diff-validation rules defined and available to Phase 03 | Implemented | `## Post-implementation impact validation` is written as the rules Phase 03 executes |
| Guarantee 11 — targeted-test selection strategy defined, execution in Phase 03 | Implemented | `## Targeted regression strategy` |
| Guarantee 12 — no unnecessary infrastructure | Implemented | Four Markdown files and one edit; no scripts, no state, no config |
| Execution of the loop, dispatcher, adapters | Deferred | Phase 03 owns it. Phase 02 defines the inputs and rules only |
| Frappe operational commands | Deferred | Phase 04 owns it |

## Decisions I made

- **Templates live in `skills/project-context/templates/`, not `docs/`.** The contract says
  nothing in `docs/` is loaded at runtime, and these are runtime resources copied into
  target repositories. Putting them in `docs/` would have broken that rule; putting them in
  the skill keeps `${CLAUDE_PLUGIN_ROOT}` referencing intact.
- **The orchestration skill names the context skill by path instead of relying on it
  activating.** Phase 01's live testing showed activation is stochastic. A second skill
  whose loading is a second coin flip would put the context rules behind two of them. The
  path reference is deterministic, and the orchestration skill also carries the four rules
  that must hold when the context skill is not read at all — the same deliberate
  duplication pattern Phase 01.5 established.
- **The context skill is read conditionally**, when `context: absent` or the task is
  NORMAL/DIFFICULT. It is ~2k tokens; loading it on every FAST typo fix would be the
  overhead this phase exists to avoid. The four inline rules cover the FAST/SMALL case.
- **`context:` is a directory check, stated as such in the skill.** Per your decision, the
  field is `present|absent` only. Wording was chosen to close the obvious escape: "a
  directory check, not a judgement."
- **The near-empty-project case reports `context: absent`** and adds one line of
  explanation, rather than getting its own field value. Absent is factually what it is.
- **The `Impact:` line uses the same shape on every tier** — `area | affected | risks |
  verify` — rather than a short form and a long form. One shape has nothing to choose
  between, and the FAST example in the skill is deliberately trivial (`risks: none`) so
  brevity is shown as correct rather than as a shortcut.
- **Length caps sit in a comment at the top of each template**, per your decision, and each
  cap comment also carries the rule most likely to be violated for that specific file
  (orientation-not-architecture for `PROJECT.md`, do-not-enumerate for `ARCHITECTURE.md`,
  secrets for `OPERATIONS.md`).
- **Caps set at ~60 / ~120 / ~80 lines.** The instantiated files are read on most tasks, so
  the caps are budget limits, not style preferences. `ARCHITECTURE.md` gets the largest
  because it carries the impact-relevant detail.
- **`OPERATIONS.md`'s test section explicitly asks for how to run a targeted subset.** The
  whole targeted-regression strategy depends on that command existing and being known; it
  is the one line in the three templates that the rest of the phase leans on.
- **No `docs/ai-context/` was created in this repository.** The templates are for target
  project repositories. Creating one here is not in the Phase 02 allowed list, and this
  repository is a plugin, not a project the orchestrator works on.

## Deviations

None.

## Open questions

1. **Verification under a live run.** The two mandatory lines are validated structurally
   only. The Phase 01 pattern held: everything shipped needed a real session before it
   could be called working. Worth testing specifically: (a) a task in a repository with no
   `docs/ai-context/`, to see whether bootstrap actually fires rather than being noted and
   skipped; (b) a FAST typo fix, to see whether the `Impact:` line survives on the tier
   where every previous rule was dropped.
2. **Nothing enforces either line when the orchestration skill does not load.** The
   Phase 01.5 hook covers dangerous Bash commands; a missing context read or impact line is
   not a Bash command and no `PreToolUse` matcher sees it. This is a real gap, and closing
   it is not in the Phase 02 allowed list — `hooks/` was explicitly excluded from this
   phase. If live testing shows the lines dropping when the skill fails to load, the fix is
   a decision for you, not something to add quietly.
3. **The duplication set has grown.** Push/staging/live-site already exist in both the
   skill and the hook. Context and impact now exist in both the orchestration skill (four
   rules) and the context skill (full rules). Each duplication was justified individually;
   the total is now four rules in two places plus three in two places, with nothing
   enforcing that they stay in sync.
4. **Codex REVIEW mode is referenced before it exists.** `### Who runs the analysis` names
   it as Phase 03 defines it. If Phase 03 renames the mode or splits onboarding analysis
   away from diff review, this section needs the corresponding edit.

## Not built (correctly out of scope)

- Persistent impact databases, dependency or graph databases, cached scan results,
  background indexers, code maps, per-function impact metadata, task history databases, and
  semantic search services — forbidden by the contract and by the phase document.
- The delegation dispatcher, OpenCode and Codex adapters, and the structured brief/result
  contract — Phase 03. Phase 02 defines the context and impact inputs those components
  consume; it executes none of them.
- Test execution workflow — Phase 03. The selection *strategy* is defined here; running the
  tests is not.
- Frappe operational commands — Phase 04.
- Any change to `hooks/` — excluded from this phase by instruction and by the contract's
  Phase 01.5 scope.
- Generated documentation for individual source files — explicitly a non-goal.
- Deployment, remote server configuration, demo and production deployment — permanently out
  of scope for every phase.

## Verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `claude plugin validate skills --strict` | `✔ Validation passed` (exit 0) — `skills/project-context/SKILL.md` frontmatter accepted alongside the existing skill |
| `wc -l -c` on the new files | `SKILL.md` 183 lines / 7,836 B; `PROJECT.md` 23 / 685 B; `ARCHITECTURE.md` 32 / 1,064 B; `OPERATIONS.md` 36 / 1,198 B. The three templates total under 3 KB — roughly 750 tokens for all three |
| `git diff --stat` on the orchestration skill | 46 insertions, 7 deletions. The only deletions are the three preamble lines that were reworded for the new field and its carve-out; every other edit is additive |
| `ls -A .claude-plugin` | `plugin.json` only — layout rule holds |
| `git status --porcelain` | `M skills/orchestration/SKILL.md`, `?? skills/project-context/` — nothing else touched; `config/`, `hooks/`, and `.claude-plugin/` unchanged |
| `git status --porcelain` before starting | Empty — clean working tree; nothing pre-existing was staged or reverted |

Not verified: live-session behaviour of the `context:` field, of bootstrap, and of the
`Impact:` line. See Open questions 1 and 2.
