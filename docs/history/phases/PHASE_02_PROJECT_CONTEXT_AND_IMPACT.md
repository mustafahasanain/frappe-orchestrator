# Phase 02 — Project Context & Impact

## Goal

Create a lightweight, repository-owned AI context system that prevents unnecessary full repository scans and improves impact-aware implementation and regression review.

This phase must enable the orchestration system to:

- understand an existing project once
- reuse that understanding across future tasks
- work consistently across multiple computers
- detect stale AI documentation
- identify likely affected areas before implementation
- help Codex select targeted tests after implementation
- avoid running the full test suite for every change

---

## Core Principle

> AI context is a navigation layer, not a replacement for the repository.

The actual repository code and configuration remain the source of truth.

The AI context exists to reduce repeated discovery work and guide agents toward the relevant parts of the project.

---

## Repository-Owned Context

AI project context must live inside the project repository.

Default structure:

```text
docs/
└── ai-context/
    ├── PROJECT.md
    ├── ARCHITECTURE.md
    └── OPERATIONS.md
```

These files must normally be:

- Git tracked
- committed with the project
- pushed with the repository
- portable between computers
- readable by all agents

This allows a developer to clone or pull the repository on another machine and immediately recover the project's AI context.

---

## Secrets Rule

AI context may describe infrastructure and project relationships, but must never contain secrets.

Allowed examples:

```text
Bench: /home/frappe/frappe-bench
Local dev site: school.local
App: a1erp_connect_client
```

Not allowed:

```text
SSH private keys
Passwords
API secrets
Access tokens
Private credentials
```

Secrets remain outside the repository.

---

## Context Files

The default structure contains only three files.

Do not create additional AI context files unless one of these files becomes meaningfully difficult to maintain.

---

## PROJECT.md

Purpose:

Provide a fast orientation to the project.

Keep it short.

Typical useful information:

- project purpose
- main technology stack
- major applications or modules
- important business areas
- main code locations
- important dependencies
- project type
- important repository conventions

Example topics for Frappe:

- apps
- major modules
- important DocType groups
- frontend/public structure

Example topics for Next.js:

- application structure
- routing approach
- major feature areas
- shared libraries
- frontend architecture summary

Do not turn `PROJECT.md` into detailed architecture documentation.

---

## ARCHITECTURE.md

Purpose:

Describe the parts of the system that matter when reasoning about change impact.

May include, where relevant:

- major modules
- important DocTypes
- APIs
- hooks
- overrides
- integrations
- permissions
- background jobs
- scheduled jobs
- critical business logic
- important data flows
- frontend structure
- shared services
- shared utilities
- important state boundaries
- known risky areas
- coupling between major areas

Only document meaningful architecture.

Do not enumerate every function, endpoint, component, or DocType merely because it exists.

---

## OPERATIONS.md

Purpose:

Describe how an agent should safely work with and verify the project.

Typical information:

- install/setup assumptions
- development commands
- testing commands
- lint commands
- build commands
- type-check commands
- project-specific verification steps
- relevant local environment assumptions
- Frappe-specific commands where applicable
- known operational gotchas

Remote deployment is intentionally outside the plugin workflow and is handled separately through explicit deployment scripts.

`OPERATIONS.md` should focus on project development, testing, verification, and local Frappe operations. It may document deployment-related context only when useful for understanding the project, but it must not define or control remote deployment.

---

## Automatic Context Bootstrap

AI context should be created automatically.

The user should not need to manually initialize every project.

### Existing Project

When Claude begins meaningful work on a repository and:

```text
docs/ai-context/
```

does not exist:

```text
Repository
    ↓
Not onboarded
    ↓
Initial repository analysis
    ↓
Create AI context
    ↓
Continue task
```

This happens only once under normal circumstances.

---

## New Project

A newly generated project should not receive meaningless AI context while it is still mostly empty.

Example:

```text
bench new-app my_app
```

At this stage:

- use the user's existing plan or specification when one exists
- begin implementation
- wait until meaningful structure exists
- then bootstrap `docs/ai-context/`

Do not document empty scaffolding.

---

## Initial Repository Analysis

Initial onboarding is an architecture-level scan.

It is not an exhaustive read of every source file.

The analysis should first identify:

- project type
- major directories
- entry points
- configuration
- dependencies
- tests
- architecture boundaries
- critical business areas

Then inspect only the code required to understand those areas.

---

## Frappe Initial Scan

For a typical Frappe/ERPNext application, likely starting points include:

```text
hooks.py
modules.txt
pyproject.toml
requirements.txt
package.json
doctype directories
api modules
overrides
patches
public/
templates/
www/
tests/
README and existing docs
```

Exact reads depend on the repository.

Do not assume every Frappe project uses every listed structure.

---

## Next.js Initial Scan

Likely starting points include:

```text
package.json
src/app/
src/pages/ when applicable
src/components/
src/lib/
src/services/
middleware
API routes
tests
configuration
build/configuration files
README and existing docs
```

Again, inspection is targeted.

---

## Initial Analysis Ownership

For an unfamiliar existing repository, once the Phase 03 dispatcher is available:

