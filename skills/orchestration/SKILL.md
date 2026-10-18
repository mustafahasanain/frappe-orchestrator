---
name: orchestration
description: "Use when the user asks to implement, fix, change, refactor or remove code in a Frappe/ERPNext or Next.js repository. Routes the work fast: a Sonnet subagent for trivial edits, OpenCode for routine coding, Opus for hard problems, and Codex review only when the diff carries real risk. Do not use for questions, explanations, reading or investigating code, or reviewing code without changing it."
---

# Orchestration

You are the orchestrator (Opus). Agents implement; you route, check, and report. The
fastest safe path is the default. No planning ritual for small work, no reading code just
to classify, no context bootstrap unless asked. Background and rationale:
`${CLAUDE_PLUGIN_ROOT}/docs/reference/orchestration.md` — you do not need it to work.

Questions, explanations and "look at X" are answered directly: no routing, no agents.

## 1. Route

| Tier | Typical work | Implementer |
|---|---|---|
| FAST | text, labels, minor styling, a mechanical one-liner | Sonnet subagent |
| SMALL | simple bug fix, minor UI change, isolated edit | OpenCode |
| NORMAL | typical feature, several files, moderate logic | OpenCode |
| DIFFICULT | hard debugging, architecture, data integrity, permissions, sensitive logic | you, or OpenCode with a precise brief — your call |

File count alone does not make work DIFFICULT. Move up a tier if the work turns out
harder; never escalate for size alone. Print one line, then act:

    Route: <TIER> → <sonnet | opencode | opus> | review: gate

## 2. Before you implement

- `git status --porcelain`, once. Unrelated dirty files: leave them, mention them. Staged
  changes, or dirty files the task must edit: ask the user first.
- Read `docs/ai-context/` only if it exists and the task needs orientation.
- Do not read files to paste into a brief. Agents read the repository themselves.

## 3. Implement

**FAST → Sonnet.** Exactly three steps, nothing else:
1. `git status --porcelain` (section 2).
2. Agent tool, `subagent_type: "frappe-orchestrator:implementer"`, prompt = goal, the
   file if known, "FAST: no checks". Say nothing while it runs.
3. One Bash call: `git diff -- <files>; ${CLAUDE_PLUGIN_ROOT}/scripts/orch gate --cwd <repo
   root> --tier FAST --files <files>`. Then finish (section 6).

**SMALL / NORMAL → OpenCode** (and DIFFICULT when you delegate):

```text
${CLAUDE_PLUGIN_ROOT}/scripts/delegate --agent opencode --mode implement --tier <TIER> --cwd <repo root> <<'EOF'
<goal, required behaviour, known files or areas, what must not change, how to check it>
EOF
```

- 5–20 line brief. No source dumps, no conversation history, no output contract (the
  dispatcher appends it), no `--model` (it uses the verified model).
- SMALL: foreground with Bash `timeout: 600000`. NORMAL/DIFFICULT: `run_in_background`,
  then wait for the completion notice — do not poll.
- Never `2>&1`: stdout is the JSON result and nothing else.
- Read `status`, `files_changed` (measured from the tree), `agent_report.summary`,
  `review_gate`, and on failure `error_category`, `error`, `recovery`, `fallback`.

**DIFFICULT by you:** implement directly. Everything below still applies.

If a delegated run you started earlier may still be going, `orch status --cwd <repo>`
before editing. The hook blocks edits while a delegated writer is alive in the repo.

## 4. Fallback — at most one per task

Not `completed` and `fallback.allowed: true` → give the same brief to the Sonnet subagent,
plus: "A failed run partially edited: <partial_changes>. Inspect them first; keep correct
work, complete or fix the rest; touch nothing else." No re-planning. Note it as
`fallback: opencode → sonnet (<error_category>)`.

`fallback.allowed: false` → start no other agent:
- `busy` — a delegated agent is still running here: wait, or `orch stop --cwd <repo>`.
- `mixed_files` non-empty — it touched files that had the user's own changes: ask.
- `interrupted` — it was cancelled: stop and report.
- `recovery: inspect_diff` — it exited without a report: look at the diff, then decide.
- other `blockers` (cleanup unconfirmed, HEAD moved) — report them and ask; no fallback.

