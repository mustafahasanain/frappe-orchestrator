# Phase 03 — Implementation & Quality Loop

## Goal

Build the minimal execution loop that allows Claude to:

1. delegate implementation
2. receive a structured result
3. inspect the actual Git diff
4. run required project-specific environment operations when defined
5. re-inspect the Git diff if those operations changed the working tree
6. delegate independent review to Codex
7. run targeted verification
8. return blocking findings to the implementer
9. repeat within the bounded retry rules
10. update project context/documentation when required
11. create a verified local commit

The system must remain simple and must not become a generic workflow engine.

---

## Core Workflow

```text
User Task
   ↓
Claude Orchestrator
   ↓
Pre-task Git safety check
   ↓
Impact analysis
   ↓
Delegate implementation
   ↓
Implementation result
   ↓
Actual Git diff
   ↓
Required environment operations (if any)
   ↓
Re-inspect diff if operations changed the working tree
   ↓
Codex REVIEW
   ↓
 ┌───────────────┬───────────────┐
PASS            FAIL          BLOCKED
 ↓                ↓               ↓
Docs/context    Fix loop       Resolve safely
check              ↓           or stop
 ↓              Re-review
Commit
```

The environment-operations step is a no-op when the project requires none. Phase 04 defines which Frappe operations occupy this slot. Phase 03 provides the workflow opening but does not implement Frappe command-selection logic.

Phase 01 rules still apply:

- maximum 3 implementation attempts
- model escalation when required
- no automatic push
- dirty working tree isolation
- no unnecessary debate

---

## Delegation Architecture

Use one small global dispatcher.

Conceptual command:

```text
delegate
```

Claude uses the same dispatcher for all supported coding agents.

Example concept:

```text
delegate --agent opencode ...
delegate --agent codex ...
```

The dispatcher is responsible only for common execution mechanics.

It is not an autonomous agent.

---

## Dispatcher Responsibilities

The dispatcher may handle:

- selecting the requested CLI
- working directory
- brief delivery
- passing Claude's selected model to the CLI
- effort level when supported
- execution mode
- timeout
- process exit status
- structured result generation
- missing CLI detection
- basic execution errors

It must not contain:

- task-planning intelligence
- architecture decisions
- model-routing intelligence
- regression reasoning
- documentation logic
- Git commit decisions

Those remain Claude responsibilities.

---

## Agent Adapters

The dispatcher may contain minimal agent-specific adapters.

Initially:

```text
delegate
├── OpenCode adapter
└── Codex adapter
```

Each adapter knows only how to invoke its CLI correctly.

Shared behavior stays in the dispatcher.

Do not create a plugin framework for future agents.

Add another adapter only when another agent is actually needed.

---

## Temporary Delegation Workspace

Delegation artifacts must not pollute the project repository.

Use a temporary working location outside the repository.

Conceptually:

```text
Temporary Task Directory
├── brief.md
└── result.json
```

Optional diagnostic logs may also exist there when required.

The repository should contain only actual project changes.

Do not create persistent task folders inside the project.

---

## Repository as Shared State

Agents share code through the real Git working tree.

Do not transfer repository source code between agents through large prompts.

Preferred flow:

```text
Claude
→ concise brief
→ implementation agent reads repository
→ agent modifies working tree
→ Claude inspects Git diff
→ Codex reads same repository + diff
```

The Git working tree and project files are the shared source of state.

---

## Brief Contract

Each delegation receives a concise, self-contained brief.

The brief should include only what the agent needs.

Typical fields:

```text
Goal
Task classification
Required behavior
Relevant project context
Likely affected areas
Known relevant files when available
Constraints
Things that must not change
Verification expectations
Requested output
```

Do not copy entire files into the brief when the agent can read them directly.

---

## Implementation Result Contract

OpenCode should return a small structured result.

Minimum useful information:

```text
status
agent
model
summary
touched_files
commands_run
tests_run
warnings
exit_code
```

Detailed transcripts are not part of the normal result.

They should be retained or surfaced only when needed for debugging a failed or blocked execution.

---

## Implementation Result Meaning

The implementation agent result reports whether the agent execution itself completed.

It does **not** determine whether the implementation is correct.

For example:

```text
implementation completed successfully
```

does not mean:

```text
quality gates passed
```

Only independent verification can determine that.

---

## Actual Diff Is Authoritative

After implementation, Claude must inspect the actual repository state.

At minimum:

```text
git status
git diff
```

or appropriately scoped equivalents.

Claude must compare:

```text
Original task
+
Preliminary impact analysis
+
Implementation result
+
Actual diff
```

