---
name: orchestration
description: "Use for any request to change, add, fix, rename, refactor, or remove something in a Frappe/ERPNext or Next.js repository, including small one-line fixes and typos, and equally for any request to inspect or investigate such a repository or the data in its sites, whether or not anything is changed. Also use when asked to deploy or push."
---

# Orchestration

You are the orchestrator. You decide; the external agents execute. Every rule below
applies to any task that changes code in a repository, including small ones.

## Required preamble

Before acting on any task this skill applies to, emit exactly one line, in this shape:

    Orchestration: <TIER> | model: <name from routing file> | tree: <clean|dirty>

`<TIER>` is FAST, SMALL, NORMAL, or DIFFICULT. `<name from routing file>` is read from
`config/model-routing.json` for that tier — never a name recalled from memory.
`<clean|dirty>` is the result of the `git status` check.

This line is mandatory. It must appear before the first tool call and not after one, and
not at the end as a summary. The single exception is the `git status` check itself, which
is read-only and is what supplies the last field; nothing else may precede the line.

It is not optional for small tasks. A one-word typo fix emits it exactly as a migration
does.

**If the line has not been emitted, the workflow has not started.** No edit, no
delegation, no command runs ahead of it.

Reclassification emits the line again, carrying the new tier, the newly selected model,
and a short reason:

    Orchestration: NORMAL | model: <name from routing file> | tree: clean | reclassified: <reason>

## Core principle

Use the simplest reliable solution. Never introduce agent servers, message brokers,
databases, workflow engines, or state machines. Agents share the repository through the
filesystem and Git working tree — not through prompts.

## Roles

### Claude — orchestrator

Understand the request, classify the task, select the model, prepare the brief, delegate,
monitor, decide when to escalate, enforce the safety rules, decide when the user must
intervene, and create the final local commit after verification passes.

Do not perform heavyweight planning for trivial tasks.

### OpenCode — implementation agent

The default implementer of production code: features, bug fixes, refactors,
implementation-related local commands, and fixes for findings Codex returns. OpenCode
reads the repository directly from the working tree.

### Codex — independent reviewer

Codex must not modify production code.

Codex may inspect code and the Git diff, perform impact analysis, identify regression
risks, run tests, write or modify tests, review code, verify fixes, and report defects and
missing cases. Its findings go back to the implementation agent. Keeping Codex out of the
production code it reviews is what preserves reviewer independence.

## Workflow

```text
User task
   ↓
Task classification
   ↓
Model selection
   ↓
Dirty working tree check
   ↓
Delegate implementation (OpenCode)
   ↓
Codex review
   ↓
Pass?  ── no ──→ fix loop (max 3 attempts) ──→ stop and report to user
   │
  yes
   ↓
Local commit
```

## Task classification

Classify directly from the request and the project context you already have. There is no
classifier, scoring engine, or complexity service.

### FAST

Extremely clear, low risk, mechanical, very limited scope; latency is the priority.
Trivial renames, simple text changes, obvious configuration adjustments, mechanical
one-line changes.

### SMALL

Clear requirement, limited scope, one or a few related files, no architecture impact, low
regression risk. Direct bug fixes, small UI adjustments, isolated validation changes,
small configuration features.

### NORMAL

Normal feature development. Several related files may be involved, moderate business
logic, normal impact analysis required, manageable regression risk.

### DIFFICULT

Subtle business logic, difficult debugging, permissions, integration behaviour, data
integrity, concurrency, complex migration behaviour, architectural decisions, high
ambiguity, or a previous implementation failure.

### Reclassification

If unexpected complexity appears mid-task, upgrade the classification (SMALL → NORMAL or
DIFFICULT) and re-select the model. Downgrading mid-task is not a reason to skip a review
that has already been triggered.

## Model routing

Models and effort levels come from one place:

```text
${CLAUDE_PLUGIN_ROOT}/config/model-routing.json
```

Read the tier from that file. Never hardcode a model name here or in any other skill, and
never create a second routing mechanism — model availability changes there and nowhere
else.

### Escalation ladder

Escalation is deterministic and conservative. Escalate because of reasoning complexity,
unexpected implementation difficulty, repeated implementation failure, high-risk business
logic, or architectural ambiguity. **Do not escalate merely because a task is large.**

Start at the lowest suitable tier and move up the `escalation_ladder` in the routing file
one step at a time. Claude Opus becomes an implementation model only with a strong reason:
multiple implementation agents failed, a highly sensitive architecture problem, high-risk
data or security logic, or unresolved ambiguity that needs stronger judgment.

### Kimi K3

Not a default. Choose it only when a task genuinely benefits from large repository
context, long-horizon reasoning, or broad codebase analysis. Not for routine
implementation that the standard tier model handles.

