---
name: project-context
description: "Use when working in a Frappe/ERPNext or Next.js repository and you need to know what the project is, how it is structured, or what a change might break — reading or creating docs/ai-context/, onboarding an unfamiliar repository, working out which areas a task affects, choosing which tests to run, or updating project documentation after a change."
---

# Project context and impact

AI context is a navigation layer, not a replacement for the repository. The code and
configuration are the source of truth. Context exists so the same discovery work is not
repeated on every task, and so a change can be reasoned about before it is made.

## Where context lives

```text
docs/ai-context/
├── PROJECT.md        orientation
├── ARCHITECTURE.md   what matters for change impact
└── OPERATIONS.md     how to run, test, and verify
```

Inside the project repository, Git-tracked, committed and pushed with it. A clone on
another machine recovers the context with the code.

Three files only. Do not add a fourth unless one of them has become genuinely unmaintainable.

**Never write a secret into these files.** Paths, site names, app names, and bench
locations are fine. Keys, passwords, API secrets, tokens, and credentials are not.

**Current truth, not history.** No timestamps, no changelog entries, no "last updated by",
no task journals. Git records history already.

## Reading context

When `docs/ai-context/` exists:

```text
Task → read the relevant context → determine likely affected areas
     → targeted repository reads → proceed
```

Read the sections that bear on the task, not all three files by reflex. Context gives
orientation; the task decides which source files to open. **Never re-scan the whole
repository because a task arrived.**

## Bootstrap

When `docs/ai-context/` does not exist and meaningful work is starting, create it once,
before continuing with the task.

Templates:

```text
${CLAUDE_PLUGIN_ROOT}/skills/project-context/templates/
```

Copy the three files into `docs/ai-context/`, fill them from the analysis below, and
delete the hint comments as you replace them. Keep the length caps written at the top of
each template.

**A nearly empty project is the exception.** After `bench new-app` or a fresh scaffold
there is nothing worth documenting. Use the user's plan or specification, implement, and
bootstrap once real structure exists. Do not document empty scaffolding. Report this as
`context: absent` in the orchestration preamble — it is absent — and say in one line that
bootstrap is waiting for structure.

### Initial repository analysis

Architecture-level, not an exhaustive read. First identify project type, major
directories, entry points, configuration, dependencies, tests, architecture boundaries,
and critical business areas. Then read only the code needed to understand those.

Frappe/ERPNext starting points: `hooks.py`, `modules.txt`, `pyproject.toml`,
`requirements.txt`, `package.json`, doctype directories, api modules, overrides, patches,
`public/`, `templates/`, `www/`, `tests/`, README and existing docs.

Next.js starting points: `package.json`, `src/app/`, `src/pages/` where used,
`src/components/`, `src/lib/`, `src/services/`, middleware, API routes, tests, build and
tooling configuration, README and existing docs.

Not every project uses every structure listed. Inspection stays targeted.

### Who runs the analysis

Claude performs the onboarding analysis directly, read-only, using the strategy above.
Once the Phase 03 dispatcher exists, it is delegated to Codex in REVIEW mode — read-only,
targeted repository analysis rather than diff review, returning concise structured
findings that Claude validates.

Claude owns the resulting context in both cases. A project Claude built from the start
needs no onboarding scan; write the context directly.

### Incomplete understanding

Document only verified architecture. Do not invent conclusions, and do not write an
assumption as a fact. Unclear areas are inspected later, when a task requires them. The
context grows with real work.

## Impact analysis

Every task gets an impact analysis before implementation, stated as one visible line:

    Impact: <area> | affected: <direct> | risks: <what could regress> | verify: <checks>

It is required for every tier. On a FAST task it is short and that is correct:

    Impact: customer form label | affected: form render | risks: none | verify: reload the form

On NORMAL and DIFFICULT tasks each field carries more, and targeted reads may be expanded
before implementing — shared business logic, integrations, permissions, data integrity,
migration behaviour, and cross-module features earn deeper inspection. Do not perform
architecture-wide analysis for a trivial change.

The line is derived from the request, the AI context, targeted reads, and the task
requirements. It is ephemeral working state: it is not written into the repository, and no
dependency graph, impact database, or code map is created to produce it.

Before delegating, send the implementer the affected area, its direct dependencies, and
the known regression risks. Blind implementation is what this prevents.

## Post-implementation impact validation

After implementation, impact is recalculated against the real diff — by Codex once the
Phase 03 dispatcher exists, and these are the rules it executes.

Inputs: the preliminary impact line, the actual Git diff, the AI context, and targeted
code inspection.

Verify:

- what actually changed, as opposed to what was planned
- whether the implementation touched unexpected areas
- what could regress
- which tests are now appropriate
- whether further targeted inspection is needed

**The real diff outranks the original plan.** Where they disagree, the diff is what
happened.

## Targeted regression strategy

The default is affected tests plus targeted regression checks — not the whole suite after
every change.

Test selection follows the changed files, the affected business behaviour, shared
dependencies, the architecture context, known risky areas, and the tests the repository
actually has.

The full suite runs only with a stated reason: shared or core behaviour changed, the
affected surface is broad, a schema or migration change has wide reach, infrastructure
behaviour changed, several major modules are involved, or targeted tests cannot give
enough confidence. Escalating verification scope requires naming which of these applies.

## Context update rule

After a task passes review, answer one question: **did this change what a future developer
or agent needs to know to understand the project correctly?**

If no, do not touch the context. Most tasks are no: CSS adjustments, wording changes,
isolated UI tweaks, trivial bug fixes, internal refactors that change no important
structure or behaviour.

If yes, update only the affected section:

- **ARCHITECTURE.md** — an important new DocType, API, integration, or hook; a changed
  permission model; a new background job; a changed major data flow; a new shared service;
  an architectural business-rule change.
- **OPERATIONS.md** — a new required test command, a build or setup change, a development
  workflow change, a new operational requirement.
- **PROJECT.md** — a new major module, a change in application scope, a new primary
  technology, an important structural reorganization.

## Stale context

The repository always overrides the context files. When a targeted read contradicts what
the context says:

```text
trust the repository → verify the actual behaviour
→ update the affected context section → continue
```

Never change code to match outdated documentation. Detecting staleness is a side effect of
normal targeted reads; it does not justify a full rescan.