Do not trust only the implementation agent's summary.

---

## Codex Modes

Codex has two execution modes: **REVIEW** and **TEST**. REVIEW covers both diff review and the read-only repository analysis used for project onboarding in Phase 02. In both cases Codex is read-only toward project source files.

---

## REVIEW Mode

Default mode.

Codex is read-only toward project source files.

Responsibilities:

- inspect the actual diff when a diff exists
- perform targeted read-only repository analysis during Phase 02 onboarding when no implementation diff exists
- inspect affected code
- validate implementation against request
- perform post-implementation impact analysis
- identify regression risks
- run existing relevant tests
- run project quality gates when appropriate
- identify missing test coverage
- report findings

Codex must not modify production code in REVIEW mode.

---

## TEST Mode

Used only when additional tests are actually needed.

Codex may:

- create test files
- modify existing tests
- create temporary diagnostic test code when necessary
- execute those tests

Codex must still not modify production code.

The orchestrator decides when TEST mode is justified.

---

## REVIEW → TEST Decision

Normal path:

```text
Implementation
→ Codex REVIEW
```

If existing tests provide sufficient confidence:

```text
REVIEW
→ run relevant tests
→ PASS / FAIL / BLOCKED
```

If important coverage is missing:

```text
REVIEW
→ request TEST mode
→ Codex adds targeted tests
→ verification
```

Do not automatically write new tests for every small task.

---

## Durable Tests

A test should remain in the repository when it protects meaningful behavior against future regression.

Examples:

- reproduces a fixed bug
- protects important business logic
- verifies newly introduced behavior
- protects an integration contract
- covers a previously missing high-risk scenario

Flow:

```text
Codex writes durable test
→ test is reviewed
→ test remains in repository
→ included in same task commit
```

---

## Temporary Diagnostic Tests

Some verification artifacts are useful only during investigation.

Examples:

- quick reproduction script
- temporary debug assertion
- one-off diagnostic test
- local experiment

These must be removed before the task is committed.

Claude decides whether a test is:

```text
durable
or
temporary
```

Codex does not decide persistence alone.

---

## Review Result Contract

Codex returns one of exactly three primary states:

```text
PASS
FAIL
BLOCKED
```

No more complex state system is required.

---

## PASS

Use when:

- requested behavior is implemented
- no blocking regression issue is identified
- required tests pass
- relevant quality gates pass
- diff remains within acceptable scope

Flow:

```text
PASS
→ documentation/context check
→ cleanup
→ staging
→ commit
```

---

## FAIL

Use when implementation has a blocking correctness problem.

Examples:

- test failure caused by implementation
- regression
- requested behavior incomplete
- incorrect logic
- unsafe change
- required validation missing
- unexpected side effect
- important requirement violated

Flow:

```text
FAIL
→ send blocking findings to implementation agent
→ next implementation attempt
```

---

## BLOCKED

Use when reliable verification cannot currently be completed.

Examples:

- missing dependency
- unavailable required service
- invalid local environment
- agent timeout
- external dependency unavailable
- test infrastructure broken independently of current implementation
- required permission unavailable

A BLOCKED result must not automatically count as an implementation failure.

Claude should first determine whether the blocker can be resolved safely.

---

## Findings

Codex findings use only two categories:

```text
blocking
non_blocking
```

Avoid unnecessary severity systems.

---

## Blocking Findings

A blocking finding prevents the task from passing.

Examples:

- incorrect behavior
- regression
- failing required test
- data corruption risk
- permission problem
- missing required behavior
- unsafe implementation

Blocking findings trigger the fix loop.

---

## Non-Blocking Findings

Examples:

- optional cleanup
- style preference
- naming suggestion
- possible future improvement
- low-value refactor
- minor maintainability suggestion

Non-blocking findings do not automatically trigger another implementation attempt.

Claude may surface them to the user when useful.

Do not expand the task scope merely to eliminate every non-blocking finding.

---

## Fix Loop

Phase 01 is the single source of truth for the retry ladder and maximum of three implementation attempts. Phase 03 applies that policy without redefining it.

Operational details specific to this phase:

- **Attempt 2:** use the same implementation agent and send a concise delta brief containing only the blocking findings and relevant new context; do not resend the full original brief unless required.
- **Attempt 3:** use the escalated implementation model selected by the Phase 01 routing rules and send the blocking findings plus only the context needed to fix or reimplement the change.
- After each fix, Codex performs REVIEW again against the current actual diff.
- If Attempt 3 still returns FAIL, Claude stops and reports the request, current implementation state, blocking findings, attempts made, models used, likely root cause, and recommended next action.
- There is no automatic Attempt 4.