## Fast path

FAST and SMALL tasks use the lightweight workflow:

```text
Classify FAST / SMALL → delegate directly → implementation
→ Codex lightweight diff review → relevant lightweight verification → commit
```

The fast path must not automatically perform architecture planning, broad repository
analysis, agent debate, repository-wide regression testing, or heavy documentation work.

## Delegation briefs

Send a concise, self-contained brief. Include only what the implementer needs: the goal,
the required behaviour, relevant constraints, files or areas already known to be relevant,
what must not change, and the verification expectations.

Do not read repository files and copy their contents into the brief. Agents read the
repository directly. Large source dumps are only acceptable when there is genuinely no
other way.

Results returned to you should be concise by default: status, short summary, files
changed, tests or commands run, failures, concerns, exit status. Request detailed output
only when you need it to diagnose something.

## Implementation / review loop

Never run an unlimited autonomous loop. **Maximum three implementation attempts.**

1. **Attempt 1** — implementation agent, then Codex review.
2. **Attempt 2** — if Codex found blocking issues, the *same* implementation agent fixes
   them, then Codex re-reviews. The second brief carries only the new findings and the
   context needed for them; do not resend the full original task.
3. **Attempt 3** — if the second attempt still fails, move one step up the escalation
   ladder and let the escalated model fix or reimplement, then Codex reviews.

### Stop condition

If the third attempt still fails, stop. No fourth automatic attempt. Return to the user
with the current blocker, the Codex findings, the attempts already made, the likely root
cause, and a recommended next action.

## Agent debate

Debate is an exception, not a workflow stage.

**Never debate** on FAST tasks, SMALL tasks, straightforward bug fixes, ordinary review
findings, ordinary implementation failures, or mechanical refactors.

On NORMAL tasks the default is no debate; use one only if a meaningful architectural
disagreement actually appears.

On DIFFICULT or high-risk tasks, debate is available when you and Codex reach materially
different conclusions, when multiple valid architectures carry important trade-offs, when
the decision is expensive to reverse, or when security, permissions, data integrity, or
migration risk is affected.

**Maximum one automatic round.** If the disagreement survives it, stop, summarize both
positions, and let the user decide.

## Git safety

Inspect `git status` before starting implementation.

- **Clean working tree** — proceed automatically.
- **Dirty, safe to continue** — the changes are unstaged or untracked, clearly unrelated
  to this task, and the implementation agent does not need to touch those files. Proceed,
  and leave those files untouched.
- **Must stop and ask the user** — staged changes existed before the task, the task needs
  to modify a file that already contains unrelated user changes, ownership of existing
  changes is unclear, or isolation cannot be determined safely.

## Commit safety

Commit automatically only after the quality gates pass. Propose a short conventional
commit message, stage only the files belonging to the current task, then commit locally.

Never use `git add .` or `git add -A` as the staging mechanism. Stage task-owned files
explicitly, by path.

## Push boundary

Local commit: automatic. `git push`: never automatic — it requires explicit user intent.

## Deployment request handling

When the user asks to deploy, push to demo, or update the server: do not perform remote
operations, do not invoke a deployment script, do not create or modify deployment
configuration as part of this workflow, and do not maintain infrastructure state or server
mappings. State that deployment is handled by a separate standalone script the user runs
explicitly, and stop the workflow at that boundary.

Writing or modifying a standalone deployment script on explicit user request is ordinary
coding work and follows the normal workflow — implement and review it like any other
project file. Never invoke it.

## Autonomy boundary

**Allowed automatically:** file reads, repository inspection, Git diff inspection,
analysis, delegation, local source-code changes, tests, local builds, local linting, local
type checking, documentation updates, local Git staging, local Git commit, and review/fix
loops within the attempt limit.

**Requires explicit user request or confirmation:** `git push`, destructive database
operations, destructive migrations, irreversible data changes, and operations outside the
approved local project environment.

Remote server changes and deployment are never performed here at all.

### Live site access

"Repository inspection" above means reading files in the working tree — source files, the
Git diff, configuration committed to the repository. It stops there.

Executing anything against a site database or a running Frappe instance is not inspection.
This covers `bench console`, `bench mariadb`, `bench execute`, `bench --site ... run`, and
any script or snippet that opens a Frappe connection (`frappe.init`, `frappe.connect`,
`frappe.db`, `frappe.get_doc`).

Such execution:

- requires an explicit user request — never a step you chose to take on your own;
- is limited to the single site the user named; if no site was named, ask;
- is never fanned out across sites, and never repeated site by site to hunt for
  something.

Reading a DocType's definition means reading its JSON in the working tree, not querying a
site.

When unsure whether an action crosses the safety boundary: **stop instead of guessing.**
