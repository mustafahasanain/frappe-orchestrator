# Phase 01 — Orchestration Foundation

This architecture consists of exactly four phases: **01 Orchestration Foundation, 02 Project Context & Impact, 03 Implementation & Quality Loop, and 04 Frappe Operations**. Deployment is intentionally outside the phase system.

## Goal

Build the minimal foundation for a global Claude-based orchestration system that can delegate coding work to external coding-agent CLIs while keeping Claude as the single decision-maker.

This phase defines:

- task classification
- agent responsibilities
- model routing
- delegation boundaries
- review/fix loop
- escalation rules
- debate rules
- Git safety
- autonomy boundaries

This phase does **not** implement repository context, regression detection, Frappe operations, or deployment.

---

## Core Principle

> Use the simplest reliable solution.

The system must not introduce:

- agent servers
- message brokers
- databases
- generic workflow engines
- unnecessary state machines
- repository-wide scans for every task
- automatic debates for routine work

Agents share the repository through the filesystem and Git working tree.

Source code should not be passed between agents through large prompts unless absolutely necessary.

---

## Architecture Decision

The orchestration system will be installed globally as a Claude Plugin / Skill system.

```text
Global Claude Plugin / Skills
├── orchestration
├── delegation
├── model routing
├── review / quality workflow
└── Frappe operational skills (Phase 04)

Per Repository
├── docs/ai-context/
└── project-specific configuration
```

The orchestration logic must not be duplicated inside every repository.

Project-specific information stays inside the repository.

---

## Agent Responsibilities

### Claude Opus

Primary role:

**Orchestrator**

Responsibilities:

- understand the user request
- classify the task
- determine the required workflow
- select implementation model
- prepare concise delegation briefs
- delegate work
- monitor execution
- decide when escalation is required
- coordinate implementation/review loops
- enforce safety rules
- decide when user intervention is required
- create the final local commit after successful verification

Claude should not automatically perform heavyweight planning for trivial tasks.

---

### OpenCode

Primary role:

**Implementation Agent**

OpenCode is responsible for:

- production code changes
- refactors
- bug fixes
- feature implementation
- implementation-related local commands
- fixing findings returned by Codex

OpenCode reads the repository directly from the working tree.

Claude should send concise task briefs instead of embedding large amounts of source code.

---

### Codex

Primary role:

**Independent Reviewer**

Default rule:

Codex must not modify production code.

Codex may:

- inspect repository code
- inspect the Git diff
- perform impact analysis
- identify regression risks
- run tests
- write or modify tests when appropriate
- perform code review
- verify fixes
- report defects and missing cases

Codex findings are returned to the implementation agent.

Default loop:

```text
OpenCode
   ↓
implementation
   ↓
Codex
   ↓
review / test / verify
   ↓
finding?
   ├── yes → OpenCode fixes
   └── no  → quality gate passes
```

Codex must not normally fix the production code it is reviewing.

This preserves reviewer independence.

---

## Task Classification

Claude classifies tasks directly using the request and available project context.

No separate classifier, scoring engine, or complexity service is required.

### FAST

Characteristics:

- extremely clear
- low risk
- mechanical
- very limited scope
- latency is the priority

Examples:

- trivial rename
- simple text change
- obvious configuration adjustment
- mechanical one-line change

Default implementation:

**Kimi K2.6**

Effort:

**low**

---

### SMALL

Characteristics:

- clear requirement
- limited scope
- usually one or a few related files
- no architecture impact
- low regression risk

Examples:

- direct bug fix
- small UI adjustment
- isolated validation change
- small configuration feature

Default implementation:

**Kimi K2.7 Code**

Effort:

**low**

---

### NORMAL

Characteristics:

- normal feature development
- several related files may be involved
- moderate business logic
- normal impact analysis required
- regression risk exists but is manageable

Default implementation:

**Kimi K2.7 Code**

Effort:

**medium**

---

### DIFFICULT

Characteristics may include:

- subtle business logic
- difficult debugging
- permissions
- integration behavior
- data integrity
- concurrency
- complex migration behavior
- architectural decisions
- high ambiguity
- previous implementation failure

Default implementation:

**Claude Sonnet 5**

Effort:

**medium**

Increase to:

**high**

when reasoning complexity or risk justifies it.

---

## Special OpenCode Model

### Kimi K3

Kimi K3 is not a default implementation model.

Use it selectively when a task particularly benefits from:

- large repository context
- long-horizon reasoning
- broad codebase analysis

Do not use it for routine implementation when Kimi K2.7 Code is sufficient.

Repository analysis strategy will be defined more precisely in Phase 02.

---

## Model Escalation

Model escalation must be deterministic and conservative.

Do not use a stronger model merely because a task is large.

Escalate because of:

- reasoning complexity
- unexpected implementation difficulty
- repeated implementation failure
- high-risk business logic
- architectural ambiguity