```text
Codex
→ read-only repository analysis
→ concise structured findings

Claude
→ validate important findings
→ create AI context
```

Once the Phase 03 dispatcher is available, Codex owns the initial repository analysis.

Until the Phase 03 dispatcher exists, Claude performs the onboarding analysis directly using the same targeted, read-only strategy. Once Phase 03 is available, the analysis is delegated to Codex in **REVIEW** mode as described below.

Claude owns the final repository AI context in both cases.

This onboarding analysis uses Codex **REVIEW** mode as defined in Phase 03. During onboarding there may be no implementation diff; REVIEW remains read-only and performs targeted repository analysis instead of diff review.

This keeps Phase 02 independently usable before Phase 03 while preserving Codex's review role once delegation tooling exists.

---

## Known / Newly Built Project

When Claude has already orchestrated the project from its beginning and has sufficient reliable context:

```text
Claude
→ create/update AI context directly
```

A redundant Codex onboarding scan is not required.

Codex may still verify important areas when needed.

---

## Incomplete Understanding

Initial analysis does not need to pretend that the entire repository is understood.

If parts of the project remain unclear:

- do not invent conclusions
- do not document assumptions as facts
- document only verified architecture
- inspect unclear areas later when a task requires them

The AI context should grow naturally with real work.

---

## Context Usage on Future Tasks

When `docs/ai-context/` exists:

```text
User Task
   ↓
Read relevant AI context
   ↓
Determine likely affected areas
   ↓
Targeted repository reads
   ↓
Proceed
```

Do not automatically re-scan the entire repository.

The AI context provides orientation.

The actual task determines which additional files should be read.

---

## Context Update Rule

AI context is updated only when a change modifies information that future developers or agents need to understand the project correctly.

After successful implementation and review, Claude evaluates:

> Did this task change important project knowledge?

If no:

```text
No context update
```

If yes:

```text
Update only the affected section
```

---

## Examples

### No Context Update

Examples:

- CSS adjustment
- wording change
- isolated UI tweak
- trivial bug fix with no architectural effect
- internal refactor that does not change important structure or behavior

---

### Update ARCHITECTURE.md

Examples:

- important new DocType
- new API
- new integration
- new hook
- changed permission model
- new background job
- changed major data flow
- new shared service
- architectural business-rule change

---

### Update OPERATIONS.md

Examples:

- new required test command
- build process change
- setup change
- development workflow change
- important operational requirement

---

### Update PROJECT.md

Examples:

- new major module
- major application scope change
- new primary technology
- important structural reorganization

---

## Current Truth, Not History

AI context files represent the current state of the project.

Do not add:

- timestamps for every update
- AI-generated changelog entries
- "last updated by Claude"
- task histories
- implementation journals

Git already records history.

---

## Stale Context Rule

Repository code and configuration always override AI context.

If an agent detects a conflict:

```text
AI context
    ≠
Repository code/config
```

then:

```text
Trust repository
→ verify actual behavior
→ mark context as stale
→ update affected context section
→ continue
```

Never force the repository to match outdated documentation simply because the documentation exists.

---

## Context Verification

Claude and Codex should naturally detect stale context during targeted reads.

A full repository rescan is not required.

Example:

```text
ARCHITECTURE.md says:
Order validation is handled in validation.py

Task inspection shows:
Logic moved to order_service.py

→ verify actual flow
→ update relevant architecture section
→ continue
```

---

## Impact Analysis

Every meaningful code task should have an impact analysis before implementation.

The impact analysis must remain lightweight.

Do not create a permanent dependency graph or impact database.

---

## Ephemeral Task Impact Map

Impact analysis is temporary and task-specific.

It may be derived from:

```text
User request
+ AI context
+ targeted repository reads
+ task requirements
```

Example:

```text
Changed Area:
Sales Invoice validation

Directly Affected:
- invoice validation
- submit flow

Potential Regressions:
- draft save
- submit
- cancellation
- pricing interaction

Relevant Verification:
- targeted invoice tests
- validation tests
- cancel regression check

Likely Unaffected:
- purchasing
- unrelated stock flows
```

This impact map does not need to be saved inside the repository.

---

## Pre-Implementation Impact Analysis

Before implementation:

```text
Claude
→ determines likely affected area
→ identifies direct dependencies
→ identifies likely regression risks
→ sends relevant context to implementer
```

This prevents blind implementation.

It should remain proportional to the task.

FAST tasks may have only a minimal impact assessment.

---

## Post-Implementation Impact Validation

After implementation, Codex performs impact analysis again using the real diff.

```text
Preliminary impact assumptions
+
actual Git diff
+
AI context
+
targeted code inspection
        ↓
Post-implementation impact review
```

Codex must verify:

- what actually changed
- whether the implementation touched unexpected areas
- what could regress
- which tests are now appropriate
- whether additional targeted inspection is needed

The real diff has priority over the original plan.

---

## Targeted Regression Strategy

The default is:

```text
Run affected tests
+
targeted regression checks
```

Not:

```text
Run entire project test suite after every change
```

Codex selects tests based on:

- changed files
- affected business behavior
- shared dependencies
- architecture context
- known risky areas
- test coverage available in the repository