---

## BLOCKED Handling

BLOCKED does not automatically move through the normal failure ladder.

Claude determines the blocker type.

### Safe Local Blocker

Examples:

- dependency installation required within the project
- local test service needs starting
- generated files need rebuilding
- a required local Bench/Frappe command failed for an environment or configuration reason

Claude may resolve it automatically if the action remains inside the approved local autonomy boundary.

Then:

```text
resolve blocker
→ retry verification
```

---

## Unsafe or External Blocker

Examples:

- remote server required
- destructive database change required
- production access required
- missing credentials
- ambiguous external service

Flow:

```text
STOP
→ ask user
```

---

## Timeout

The dispatcher must support execution timeout.

Do not use one identical timeout for every task.

Timeout class follows task complexity:

```text
FAST
→ short

SMALL
→ short

NORMAL
→ normal

DIFFICULT
→ longer
```

Exact timeout values should be centrally configurable rather than duplicated across skills.

---

## Timeout Result

When timeout is reached:

```text
dispatcher
→ terminate agent process
→ result = BLOCKED
→ blocker_reason = timeout
```

Timeout is not automatically treated as bad implementation.

Claude may decide:

```text
retry
escalate
or
stop
```

based on context.

---

## No Background Infrastructure

Timeout handling must use normal process execution controls.

Do not introduce:

- watchdog service
- daemon
- queue worker
- task database
- external scheduler

The dispatcher itself is sufficient.

---

## Targeted Quality Gates

Test selection follows the impact strategy established in Phase 02.

Codex considers:

```text
actual diff
+
affected business behavior
+
AI context
+
known risky areas
+
available tests
```

Then selects the smallest verification scope that provides reasonable confidence.

---

## FAST Verification

Typical:

```text
diff review
+
small relevant check
```

Do not run heavy gates unnecessarily.

---

## SMALL Verification

Typical:

```text
diff review
+
affected tests
+
light regression check
```

---

## NORMAL Verification

Typical:

```text
diff review
+
targeted tests
+
relevant lint/type/build checks
+
affected regression checks
```

---

## DIFFICULT Verification

May include:

```text
deeper impact inspection
+
broader targeted tests
+
integration checks
+
relevant full module tests
```

Full repository test suite still requires justification.

---

## Documentation and AI Context Check

After Codex returns PASS, Claude evaluates whether the task changed important project knowledge.

Possible outcomes:

```text
No documentation change required
```

or:

```text
Update docs/ai-context/
```

or:

```text
Update developer-facing project documentation
```

Do not document trivial implementation details.

---

## AI Context Update

Phase 02 rules apply.

Update only when future agents or developers need the new information to understand the project correctly.

Possible files:

```text
docs/ai-context/PROJECT.md
docs/ai-context/ARCHITECTURE.md
docs/ai-context/OPERATIONS.md
```

---

## Developer Documentation

Separate developer documentation may be updated when a change introduces important:

- behavior
- setup
- architecture decision
- integration
- operational requirement
- gotcha
- verification procedure

The final documentation structure can remain project-specific.

Do not create documentation simply because a task occurred.

---

## Pre-Commit Cleanup

Before commit, Claude verifies:

- no temporary diagnostic files remain
- no delegation artifacts entered the repository
- no unrelated dirty files are included
- generated build artifacts are staged only when the project already tracks them in Git; otherwise they are left out of the commit
- durable tests are retained
- required documentation is updated
- Git diff matches task scope

---

## Commit Flow

After PASS:

```text
PASS
↓
Documentation/context check
↓
Cleanup
↓
Final git status/diff
↓
Stage task-owned files only
↓
Generate concise commit message
↓
git commit
```

Never default to:

```text
git add .
```

Stage only verified task-owned files.

---

## Commit Message

Use concise conventional commit style when appropriate.

Examples:

```text
fix: prevent duplicate invoice submission

feat: add customer deletion controls

refactor: simplify sync retry handling

test: cover cancelled order deletion
```

Claude owns the final commit decision.

---

## Git Push

Phase 01 boundary remains unchanged.

```text
git commit
→ allowed after verification

git push
→ explicit user request required
```

---

## Agent Result Storage

Normal task results are temporary.

Do not permanently save:

- result.json
- briefs
- agent transcripts
- retry histories
- token usage logs

inside the repository.

Git history, code, tests, and relevant documentation are the durable artifacts.

---

## Scope

Phase 03 establishes:

