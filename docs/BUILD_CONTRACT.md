# Build Contract

This repository is a Claude Code plugin that is built **phase by phase**, under human review.

You (the building agent) implement **one phase per session**. You do not implement future
phases, and you do not invent structure that no phase asked for.

---

## Authoritative sources

| Source | Role |
| --- | --- |
| `docs/phases/PHASE_01_ORCHESTRATION_FOUNDATION.md` | Spec for Phase 01 |
| `docs/phases/PHASE_02_PROJECT_CONTEXT_AND_IMPACT.md` | Spec for Phase 02 |
| `docs/phases/PHASE_03_IMPLEMENTATION_AND_QUALITY_LOOP.md` | Spec for Phase 03 |
| `docs/phases/PHASE_04_FRAPPE_OPERATIONS.md` | Spec for Phase 04 |
| This file | How to build, what to touch, what to report |

If this file and a phase document disagree about **scope**, this file wins.
If they disagree about **behaviour or rules**, the phase document wins.

---

## Guiding principle

> Use the simplest reliable solution.

Do not add abstraction layers, config systems, state files, registries, or helper
modules unless the phase document explicitly requires them. Fewer files is better.

---

## Plugin layout rules

This is a Claude Code plugin. The layout rules are non-negotiable:

- `.claude-plugin/` contains **only** `plugin.json`.
- Every component directory (`skills/`, `agents/`, `hooks/`, `commands/`) lives at the
  repository root, never inside `.claude-plugin/`.
- Skills use the directory form: `skills/<skill-name>/SKILL.md`.
- Any path inside the plugin that must be referenced at runtime uses
  `${CLAUDE_PLUGIN_ROOT}`, never an absolute path and never a relative path from cwd.
- `docs/` is documentation and specification only. Nothing in `docs/` is loaded by the
  plugin at runtime.

A misplaced component directory makes the plugin load with no error and do nothing.
Verify placement before reporting success.

---

## Phase scope

Each phase may create or change **only** the files listed for it.

### Phase 01 — Orchestration Foundation

Allowed:

- `skills/orchestration/SKILL.md`
- `config/model-routing.json`

`model-routing.json` is **data only**. It contains task tiers, model names, and effort
levels. It contains no logic, no execution instructions, and no agent commands.

Explicitly forbidden in Phase 01:

- any dispatcher
- any agent adapter (OpenCode, Codex)
- any structured result contract implementation
- any script that invokes an external CLI
- any `docs/ai-context/` template

### Phase 02 — Project Context & Impact

Allowed:

- a context skill under `skills/`
- context file templates for the per-repository `docs/ai-context/` structure
  (`PROJECT.md`, `ARCHITECTURE.md`, `OPERATIONS.md`)
- integration edits to the Phase 01 orchestration skill where the phase requires them

Forbidden: persistent impact databases, cached scan results, background indexers.

### Phase 03 — Implementation & Quality Loop

Allowed:

- the delegation dispatcher
- agent adapters for OpenCode and Codex
- structured brief and result contracts
- integration edits to earlier skills

It must reuse `config/model-routing.json` from Phase 01. It must not create a second
routing mechanism.

Forbidden: background services, queues, daemons, persistent task databases.

### Phase 04 — Frappe Operations

Allowed:

- a Frappe operations skill under `skills/`
- any local operation helper the phase explicitly requires

Forbidden: anything that touches a remote host.

---

## Permanently out of scope

Deployment is outside the plugin and outside the phase system. Across every phase, never
create, modify, or invoke:

- remote deployment logic
- deployment configuration
- infrastructure or server state
- server automation

Writing a standalone deployment **script** on explicit user request is ordinary coding
work and is allowed. Invoking it from the plugin is not.

---

## Git rules

- Never run `git push`.
- Never run `git add .` or `git add -A`. Stage the specific files you created or changed.
- One commit per phase, at the end, after the report is written.
- Commit message format: `feat(phase-0X): <short summary>`.
- If the working tree is dirty before you start with changes that are not yours, stop and
  ask. Do not stage or revert anything you did not create.

---

## Stop conditions

Stop and ask the user instead of guessing when:

- the phase document is ambiguous about behaviour that affects file structure
- two phase documents appear to conflict
- implementing the phase would require a file outside its allowed list
- you are unsure whether something belongs to this phase or a later one

A question is cheap. A wrong structural decision costs a rewrite.

---

## Required report

At the end of every phase, before committing, write:

```
docs/reports/PHASE_0X_REPORT.md
```

Use exactly these sections:

```markdown
# Phase 0X Report

## What was built
Files created or changed, one line each, with what each is responsible for.

## Spec coverage
Table: each requirement from the phase document, and whether it is Implemented,
Partial, or Deferred. Deferred needs a reason and the phase that owns it.

## Decisions I made
Any choice the spec left open, and why I chose what I chose.

## Deviations
Anything I did differently from the spec, and why. Write "None" if none.

## Open questions
Things the user should decide before the next phase. Write "None" if none.

## Not built (correctly out of scope)
What I deliberately did not build, and which phase owns it.

## Verification
Commands run and their results — at minimum `claude plugin validate .`
```

Be honest in the report. A report that hides a gap is worse than a gap.

Do not start the next phase. End the session after the report and the commit.
