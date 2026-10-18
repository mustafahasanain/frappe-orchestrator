# Phase 04 — Frappe Operations

## Goal

Define a simple and reliable way for Claude to determine which Frappe/ERPNext operational commands are required after a code change.

This phase answers:

> What Frappe operations does this change require?

It does **not** decide:

> On which remote server or production environment should they run?

Remote deployment is outside the plugin and phase system. It is handled separately through explicit deployment scripts.

---

## Core Principle

Do not run:

```text
build
migrate
clear-cache
restart
```

after every change by default.

Instead:

```text
Git Diff
+
Frappe Operation Rules
+
docs/ai-context/OPERATIONS.md
        ↓
Required Frappe Operations
```

Run only what the current change actually requires.

---

## Separation of Responsibilities

### Phase 04

Responsible for:

- detecting required Frappe operations
- deciding whether build is required
- deciding whether migrate is required
- deciding whether clear-cache is required
- deciding whether restart/reload is required
- handling local development sites
- verifying operation success

### External Deployment Scripts

Outside the plugin and phase system:

- remote servers
- SSH
- demo deployment
- production deployment
- server selection
- bench selection
- site/app deployment mapping

These responsibilities are handled only by separate scripts that the user explicitly runs when deployment is required.

---

## Decision Strategy

Claude evaluates:

```text
Actual Git Diff
+
Project AI Context
+
Frappe Operation Rules
```

The rules provide the default expectation.

The actual project configuration may override them.

Do not hardcode assumptions when the repository defines a different workflow.

Frappe operations are executed by Claude directly as **local shell commands** inside the approved local/development environment. They are not routed through the Phase 03 delegation dispatcher.

---

## Frontend Changes

Changes to Frappe frontend assets may require:

```text
bench build
```

Typical examples:

- JavaScript
- CSS / SCSS
- frontend assets
- bundled web resources
- Desk frontend code
- app assets requiring compilation

Claude should verify how the specific project builds assets using:

```text
docs/ai-context/OPERATIONS.md
```

before assuming a custom project follows standard behavior.

---

## Schema / Metadata Changes

Changes affecting Frappe metadata or database schema generally require site migration.

Examples may include:

- DocType schema changes
- field changes
- fixtures affecting metadata
- patches
- migration-related code
- schema-affecting configuration

Typical required operation:

```text
bench --site <site> migrate
```

Migration should run only against a known target site.

---

## Backend Python Changes

Python/backend changes may require process reload or restart depending on the development environment.

Do not automatically restart every time a `.py` file changes.

Determine whether the currently running development environment needs process reload.

The project-specific behavior should be documented in:

```text
docs/ai-context/OPERATIONS.md
```

---

## Cache-Sensitive Changes

Some changes may require:

```text
bench --site <site> clear-cache
```

Examples can include changes involving cached metadata, hooks, configuration, or other cache-sensitive behavior.

Do not use `clear-cache` as a universal post-change command.

Run it only when there is a reasonable reason.

---

## Operation Planning

Before executing Frappe operations, Claude produces a small internal operation plan.

Example:

```text
Required:
- build
- migrate

Not required:
- clear-cache
- restart
```

The plan does not need to be stored permanently.

---

## Automatic Execution Boundary

### Build

May run automatically when required.

Example:

```text
bench build
```

No site target is normally required.

---

### Clear Cache

May run automatically when:

- it is required by the current change
- the target development site is known

Example:

```text
bench --site <site> clear-cache
```

---

### Restart

May run automatically only when:

- the environment is local/development
- the environment is known
- the current runtime actually requires a restart/reload

Remote restart is outside this phase and must be handled by the separate deployment script when required.

---

### Migrate

May run automatically when:

- the target is a known development site
- the change genuinely requires migration
- the migration appears non-destructive
- no ambiguity exists about the target site

Example:

```text
bench --site <site> migrate
```

---

## Destructive Migration Safety

A migration must stop for user confirmation when it may involve:

- destructive schema changes
- significant data deletion
- irreversible transformation
- uncertain migration behavior
- ambiguous impact on existing data

Normal development schema migration:

```text
known dev site
+
non-destructive migration
→ allowed automatically
```

Potentially destructive migration:

```text
STOP
→ ask user
```

---

## Install App Rule

The system must never infer installation automatically.

Example command:

```text
bench --site <site> install-app <app>
```

may run only when installation was explicitly requested or is explicitly required by an approved workflow.

The presence of an app inside a bench does not imply that it should be installed on a site.

---

## Site Resolution

Any operation requiring a site must resolve the site before execution.

Claude may determine the site from:

- project context
- known bench configuration
- explicit user instruction
- reliable repository configuration

---

## No Site Guessing

A site is treated as a **development site** only when `docs/ai-context/OPERATIONS.md` explicitly identifies it as such or the user explicitly identifies it for the current task. A site name or bench membership alone is not enough to classify it as development.

If exactly one valid development site is known:

```text
resolve site
→ execute
```

If multiple sites could be affected:

```text
STOP
→ ask user
```

If the site cannot be reliably identified:

```text
STOP
→ ask user
```

Claude must never guess a site.

This applies even in development environments.

---

## Site-Independent Commands

Commands that do not require a site may run without site resolution.

Example:

```text
bench build
```

provided the correct bench/project environment is known.

---

## Multi-Site Benches

A bench may contain multiple sites.

The existence of multiple sites must not cause:

```text
migrate all sites
```

or other broad operations automatically.

Default behavior:

```text
operate only on the resolved target site
```

Broad multi-site operations require explicit intent.

---

## Multi-App Projects

A site may contain multiple apps.

Operations should remain scoped to the current task and affected application whenever possible.

Do not assume that modifying one app means all apps need operational changes.