---

## Full Test Suite

The full test suite should not run by default.

It may be justified when:

- shared/core behavior changed
- the affected surface is broad
- schema or migration changes have wide impact
- infrastructure-level behavior changed
- targeted tests cannot provide enough confidence
- multiple major modules are affected
- Codex identifies a specific reason requiring broader validation

Codex must have a reason for escalating verification scope.

---

## FAST / SMALL Impact Handling

FAST and SMALL tasks must avoid unnecessary analysis overhead.

Typical flow:

```text
Task
→ read relevant AI context
→ inspect changed area
→ lightweight impact check
→ implement
→ Codex checks diff
→ targeted verification
```

Do not perform architecture-wide analysis for a trivial change.

---

## NORMAL / DIFFICULT Impact Handling

NORMAL and DIFFICULT tasks may require deeper inspection.

Examples:

- shared business logic
- integration changes
- permissions
- data integrity
- migration behavior
- cross-module features

For these tasks, Claude may expand targeted reads before implementation.

Codex may expand regression scope after reviewing the diff.

---

## No Persistent Impact Infrastructure

Phase 02 must not introduce:

- dependency databases
- graph databases
- manually maintained code maps
- per-function impact metadata
- automated full repository indexing infrastructure
- task history database
- custom semantic search service

These may only be reconsidered if a real limitation appears later.

---

## Responsibilities

### Claude

Responsible for:

- detecting whether project onboarding is required
- reading AI context
- creating AI context
- maintaining AI context
- preliminary impact analysis
- deciding which context to send to implementation agents
- detecting when task scope requires deeper inspection

---

### Codex

Responsible for:

- initial analysis of unfamiliar repositories
- independent repository inspection
- post-implementation diff analysis
- regression risk detection
- targeted test selection
- verifying whether implementation scope matches expectations
- identifying stale or incomplete AI context when encountered

Codex remains read-only toward production code by default, as established in Phase 01.

---

### Implementation Agent

Responsible for:

- reading the relevant repository files directly
- following the provided task brief
- respecting scope
- reporting unexpected dependencies
- not performing unnecessary repository-wide exploration

---

## Scope

Phase 02 establishes:

- repository-owned AI context
- portable project knowledge
- automatic context bootstrap
- initial repository analysis
- context update rules
- stale-context safeguards
- preliminary impact analysis
- post-implementation impact validation
- targeted regression strategy

---

## Non-Goals

Phase 02 does not implement:

- full autonomous implementation/review loop
- detailed test execution workflow
- permanent impact graphs
- Frappe operational commands (covered in Phase 04)
- demo deployment
- production deployment
- remote server configuration
- task databases
- semantic repository indexing services
- generated documentation for every source file

The implementation loop and Frappe operational commands are covered by Phases 03–04. Deployment concerns — remote deployment, demo/production deployment, and server configuration — are permanently outside the plugin and are not assigned to any phase.

---

## Acceptance Criteria

Phase 02 is complete when the system can support:

```text
Existing Repository
        ↓
AI context exists?
   ┌────┴────┐
   No       Yes
   ↓         ↓
Codex      Read context
scan          ↓
   ↓       Targeted reads
Claude        ↓
creates    Impact analysis
context       ↓
   └──────→ Task proceeds
```

And for every meaningful implementation, Phase 02 defines the context and impact inputs that Phase 03 will execute:

```text
Task
 ↓
AI Context
 ↓
Preliminary Impact Map
 ↓
Targeted Implementation
 ↓
Actual Git Diff
 ↓
Codex Impact Review
 ↓
Targeted Regression Tests
```

The following guarantees must hold:

1. AI context is stored inside the repository.
2. AI context is portable across machines.
3. AI context contains no secrets.
4. Existing unfamiliar repositories are onboarded automatically.
5. Initial onboarding does not require reading every file.
6. Future tasks do not trigger unnecessary full repository scans.
7. Only important architectural/context changes update AI documentation.
8. Repository code overrides stale AI context.
9. Impact analysis is task-specific and temporary.
10. The rules for validating impact against the actual implementation diff are defined and available to Phase 03.
11. The targeted-test selection strategy is defined; its execution belongs to Phase 03.
12. No unnecessary impact-analysis infrastructure is introduced.

---

## Risks / Safeguards

### AI Context Becomes Huge

Safeguard:

Start with only three files and document only important project knowledge.

### AI Context Becomes Stale

Safeguard:

Repository code/configuration always overrides documentation.

### Context Is Rewritten After Every Task

Safeguard:

Update only when future project understanding materially changes.

### Agents Trust Documentation Blindly

Safeguard:

Targeted code reads remain required for task-specific work.

### Repository Onboarding Uses Too Many Tokens

Safeguard:

Use architecture-level inspection instead of exhaustive code reading.

### Regression Testing Becomes Too Expensive

Safeguard:

Use task-specific impact analysis and targeted tests.

### Impact Analysis Misses Unexpected Changes

Safeguard:

Codex recalculates impact using the actual Git diff after implementation.

### Project Knowledge Is Lost Between Computers

Safeguard:

AI context is committed and pushed with the repository.