Default ladder:

```text
FAST
Kimi K2.6
effort: low

SMALL
Kimi K2.7 Code
effort: low

NORMAL
Kimi K2.7 Code
effort: medium

DIFFICULT / First Escalation
Claude Sonnet 5
effort: medium or high

Fallback
GLM-5.3

Exceptional Escalation
Claude Opus
```

Claude Opus should only become an implementation model when there is a strong reason.

Examples:

- multiple implementation agents failed
- highly sensitive architecture problem
- high-risk data or security logic
- unresolved ambiguity requiring stronger judgment

Model routing must be defined in one central location so model availability can be changed without editing multiple skills.

---

## Fast Path

FAST and SMALL tasks use a lightweight workflow.

```text
User Request
    ↓
Claude classifies FAST / SMALL
    ↓
Delegate directly
    ↓
Implementation
    ↓
Codex lightweight diff review
    ↓
Relevant lightweight verification
    ↓
Commit
```

The Fast Path must not automatically perform:

- architecture planning
- broad repository analysis
- agent debate
- repository-wide regression testing
- heavy documentation work

If unexpected complexity appears, Claude upgrades the task classification.

Example:

```text
SMALL
  ↓
unexpected complexity
  ↓
NORMAL or DIFFICULT
```

---

## Implementation / Review Loop

The system must never use an unlimited autonomous loop.

Maximum:

**3 implementation attempts**

### Attempt 1

```text
Implementation Agent
        ↓
Codex Review
```

### Attempt 2

If Codex finds blocking issues:

```text
Same Implementation Agent
        ↓
Fix Findings
        ↓
Codex Re-review
```

The second brief should contain only the new findings and relevant context.

Do not resend the full original task unnecessarily.

### Attempt 3

If the second attempt still fails:

```text
Escalated Implementation Model
        ↓
Fix / Reimplement
        ↓
Codex Review
```

### Stop Condition

If the third attempt still fails:

```text
STOP
```

Claude must return to the user with:

- current blocker
- Codex findings
- attempts already made
- likely root cause
- recommended next action

No fourth automatic implementation attempt is allowed.

---

## Agent Debate Rule

Debate is an exception.

It is not a standard workflow stage.

### Never Debate

Do not use debate for:

- FAST tasks
- SMALL tasks
- straightforward bug fixes
- normal review findings
- ordinary implementation failures
- mechanical refactors

### NORMAL Tasks

Default:

**No debate**

Use debate only if a meaningful architectural disagreement appears.

### DIFFICULT / HIGH-RISK Tasks

Debate may be used when:

- Claude and Codex reach materially different conclusions
- multiple valid architectures have important trade-offs
- the decision will be expensive to reverse
- security is affected
- permissions are affected
- data integrity is affected
- migration strategy has serious risk

### Debate Limit

Maximum automatic debate:

**1 round**

If the disagreement remains unresolved:

```text
STOP
→ Claude summarizes the disagreement
→ User decides
```

---

## Delegation Contract

Claude should delegate using concise, self-contained briefs.

An implementation brief should contain only what the implementer needs, such as:

- goal
- required behavior
- relevant constraints
- files or areas already known to be relevant
- things that must not change
- verification expectations

Agents should read required files directly from the repository.

Avoid:

```text
Claude reads repository
→ copies large source files into prompt
→ sends them to OpenCode
```

Prefer:

```text
Claude sends concise brief
→ OpenCode reads repository directly
→ OpenCode changes working tree
```

Agent results returned to Claude should be concise by default.

Useful result information includes:

- status
- short summary
- files changed
- tests or commands run
- failures
- concerns
- exit status

Detailed output should only be requested when required for diagnosis.

---

## Git Safety

### Dirty Working Tree Isolation Rule

Claude must inspect Git status before starting implementation.

### Clean Working Tree

```text
Clean
→ proceed automatically
```

### Existing Dirty Working Tree

Claude must inspect the existing changes.

#### Safe to Continue

The task may continue when:

- changes are unstaged or untracked
- they are clearly unrelated to the current task
- the implementation agent does not need to modify those same files

Those files must remain untouched.

#### Must Stop

Claude must stop and ask the user when:

- staged changes existed before the task
- the task needs to modify a file that already contains unrelated user changes
- ownership of existing changes is unclear
- isolation cannot be determined safely

---

## Commit Safety

Automatic local commit is allowed only after the quality gates pass.

The system must:

- propose a short conventional commit message
- stage only files belonging to the current task
- create the local commit

Example:

```text
fix: preserve task-owned changes during commit
```

The system must **never use `git add .` as its default automatic staging mechanism**.

It must explicitly stage task-owned files.

---

## Push Boundary

Automatic local commit is allowed.

Automatic Git push is not.

```text
local commit
→ allowed automatically

git push
→ explicit user request required
```

