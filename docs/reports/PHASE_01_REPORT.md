# Phase 01 Report

## What was built

- `.claude-plugin/plugin.json` — plugin manifest (`name`, `description`, `version`, `author`, `keywords`). The only file in `.claude-plugin/`. Declares no component paths, so root-level `skills/` is discovered by convention.
- `.gitignore` — ignores OS junk, editor state, logs, local env files, and `.claude/settings.local.json`.
- `skills/orchestration/SKILL.md` — the orchestration skill. Encodes agent roles, task classification, model-routing lookup, escalation ladder, fast path, delegation-brief and result rules, the bounded 3-attempt implementation/review loop, debate rules, dirty-working-tree isolation, commit safety, the push boundary, deployment-request handling, and the autonomy boundary.
- `config/model-routing.json` — central routing data: four task tiers (model + effort + description), the ordered `escalation_ladder`, and `special_models` for Kimi K3. Data only; no logic, no commands, no execution instructions.
- `docs/reports/PHASE_01_REPORT.md` — this report.

## Spec coverage

| Requirement (Phase 01) | Status | Note |
| --- | --- | --- |
| Claude as orchestrator; responsibilities enumerated | Implemented | `## Roles → Claude` |
| OpenCode as default production-code implementer | Implemented | `## Roles → OpenCode` |
| Codex as independent reviewer; must not modify production code | Implemented | `## Roles → Codex` |
| Task classification FAST / SMALL / NORMAL / DIFFICULT, no separate classifier | Implemented | `## Task classification` |
| Reclassification on unexpected complexity | Implemented | `### Reclassification` |
| Model routing defined in one central location | Implemented | `config/model-routing.json`, referenced as `${CLAUDE_PLUGIN_ROOT}/config/model-routing.json` |
| Per-tier default models and effort levels | Implemented | `tiers` in the routing file |
| DIFFICULT effort medium, raise to high on risk | Implemented | `effort` + `effort_upgrade` |
| Kimi K3 as selective, non-default model | Implemented | `special_models` + `### Kimi K3` |
| Deterministic, conservative escalation ladder | Implemented | `escalation_ladder` + `### Escalation ladder` |
| Claude Opus only as exceptional escalation | Implemented | Last ladder entry; conditions stated in the skill |
| Fast path for FAST/SMALL, with the "must not" list | Implemented | `## Fast path` |
| Delegation contract: concise briefs, no large source dumps | Implemented | `## Delegation briefs` |
| Concise result fields (status, summary, files, commands, failures, concerns, exit status) | Implemented | `## Delegation briefs` |
| Implementation/review loop, max 3 attempts, attempt-2 brief carries only new findings | Implemented | `## Implementation / review loop` |
| Stop condition with blocker / findings / attempts / root cause / next action | Implemented | `### Stop condition` |
| Debate is exceptional; never for FAST/SMALL; max 1 round; then user decides | Implemented | `## Agent debate` |
| Dirty working tree isolation: clean / safe-to-continue / must-stop | Implemented | `## Git safety` |
| Commit safety: propose message, stage task files explicitly, never `git add .` | Implemented | `## Commit safety` |
| Push boundary: local commit automatic, push requires explicit intent | Implemented | `## Push boundary` |
| Deployment request handling and the plugin boundary | Implemented | `## Deployment request handling` |
| Autonomy boundary: allowed vs. requires confirmation; stop when unsure | Implemented | `## Autonomy boundary` |
| Only two Phase 01 components: orchestration skill + routing data | Implemented | Plus the scaffold files — see Deviations |
| Repository analysis strategy | Deferred | Phase 02 owns it; the spec defers it explicitly |
| Executable verification of the workflow (dispatcher, adapters, structured result contract) | Deferred | Phase 03 owns it; Phase 01 defines the rules those components must obey |
| Guarantees 1–12 in the acceptance criteria | Implemented | All twelve are stated as rules in the skill; 11 and 12 are also structural (working-tree sharing, no infrastructure introduced) |

## Decisions I made

