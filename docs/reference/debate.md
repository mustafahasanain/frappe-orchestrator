# Debate Mode

Two independent, read-only architectural advisers — Claude Opus and Codex — answer one
hard design question **before** implementation, then the orchestrator decides. It is an
exception, not a workflow stage: it costs two stages of up to 15 minutes each, and it was
used once in the audit window.

```text
user request, or DIFFICULT + a genuine architectural fork (tell the user first)
   ↓
Stage 1  Opus position   ‖  Codex position     same brief, neither sees the other
   ↓
Stage 2  Opus critiques Codex  ‖  Codex critiques Opus     one round, no third
   ↓
The orchestrator decides  →  synthesis.md
   ↓
The normal implementation, then the normal review gate
```

## When it runs

- The user asks for a debate: `--trigger user-request`, any tier.
- A DIFFICULT task where one of these genuinely applies, and the user has been told:
  `architectural-ambiguity` (the right structure is not settled by the request, context or
  code), `competing-approaches` (materially different viable approaches with real
  trade-offs), `high-risk-decision` (expensive to reverse, or security, permission,
  data-integrity or migration risk). The dispatcher refuses these triggers on other tiers.

**Difficulty alone is never a trigger.** Hard debugging with one clear approach, a large
but straightforward change, CRUD, UI work and ordinary validation are implemented, not
debated. A request for "a second opinion" on existing code is a review, not a debate.

## Running it

```text
${CLAUDE_PLUGIN_ROOT}/scripts/debate --tier <TIER> --trigger <reason> --cwd <repository root>
```

The brief on stdin is the same short brief for both advisers: the goal, the affected area,
constraints, known risks, and the architectural question, stated as a question. No source
files and no preferred answer. Run it in the background. Before starting, emit:

    Debate: enabled | reason: <trigger> | participants: Claude Opus + Codex

## What is enforced in code

- **The Opus side is Opus.** The Claude adviser runs as `claude -p --model opus` (the alias
  in `deliberation.claude_model_alias`), and the run's own usage report must show a model
  starting with `deliberation.claude_model_prefix` producing the answer, with nothing but
  Claude Code's housekeeping model beside it. A new Opus release needs no edit.
- **Read-only.** Claude has Read, Grep and Glob only, every other tool denied, no MCP, no
  skills, the target repository's settings ignored. Codex runs in its read-only sandbox.
- **Independence and the bound.** A position accepts no other answer; a critique accepts
  only the two usable positions answered from the same brief. No third round can be built.
- **No verdict.** A volunteered verdict, `winner` or `final_decision` is removed.
- **Signals.** SIGTERM, SIGHUP or SIGINT to the runner is passed to both dispatchers, which
  stop their agents; the result is `interrupted`.

## Reading the result

Exit 0 and `status: complete` only when all four runs were usable. Exit 3 otherwise.

`incomplete` or `interrupted` means there was no debate. `failures` names the adviser, stage
and reason. Whatever was usable is kept under `partial`, for the record only: **one
adviser's answer is not a debate and is never presented as one.**
Do not fabricate the missing side, and do not rerun automatically. Emit:

    Debate: incomplete | <adviser> <stage>: <reason>

Then decide as you would have without it, or put the question to the user.

## Synthesis

The orchestrator decides, not an adviser, and writes the decision to the `synthesis` path
in the result: the selected approach and why, what was taken from each adviser, rejected
alternatives, remaining risks, implementation constraints, verification expectations.
Then one line:

    Debate: complete | decision: <one-line summary>

The synthesis becomes the architectural part of the implementation brief. It is not a
review and never counts as one: after implementation the review gate decides about a
fresh `review` run on the actual diff, and the reviewer is not shown the debate.
