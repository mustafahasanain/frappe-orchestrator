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
- `hooks/` holds hook scripts and `hooks/hooks.json`, the plugin's hook configuration.
  Like `skills/`, it is discovered by convention — `plugin.json` does not point at it.
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

### Phase 01.5 — Enforcement hook

Skill activation is stochastic. When the orchestration skill does not load, none of its
rules apply. This phase moves the rules whose failure is expensive out of skill prose and
into a `PreToolUse` hook, which runs whether or not the skill was read.

Allowed:

- `hooks/` — the hook script
- `hooks/hooks.json` — the hook configuration

Nothing else. `plugin.json` is not touched.

The skill keeps the guidance; the hook makes the dangerous cases unconditional. Rules
therefore exist in both places on purpose, and the skill's wording is not weakened
because the hook exists.

The hook **decides only**. It denies blanket staging and bare coding-agent invocations,
and asks before a push or any execution against a Frappe site. It performs no operation
of its own. "Permanently out of scope" below stands unchanged and binds hooks exactly as
it binds skills: the hook must refuse deployment, never perform it.

Anything the hook does not recognise is allowed through untouched.

**Amendment after Phase 03.** The delegation dispatcher carries the central routing, the
permission policy that holds a delegated run inside these same boundaries, and the
structured result contract. A bare `opencode run` or `codex exec` typed as a Bash command
skips all three, so every boundary enforced here lapses the moment work is delegated
outside the dispatcher. The rule that closes this belongs to Phase 01.5, not to Phase 03,
which is forbidden from touching `hooks/`. This phase entry therefore also allows that
fourth rule, added to `hooks/guard.py` under the same constraints as the other three:

- It **denies**, because a correct alternative always exists — the dispatcher.
- It matches the **subcommand**, not the program, so informational invocations
  (`opencode models`, `opencode --help`, `codex --version`) pass through untouched.
- It binds commands Claude runs through the Bash tool. The dispatcher launches the agent
  CLIs as its own child processes, which are not Bash tool calls, so the dispatcher is
  unaffected by its own rule.

Later phases that add a component the hook should guard follow the same route: report the
command shape, and amend Phase 01.5 rather than widening their own scope.

**Amendment after Phase 04.** Phase 04 established which Frappe operations a change
requires, and found that the live-site rule had a hole on the side the hook could not see:
a bench subcommand that acts on a site but is given no `--site` does not stop acting on a
site — it resolves one from bench configuration, `default_site` and then `currentsite.txt`.
`bench --site x migrate` asked; `bench migrate` passed through, and acted on whichever site
the bench was last pointed at. The rule that closes it belongs here for the same reason the
fourth did, and Phase 04 is forbidden from touching `hooks/`. This phase entry therefore
also allows that fifth rule, under the same constraints:

- It **asks**, matching the `--site` form rather than being quietly weaker than it. The
  live-site boundary is not relaxed to save a keystroke.
- Its subcommand set is **derived, not judged**: every command in frappe's own CLI that
  resolves a site from configuration. "Looks dangerous" is not the test, because the
  failure being prevented is acting on a site nobody named, whatever the command does.

**Amendment: keeping the deny reason accurate.** The bare-agent deny reason states the
dispatcher invocation an agent should use instead, including the `--mode` values the
dispatcher accepts and the arguments it requires. That invocation is a fact about the
dispatcher, so a phase that changes what the dispatcher accepts or requires may update
that string here, and only that string. A
stale list is not a cosmetic problem: the reason text is the instruction an agent reads at
the moment it is blocked, so a mode missing from it is a mode the agent is told does not
exist. Any change to the hook's *rules* still belongs to Phase 01.5 alone.

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
- integration edits to earlier skills and to the context templates where the phase
  requires them

Forbidden: anything that touches a remote host.

**Amendment during Phase 04.** The third item was missing, and Phases 02 and 03 both
carry it. Without it this phase can only add a skill nothing points at: the orchestration
skill's environment-operations step would go on saying "None are defined yet, so this
step is currently a no-op" after the phase that defines them, and `OPERATIONS.md` would
have nowhere to record which site is the development site — the fact the whole
no-site-guessing rule depends on. A shipped statement that a step does nothing is worse
than no section at all, because it is read as current.

The edits stay integration-shaped: a pointer to the new skill plus the rules that must
hold when it is not read, and one hint comment in a template. This is not licence to
rewrite earlier phases' work.

---

## Testing

A `tests/` directory is allowed at the repository root, with fixtures under
`tests/fixtures/`. Nothing in `tests/` is loaded by the plugin at runtime; like `docs/`,
it exists for people working on the plugin.

Tests are for the components that **fail silently**. A dispatcher that cannot start its
CLI, a hook that denies the wrong command, a malformed routing file — all announce
themselves. A parser that quietly returns the wrong object does not, and that is what
earns a test. Do not add tests for everything else because a `tests/` directory now
exists.

Keep the harness minimal: plain Python, no framework, no dependency to install, runnable
with one command. Fixtures are real captured output, not invented samples — a fixture
tidier than reality is how a parsing defect survives.

**Precedent.** Phase 03 needed test coverage that its own file list did not allow, and
amended this contract rather than widening its scope. That is the route: a phase that
needs a file class no phase allows amends this document first, in its own section, and
records the amendment in its report. The same route Phase 01.5 took for the hook rule
Phase 03 could not add itself.

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
- Subject line under 60 characters. Add a body only when the change needs explaining;
  most do not.
- No attribution trailers of any kind. No `Co-Authored-By`, no "Generated with Claude
  Code", no tool or model name anywhere in the message. The commit describes the change,
  nothing else.
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