- **Model names verbatim from the spec.** `config/model-routing.json` carries display names (`Kimi K2.6`, `Kimi K2.7 Code`, `Claude Sonnet 5`, `GLM-5.2`, `Claude Opus`, `Kimi K3`), not provider CLI model IDs. The spec does not give IDs, and inventing them would bake guesses into the one file that is supposed to be the single source of truth. See Open questions.
- **Attempt and debate limits live in `SKILL.md`, not in the JSON.** The contract scopes the routing file to task tiers, model names, and effort levels. Max-3-attempts and max-1-debate-round are behavioural rules, so they stay in the skill.
- **No `implementer` field per tier** (your instruction). OpenCode as default implementer is stated as a role rule in `SKILL.md`; the Claude Opus exception is carried by `escalation_ladder`.
- **`effort_upgrade: "high"` on the DIFFICULT tier** rather than a second tier entry — the spec describes one tier whose effort is raised, not two tiers.
- **`plugin.json` declares no `skills` path key.** Root-level `skills/` is discovered by convention; an explicit path key would be a second place where layout is defined and could drift from the contract's rule.
- **The frontmatter description was written for trigger breadth**, per your instruction. Exact line as shipped:

  ```
  description: "Orchestrate any request that changes a repository — features, bug fixes, refactors, renames, config edits, migrations, dependency bumps, test changes, or 'just fix this quickly' one-liners. Use before writing or delegating code: classify the task, select the implementation model from central routing, check the Git working tree for unrelated changes, delegate implementation to OpenCode, have Codex review independently, and create the local commit. Also use when asked to deploy, push, or update a server, to apply the correct boundary."
  ```

  It names concrete change types instead of the word "orchestrate" alone, states the action verbs the skill performs, and includes the deployment/push wording so the boundary rules fire on requests that would otherwise never reach this skill.

- **Section `## Not implemented in this phase` was removed from the skill** (your instruction) because the skill is read on every task and should not carry build-plan metadata. That content is under "Not built" below instead.

## Deviations

- **`GLM-5.3` → `GLM-5.2`.** The phase spec names GLM-5.3 as the fallback model. You instructed that GLM-5.3 does not exist on your provider, so the routing file uses GLM-5.2 in the fallback slot. Recorded here per your request; the spec document itself was not edited.
- **Two scaffold files outside the Phase 01 allowed list.** The build contract's Phase 01 scope allows only `skills/orchestration/SKILL.md` and `config/model-routing.json`. `.claude-plugin/plugin.json` and `.gitignore` were created on your explicit instruction — without a manifest the plugin cannot load at all. Flagged rather than assumed.

## Open questions

1. **Provider CLI model IDs.** Phase 03's adapters will need real IDs for each name in the routing file. Decide whether the mapping goes into `config/model-routing.json` as an added field per tier, or into the adapters. My recommendation: add an `id` field per entry in the routing file, so the "one central location" rule keeps holding.
2. **Effort for the two lowest-traffic ladder rungs.** The spec gives no effort level for the `GLM-5.2` fallback or for `Claude Opus`. I set both to values I judged reasonable (`medium` and `high`). Confirm or override.
3. **GLM-5.2's position.** The spec places the fallback *after* Claude Sonnet 5 and *before* Claude Opus. Confirm this is right for your provider — a fallback usually implies "when the previous rung is unavailable" rather than "strictly stronger than the previous rung", and Phase 03 will need to know which meaning to implement.
4. **Skill invocation.** The skill relies on description-based triggering only. If you want a deterministic entry point (`/orchestrate`), a `commands/` entry would be needed — no phase currently allocates one.

## Not built (correctly out of scope)

- Delegation dispatcher — Phase 03.
- OpenCode and Codex agent adapters — Phase 03.
- Structured brief and result contract implementation — Phase 03. Phase 01 states the required fields as rules only.
- Any script that invokes an external CLI — Phase 03.
- `docs/ai-context/` templates (`PROJECT.md`, `ARCHITECTURE.md`, `OPERATIONS.md`) and the context skill — Phase 02.
- Impact mapping, regression test selection, repository analysis strategy — Phase 02.
- Frappe operations skill — Phase 04.
- Deployment logic, deployment configuration, infrastructure or server state, server automation — permanently out of scope, no phase owns these.
- Agent servers, message brokers, databases, queues, workflow engines, persistent task state — permanently out of scope.

## Verification