Deployment is intentionally outside the plugin workflow and is handled separately through explicit deployment scripts.

---

## Deployment Request Handling

Deployment is outside the plugin and outside the phase system.

When the user requests deployment, for example `deploy this`, `push this to demo`, or `update the server`, Claude must:

- not perform remote operations
- not invoke a deployment script
- not create or modify deployment configuration as part of the normal plugin workflow
- not maintain infrastructure state or server mappings
- state that deployment is handled by a separate standalone script that the user runs explicitly
- stop the plugin workflow at the deployment boundary

If the user explicitly asks to **write or modify a standalone deployment script**, that is a normal coding task. The plugin may implement and review that script like any other project file, but it must never invoke the script or turn deployment into a workflow phase.

---

## Autonomy Boundary

### Allowed Automatically

The system may perform:

- file reads
- repository inspection
- Git diff inspection
- analysis
- delegation
- local source-code changes
- tests
- local builds
- local linting
- local type checking
- documentation updates
- local Git staging
- local Git commit
- review/fix loops within the attempt limit

### Requires Explicit User Request or Confirmation

Operations involving:

- Git push
- destructive database operations
- destructive migrations
- irreversible data changes
- operations outside the approved local project environment (excluding remote and deployment operations, which are never performed — see Deployment Request Handling)

Remote server changes and deployment are outside the plugin scope. They must be performed separately through explicit deployment scripts when the user chooses to run them.

When unsure whether an action crosses the safety boundary:

**stop instead of guessing.**

---

## Scope

Phase 01 establishes:

- global orchestration structure
- agent roles
- task classifications
- model routing
- escalation rules
- delegation principles
- bounded review loops
- debate rules
- Git isolation rules
- autonomy boundaries

---

## Non-Goals

Phase 01 does not build:

- repository AI context
- persistent project architecture documentation
- impact mapping
- regression test selection
- deployment configuration
- demo deployment
- Frappe operational commands
- production automation
- generic workflow engine
- database-backed task state
- remote agent service
- message queue
- full implementation history database

Repository context, impact mapping, and Frappe operational commands are covered by Phases 02–04. Deployment configuration, demo deployment, and production automation are permanently outside the plugin and are not assigned to any phase. Remote agent services and similar infrastructure components are also intentionally outside the plugin.

---

## Files to Create / Change

Initial implementation should keep the global plugin structure minimal.

Exact filenames should be finalized during implementation, but Phase 01 should introduce only:

- the main orchestration skill
- the central model-routing configuration file as data only, without dispatcher or agent-execution logic

The delegation dispatcher, agent adapters, and structured result contracts are built in Phase 03. Phase 01 defines the rules they must obey; it does not implement those runtime components.

Do not create project-specific context files yet.

`docs/ai-context/` belongs to Phase 02.

---

## Acceptance Criteria

Phase 01 is complete when the following rules are documented and encoded in the orchestration skill and central model-routing configuration. Executable verification of this workflow happens in Phase 03. The conceptual workflow is:

```text
User Task
   ↓
Claude Orchestrator
   ↓
Task Classification
   ↓
Model Selection
   ↓
Dirty Working Tree Check
   ↓
Delegate Implementation
   ↓
Codex Review
   ↓
Pass?
 ┌───────┴───────┐
No              Yes
↓                 ↓
Fix Loop       Local Commit
↓
Max 3 attempts
↓
Stop / Escalate to User
```

And the following guarantees hold:

1. Claude remains the orchestration authority.
2. OpenCode is the default production-code implementer.
3. Codex is independent from production-code implementation by default.
4. FAST and SMALL tasks avoid unnecessary ceremony.
5. Model escalation is predictable.
6. Debate is exceptional.
7. Automatic loops are bounded.
8. Existing Git changes are protected.
9. Local commits can be automated safely.
10. Git push requires explicit user intent, while remote deployment remains outside the plugin.
11. Agents exchange repository state through the working tree rather than large duplicated prompts.
12. No unnecessary infrastructure has been introduced.

---

## Risks / Safeguards

### Excessive Agent Usage

Safeguard:

Use the Fast Path for simple tasks.

### Token Waste

Safeguard:

Use concise briefs and direct repository reads.

### Reviewer Bias

Safeguard:

Codex does not modify production code by default.

### Infinite Fix Loops

Safeguard:

Maximum three implementation attempts.

### Unnecessary Model Cost

Safeguard:

Start with the lowest suitable model and escalate only on clear signals.

### Debate Token Waste

Safeguard:

No debates for FAST or SMALL tasks and maximum one debate round elsewhere.

### Existing Work Overwritten

Safeguard:

Dirty Working Tree Isolation Rule.

### Wrong Files Committed

Safeguard:

Explicit task-file staging; no default `git add .`.

### Dangerous Remote Action

Safeguard:

Push requires explicit user intent. Deployment remains outside the plugin and is performed only through a separately invoked deployment script.