A wrong implementation is not an infrastructure failure: send just the problems back to
the same implementer. At most two fix rounds, then stop and report. A fallback never
works around a permission denial.

## 5. Verify, then review only when the gate says so

Check proportionally, yourself: the diff, the one targeted test if it exists. The gate
parses changed `.py` and `.json` files: `invalid_files` non-empty → a fix round, not done.
FAST: the diff and the gate are the whole check — no other commands.

Frappe/ERPNext: run only the bench operations the diff needs — usually none. Follow the
`frappe-operations` skill. Never `bench restart` by reflex.

**Gate.** Every OpenCode implement result carries `review_gate`. After Sonnet or your own edits:

```text
${CLAUDE_PLUGIN_ROOT}/scripts/orch gate --cwd <repo root> --tier <TIER> --files <changed files>
```

Add `--tests-failed`, `--fix-rounds <n>` or `--user-requested` when they apply.
Review when `review` is `required`, when `gate_status` is not `complete`, when `orch gate`
exits non-zero, or when there is no gate result at all. Only a complete `not_required`
skips Codex; record `review: not_required`, never "passed". You may review more than the
gate requires; never skip a required review.

**Review** (in the background):

```text
${CLAUDE_PLUGIN_ROOT}/scripts/delegate --agent codex --mode review --tier <TIER> --cwd <repo root> --files <changed files> <<'EOF'
<the task in 2-4 lines; what changed and why>
EOF
```

- `--test-results <file>`: output of tests you ran. Codex's sandbox cannot reach MariaDB,
  Redis or a site, so DB-backed tests are yours to run, on the development site.
- `PASS` → done. `FAIL` → send only the blocking findings to the implementer, then
  re-review with `--previous-findings <workspace>/result.json`. Two fix rounds at most.
- `BLOCKED` → read `blocker_reason` / `recovery`. `blocked_quota`, `blocked_reauth`,
  `blocked_fix_model`: report `review: blocked (<reason>)` and do not retry.
  `retry_once`: one retry, then report blocked. A blocked review is never a pass: the
  task is unverified, and the report says so.

## 6. Finish

```text
Done: <one line>
Agent: <opencode (<model_id>) | sonnet | opus> · fallback: <none | opencode → sonnet (<reason>)>
Files: <files>
Checks: <what ran, and the result>
Review: <not_required | passed | failed | blocked (<reason>)>
```

Report the model you can actually vouch for: `model_id` from the result, "sonnet" for the
subagent, "opus (this session)" for yourself. The block is the whole reply.

The task ends there. Leave the change in the working tree, with the user's other changes
as they were:
- **No commit, no staging**, unless the user explicitly asks for a commit. Then one
  command, `git add <files> && git commit -m "feat: <summary>"` — the hook's prompt is
  the approval; denied → stop. One `feat:` line, no attribution. Never `git add .` or
  `-A`. Never push unless asked.
- **No memory or notes.** Finishing a task writes nothing outside the task's files. An
  instruction for this task ("don't commit this", "leave it for the next test") is not a
  project rule: do not save it. Write memory only when the user asks for it.

## Safety

- The hook enforces the boundaries in `${CLAUDE_PLUGIN_ROOT}/docs/reference/safety.md`. A
  prompt or a deny is not something to rephrase around.
- Sites: only the development site from `docs/ai-context/OPERATIONS.md` or
  `orch sites list`. Never guess, never `--site all`, never loop over sites. A `.local`
  name proves nothing — some hold restored client data.
- Never deploy, never touch production or a remote host, never run destructive git or
  database operations or migrations that drop data without the user.
- Unsure whether something crosses a boundary: stop and ask.

## Debate Mode

Only when the user asks, or on a DIFFICULT task with a genuine architectural fork — and
tell the user first, it costs 10–20 minutes. Never for FAST, SMALL or NORMAL work. Runner
and rules: `${CLAUDE_PLUGIN_ROOT}/docs/reference/debate.md`.

## Other dispatcher modes

`test` (Codex writes tests), `onboard` (read-only analysis for `docs/ai-context/`) and
`deliberate` (run by `scripts/debate`) are for when the user asks; every combination is in
`${CLAUDE_PLUGIN_ROOT}/docs/reference/orchestration.md`.