| Command | Result |
| --- | --- |
| `claude plugin validate .` | `✔ Validation passed` (exit 0) — validated `.claude-plugin/plugin.json` |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) — no warnings, no unrecognized fields |
| `claude plugin validate skills --strict` | `✔ Validation passed` (exit 0) — `skills/orchestration/SKILL.md` frontmatter accepted |
| `node -e "JSON.parse(...)"` on `config/model-routing.json` | `valid json` |
| `ls -A .claude-plugin` | `plugin.json` only — layout rule holds |
| `find . -type f` (excluding `.git`) | `skills/` and `config/` are at the repository root, not inside `.claude-plugin/` |
| `git status --porcelain` before starting | Empty — clean working tree, nothing pre-existing was staged or reverted |

## Patch: skill activation

The plugin loaded correctly (`plugin list` reported `loaded`), but the skill did not
activate on a real request. In a Frappe repository, `fix the label on the customer form,
it says "Cusomter"` produced ordinary behaviour: no task classification, no model
selection, no delegation. The skill was never read.

The cause was the frontmatter description. Skill activation matches the user's request
against the description, and the original text described what the skill *does* rather
than *when* it applies — it opened on "Orchestrate any request that changes a
repository" and then spent most of its length on internal mechanics (classification,
central routing, working-tree check, OpenCode delegation, Codex review, commit). A
request phrased as "fix the label, it says Cusomter" resembles none of that wording, and
the length diluted what signal there was.

**Old description** (566 characters):

> Orchestrate any request that changes a repository — features, bug fixes, refactors, renames, config edits, migrations, dependency bumps, test changes, or 'just fix this quickly' one-liners. Use before writing or delegating code: classify the task, select the implementation model from central routing, check the Git working tree for unrelated changes, delegate implementation to OpenCode, have Codex review independently, and create the local commit. Also use when asked to deploy, push, or update a server, to apply the correct boundary.

**New description** (206 characters):

> Use for any request to change, add, fix, rename, refactor, or remove something in a Frappe/ERPNext or Next.js repository, including small one-line fixes and typos. Also use when asked to deploy or push.

Rationale:

- **Leads with the trigger condition, in the user's vocabulary.** The opening clause is
  the set of things a user asks for, not the procedure the skill runs.
- **Names the concrete context** — Frappe/ERPNext and Next.js repositories — rather than
  the abstract "a repository", which gives the match something specific to bind to.
- **States the small-task case explicitly.** "including small one-line fixes and typos"
  covers the class of request that failed, without a keyword list; matching is semantic,
  so near-synonyms of the opening verbs add noise rather than coverage.
- **Mechanics removed entirely.** Routing, delegation, review, and commit are rules for
  the skill body, not activation signal. They remain in the body, unchanged.
- **Deploy/push boundary retained** as one short trailing clause.

Nothing else changed: the skill body, `config/model-routing.json`, and
`.claude-plugin/plugin.json` are untouched. Open question 4 above still stands — this
patch improves description-based triggering but does not make invocation deterministic.

### Patch verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `claude plugin validate skills --strict` | `✔ Validation passed` (exit 0) — new frontmatter accepted |
| `git diff --stat` before commit | `SKILL.md` — 1 insertion, 1 deletion (the description line only) |

## Patch: compliance

The activation patch above fixed loading — the skill now triggers on a plain request. The
following test run then failed on compliance. The agent loaded the skill, skipped task
classification and model selection entirely, implemented the change itself rather than
delegating, and ran Python via `bench console` against all three live sites without being
asked.

Its stated reason was that a typo was too small to be worth the workflow. The skill
already said the opposite in two places — the opening paragraph ("including small ones")
and the FAST tier definition ("mechanical one-line changes"). Both were read and treated
as boilerplate.

A third restatement was therefore rejected as the fix. Prose that has been ignored twice
does not start working when repeated a third time, and emphasis is not a mechanism. Both
changes below are structural: one makes compliance visible, the other narrows a boundary
that was too wide.

### 1. Required preamble

New `## Required preamble` section, placed immediately after the opening paragraph so it
is read before any other rule. It requires a single line before acting on any task the
skill applies to:

    Orchestration: <TIER> | model: <name from routing file> | tree: <clean|dirty>

The line is mandatory, must precede the first tool call rather than appear afterwards as a
summary, and — stated explicitly — if it has not been emitted, the workflow has not
started. Reclassification emits it again with the new tier, the newly selected model, and
a short reason.