Deployment-specific app/site mapping is outside the plugin and is handled by separate deployment scripts.

---

## Verification After Operations

Successful command execution alone is not always sufficient.

Default pattern:

```text
Run Operation
      ↓
Command exits successfully
      ↓
Relevant verification
      ↓
Operation complete
```

Verification should be proportional to the operation.

---

## Build Verification

For:

```text
bench build
```

verify at minimum:

- command completed successfully
- no build failure occurred

If the project defines a meaningful frontend smoke check, use it when appropriate.

---

## Migration Verification

For:

```text
bench --site <site> migrate
```

verify:

- migration completed successfully
- no migration exception occurred

If the project has task-specific verification related to the changed schema or behavior, run it afterward.

---

## Clear Cache Verification

For:

```text
bench --site <site> clear-cache
```

verify that the command completed successfully.

Do not add unnecessary additional checks unless the current task needs them.

---

## Restart Verification

When a development restart is required:

- ensure the restart/reload completed successfully
- confirm the relevant local service is available when a known verification method exists

Do not build a dedicated service-monitoring system.

---

## Task-Aware Operations

Frappe operations should normally happen after implementation but before final quality verification when the operation is required for tests to reflect the real changed state.

Example:

```text
Implementation
→ change requires migrate
→ migrate development site
→ Codex targeted tests
→ review
```

This prevents tests from running against stale schema.

---

## Interaction With Phase 03

Phase 03 remains responsible for:

- implementation
- review
- regression checks
- fix loop
- commit

Phase 04 adds the required Frappe operational actions into that workflow.

Example:

```text
Implementation
     ↓
Determine Frappe Operations
     ↓
Run required local operations
     ↓
Codex review / tests
     ↓
PASS / FAIL / BLOCKED
```

---

## Operation Failure

If a required Frappe command fails:

```text
operation failure
→ BLOCKED
```

unless evidence clearly shows that the failure was caused by incorrect implementation.

Claude should determine whether the problem is:

- implementation-related
- environment-related
- configuration-related
- migration-related

Do not automatically count every failed bench command as an implementation attempt failure.

---

## Project-Specific Operations

Projects may define additional required commands.

Examples:

- custom build command
- custom fixture generation
- code generation
- local service startup
- app-specific validation command

Document important project-specific operations in:

```text
docs/ai-context/OPERATIONS.md
```

Claude should prefer those documented project rules over generic assumptions.

---

## Routine Operations

Phase 04 may expose small operational skills or commands for common tasks such as:

```text
build app
migrate site
clear site cache
restart development services
install app
run Frappe tests
execute Frappe command
```

These should remain thin wrappers over existing Frappe/Bench CLI behavior.

Do not create a dedicated Frappe agent.

---

## Autonomy

### Allowed Automatically

Within a known local/development environment:

- build when required
- clear-cache when required
- non-destructive migrate on a known site
- development restart when required
- local verification
- Frappe tests
- safe read-only Bench commands

---

### Requires Explicit Intent or Confirmation

- install-app
- destructive migration
- ambiguous site operations
- multi-site broad operations
- data deletion
- irreversible database actions

---

### Never Performed by the Plugin

- remote execution over SSH
- demo operations
- production operations

These are refused rather than confirmed. Claude states that the operation belongs to a separate standalone deployment script and stops at the deployment boundary.

---

## Scope

Phase 04 establishes:

- Frappe operation detection
- rule-based command selection
- project-specific overrides
- automatic safe local execution
- migration safety
- site resolution
- no-site-guessing rule
- operation verification
- integration with the implementation/review loop

---

## Non-Goals

Phase 04 does not implement:

- SSH
- demo deployment
- production deployment
- server inventory
- remote bench selection
- project-to-server mapping
- automatic git pull on remote servers
- deployment rollback
- production restarts
- remote database operations
- generic infrastructure management

These are intentionally outside the plugin and are handled separately through explicit deployment scripts when required.

---

## Acceptance Criteria

Phase 04 is complete when the system can inspect a Frappe task and determine:

```text
What changed?
      ↓
Does it require build?
Does it require migrate?
Does it require clear-cache?
Does it require restart?
      ↓
Is a site required?
      ↓
Can the target site be resolved safely?
      ↓
Execute only required operations
      ↓
Verify success
```

The following guarantees must hold:

1. The system does not run all Frappe commands after every change.
2. Operation selection is based on the actual diff.
3. Project-specific operational rules can override generic assumptions.
4. `build` runs only when required.
5. `migrate` runs only when required.
6. `clear-cache` runs only when required.
7. `restart` runs only when the runtime requires it.
8. `install-app` is never inferred automatically.
9. Destructive migrations require confirmation.
10. Site-dependent commands never guess their target.
11. Multi-site benches are not migrated broadly by default.
12. Required operations are verified after execution.
13. Local operations remain separate from deployment.
14. No dedicated Frappe agent or unnecessary operations framework is introduced.
15. Remote, demo, and production operations are never performed by the plugin, even with confirmation.

---

## Risks / Safeguards

### Running Every Command After Every Change

Safeguard:

Diff-aware operation selection.

### Migrating the Wrong Site

Safeguard:

No Site Guessing.

### Installing an App Accidentally

Safeguard:

`install-app` requires explicit intent.

### Destructive Migration

Safeguard:

Potentially destructive migrations stop for confirmation.

### Restarting Unnecessarily

Safeguard:

Restart only when the current environment requires process reload.

### Testing Against Stale Schema

Safeguard:

Required Frappe operations run before dependent verification.

### Custom Project Workflow Is Ignored

Safeguard:

`docs/ai-context/OPERATIONS.md` overrides generic operation assumptions.

### Local Command Becomes Remote Deployment

Safeguard:

All remote execution is outside the plugin and must be handled by separate deployment scripts.