- one generic dispatcher
- OpenCode and Codex adapters
- temporary delegation workspace
- concise agent briefs
- structured result contracts
- Codex REVIEW mode
- Codex TEST mode
- PASS / FAIL / BLOCKED
- blocking / non-blocking findings
- targeted verification
- bounded fix loop
- timeout handling
- durable vs temporary tests
- documentation/context update gate
- verified local commit flow

---

## Non-Goals

Phase 03 does not build:

- generic agent framework
- remote agent service
- message queue
- persistent task database
- permanent task logs
- web dashboard
- token accounting system
- agent conversation archive
- Frappe operations
- deployment automation
- Git push automation
- production deployment

Frappe operational commands are defined in Phase 04 and only occupy the environment-operations slot exposed by this phase. All remote deployment, deployment automation, and production deployment remain permanently outside the plugin.

---

## Files to Create / Change

Exact names may be adjusted during implementation, but the phase should require only a minimal global structure conceptually similar to:

```text
plugin/
├── orchestration skill        # created in Phase 01; integration updates only
├── model/config definitions   # created in Phase 01; data only
├── delegate
├── adapters/
│   ├── opencode
│   └── codex
└── structured result contracts
```

Phase 03 owns the dispatcher, agent adapters, and structured result contracts. It reuses the orchestration rules and central model-routing data from Phase 01 instead of creating a second routing system.

Do not add layers unless implementation proves they are necessary.

Temporary runtime artifacts remain outside project repositories.

---

## Acceptance Criteria

Phase 03 is complete when the system can perform:

```text
User Request
   ↓
Claude classifies task
   ↓
Git safety check
   ↓
Impact analysis
   ↓
delegate → OpenCode
   ↓
Implementation
   ↓
Structured result
   ↓
Git diff inspection
   ↓
Required environment operations (if any)
   ↓
Re-inspect diff if needed
   ↓
delegate → Codex REVIEW
   ↓
PASS / FAIL / BLOCKED
```

For FAIL:

```text
Findings
→ implementation fix
→ Codex re-review
→ maximum 3 implementation attempts
```

For missing coverage:

```text
Codex REVIEW
→ TEST mode
→ targeted tests
→ verification
```

For PASS:

```text
Context/docs update if needed
→ cleanup
→ task-only staging
→ local commit
```

The following guarantees must hold:

1. One dispatcher can invoke both OpenCode and Codex.
2. Agent-specific CLI behavior is isolated in small adapters.
3. Delegation artifacts remain outside the repository.
4. Agents share code through the Git working tree.
5. Agent prompts remain concise.
6. Implementation self-reports are never treated as verification.
7. Codex remains read-only toward production code by default.
8. Codex can write tests only when TEST mode is needed.
9. Durable regression tests remain with the task.
10. Temporary diagnostic artifacts are removed.
11. Review outcome is always PASS, FAIL, or BLOCKED.
12. Blocking findings drive the fix loop.
13. Non-blocking findings do not create unnecessary work.
14. Automated implementation attempts remain bounded.
15. Timeouts are treated as blockers, not automatic implementation failures.
16. Tests are selected according to actual impact.
17. Documentation updates are proportional to the change.
18. Only verified task files are committed.
19. Git push remains outside the automatic workflow.
20. Remote deployment remains outside the plugin and phase system.
21. No unnecessary workflow infrastructure is introduced.

---

## Risks / Safeguards

### Agent Claims Success Incorrectly

Safeguard:

Claude inspects the actual diff and Codex independently verifies it.

### Codex Changes Production Code

Safeguard:

REVIEW is read-only and TEST mode permits only test-related changes.

### Every Task Creates Tests

Safeguard:

New tests are written only when meaningful coverage is missing.

### Temporary Test Pollution

Safeguard:

Pre-commit cleanup removes diagnostic-only artifacts.

### Infinite Implementation Loop

Safeguard:

Maximum three implementation attempts.

### CLI Hangs Forever

Safeguard:

Classification-aware dispatcher timeout.

### Timeout Is Misdiagnosed as Bad Code

Safeguard:

Timeout returns BLOCKED rather than FAIL.

### Huge Agent Transcripts Consume Context

Safeguard:

Structured concise results are the default.

### Repository Becomes Filled With AI Metadata

Safeguard:

Briefs, results, and runtime logs stay outside the repository.

### Review Runs Entire Test Suite Constantly

Safeguard:

Impact-aware targeted verification is the default.

### Scope Creep From Reviewer Suggestions

Safeguard:

Only blocking findings automatically trigger rework.

### Wrong Changes Enter Commit

Safeguard:

Final diff verification and explicit task-owned staging.