The mechanism is the point. A prose rule can be read and skipped silently; a required
visible output cannot be skipped without the omission being obvious in the transcript, to
the user and to the agent itself. The line also forces the three skipped steps to actually
happen: the tier cannot be printed without classifying, the model name cannot be printed
without reading `config/model-routing.json`, and the tree state cannot be printed without
running the `git status` check.

**Carve-out.** "Before any tool call" and "report the tree state" conflict literally,
since `git status` is itself a tool call. The section names `git status` as the single
permitted exception, because it is read-only and is what supplies the last field. The
alternative considered and rejected was `tree: <unchecked>`, which would have removed the
conflict by removing the Git safety check from the preamble's enforcement.

One sentence from the drafted wording was cut before writing: an abstract restatement that
judging a task too small was not a decision available to the agent. The concrete sentence
retained — "A one-word typo fix emits it exactly as a migration does" — carries the same
meaning, and the mandatory line is what enforces it.

### 2. Live site boundary

New `### Live site access` subsection inside `## Autonomy boundary`. That section listed
"repository inspection" under **Allowed automatically** without bounding it, which is the
gap the `bench console` fan-out went through.

The subsection makes explicit that repository inspection means reading files in the
working tree — source, Git diff, committed configuration — and stops there. Executing
against a site database or a running Frappe instance is not inspection: `bench console`,
`bench mariadb`, `bench execute`, `bench --site ... run`, and any snippet opening a Frappe
connection (`frappe.init`, `frappe.connect`, `frappe.db`, `frappe.get_doc`). Such
execution requires an explicit user request, is limited to the single site the user named
(ask if none was named), and is never fanned out across sites to hunt for something. A
closing line covers the specific failure: reading a DocType's definition means reading its
JSON in the working tree, not querying a site.

Nothing else changed. The description, `config/model-routing.json`, and
`.claude-plugin/plugin.json` are untouched, and no `commands/` entry was added — open
question 4 still stands.

### Patch verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `claude plugin validate skills --strict` | `✔ Validation passed` (exit 0) |
| `git diff --stat` before commit | `SKILL.md` — 45 insertions, 0 deletions; two inserted sections, no existing line modified |

Not verified: whether the preamble actually holds under a live run. The previous patch was
confirmed by a real request in a Frappe repository, and this one needs the same before it
can be called fixed.

## Patch: inspection coverage

A third test round ran three requests, each in its own session with `/clear` between them,
so there is no context carryover and the three results are independent.

Test 1 — "add a docstring to the top of the main python file": skill activated, preamble
emitted correctly (FAST | Kimi K2.6 | clean), and it stopped to ask which file rather than
guessing. Pass.

Test 3 — "deploy this to dev.local": skill activated, refused cleanly, explained the
boundary, distinguished writing a deploy script from running one, and flagged that the
branch is unmerged and unpushed. Pass.

Test 2 — "check if there are any customers with a missing tax id": the skill did NOT
activate. No skill-load line, no preamble. Ordinary behaviour followed — it queried
dev.local, then client.local and hub.local, without being asked and without any site being
named. The Live site access rules never applied because the skill was never read.

Because the sessions were independent, context decay is ruled out. The description is the
only variable, and the cause is a coverage gap in it, not an enforcement failure. The
description covered change verbs only — change, add, fix, rename, refactor, remove. An
inspection request ("check if", "how many", "find all", "does X exist", "look into")
matches none of them. So the skill never loaded, and the live-site boundary was silently
absent for exactly the class of request most likely to hit a database.

### The change

One clause added to the frontmatter description in `skills/orchestration/SKILL.md`:

> and equally for any request to inspect or investigate such a repository or the data in
> its sites, whether or not anything is changed

"Whether or not anything is changed" is what pulls in read-only requests; "the data in its
sites" is what makes the live-site boundary reachable for them. No keyword list was added,
and the length stays close to the previous form rather than returning to the older verbose
one.

Nothing else changed. The skill body, `config/model-routing.json`, and
`.claude-plugin/plugin.json` are untouched; no hooks and no `commands/` entry were added.

### Patch verification

| Command | Result |
| --- | --- |
| `claude plugin validate . --strict` | `✔ Validation passed` (exit 0) |
| `git diff --stat` before commit | `SKILL.md` — 1 insertion, 1 deletion; the description line only |

Not verified: whether the skill now activates on an inspection request. That needs a live
run of test 2's wording in a Frappe repository before this can be called fixed.
