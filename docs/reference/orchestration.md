# How the orchestrator works, and why

Background for humans and for the rare task that needs it. The runtime instructions are
the orchestration skill; this page is not loaded on every task.

## Roles

| Role | Who | Model selection |
|---|---|---|
| Orchestrator | the main Claude Code session | `"model": "opus"` in `~/.claude/settings.json` (an alias, so new Opus releases need no change). `orch claude-default` shows every layer that can override it. A running session keeps its model. |
| Primary implementer | OpenCode via `scripts/delegate` | `implementers.opencode.stable_model` in the routing file, or a model the user promoted with `orch models promote`; checked against OpenCode's catalog before every run (cached for a day). |
| Light implementer and fallback | Sonnet subagent `frappe-orchestrator:implementer` | `model: sonnet` in `agents/implementer.md` (an alias). |
| Direct implementer for hard work | the Opus session itself | — |
| Independent reviewer | Codex via `scripts/delegate --mode review` | `review.codex_model` in the routing file, `orch models codex`, or Codex's own `config.toml`; checked against `codex debug models` before a run. |

## Routing

| Tier | Implementer | Review |
|---|---|---|
| FAST | Sonnet | gate: only mandatory triggers |
| SMALL | OpenCode | gate: mandatory triggers, failed tests, repeated fixes, diff larger than a SMALL task |
| NORMAL | OpenCode | gate: also integration risks (hooks, background jobs, external calls, new API surface) and very large diffs |
| DIFFICULT | Opus directly, or OpenCode | gate: also any significant code change |

FAST is three orchestrator steps: `git status`, the Sonnet subagent, then one call that
shows the diff and runs the gate (which also parses changed `.py` and `.json` files). A
task never ends with a commit or a memory write; both happen only when the user asks. In
the first real trial the FAST edit itself was done 25 s in; the end-of-task commit prompt
and the memory note written after it took the session to 134 s.

Speed came first in this design. The audit measured a median ~160 s per OpenCode run and
~135 s per Codex review, with 1.9 review rounds on average — 8–12 minutes for a SMALL task.
Most of that was review that did not need to happen. The gate removes it for low-risk
changes while keeping it, mandatory, for the changes where it caught real defects.

## The review gate

`orchlib.review_gate` reads the actual diff against `HEAD` (or the commit a run started
from) plus untracked files, and applies the `review.triggers` data in the routing file:

- **mandatory** on any tier: authentication/authorization and permission code, DocType,
  report, page and web-form permission JSON, financial calculations, data-integrity and
  destructive data operations, schema and migrations (DocType field changes, patches,
  fixtures), locking and transactions, global hooks overrides, secrets and deployment
  files, dependency manifests, lock files and shell scripts;
- **risk** (required on NORMAL and DIFFICULT, advisory below): any `hooks.py` change,
  background jobs, external integrations;
- **advisory**: new DocType fields, API surface that touches no data.

Frappe context rules (in code, `orchlib.py`), because a diff line alone does not say where
it sits. For Python files the changed line numbers are mapped onto the functions of the
new file, and a changed function is judged by its whole body:

- a changed `@frappe.whitelist` function (new, or only its body changed) that allows
  guests, reads or writes records, serialises documents, touches permissions, runs dynamic
  code, files or processes, or shapes the HTTP response → `sensitive-endpoint`, mandatory;
- the same for code in public pages: `www/`, `templates/pages/`, web-form controllers;
- a changed function whose name is about access (`has_permission`, `*_query_conditions`,
  `*login*`, `can_*`, ...) → `access-control-logic`, mandatory;
- Jinja templates: data access or `| safe` in the change, or a changed output expression
  in a template that queries data → mandatory. Markup, text and `_("...")` edits pass.

Plus: tests failed unexpectedly, two or more fix rounds, a diff larger than the tier
expects, or the user asked. Everything else is `review: not_required`, which is recorded
as such — never as a pass.

**Fail-closed.** Every result has `gate_status`; only `complete` can be `not_required`.

- `error`: the routing file's review block failed validation (a level other than
  mandatory/risk/advisory, an unknown key such as `line`, a pattern that does not
  compile, a missing tier), or the gate raised. Review required.
- `incomplete`: something was not assessed - git could not produce the diff, an untracked
  file was unreadable, a symlink, over 2 MB, binary content in a code file, a file type the
  gate does not know, a Python endpoint file that does not parse, or the dispatcher's
  snapshot or `HEAD` could not be read. Review required; `unevaluated` lists what and why.
- A delegated implementation always carries `review_gate` once the agent ran. If the agent
  committed (HEAD moved), the gate assesses the committed files against the starting commit
  and requires review; the Sonnet fallback is blocked.
- `orch gate --files` is a claim, so the whole diff is still read: a mandatory or risk
  finding outside the list requires review. `orch gate` exits 3 unless `complete`.

The triggers are regular expressions in data, so they can be tuned without touching code;
`tests/test_review_gate.py` pins the representative, security, harmless and fail-closed
cases.

## Fallback

`scripts/delegate` classifies every failed run from the CLI's own stderr: `auth`, `quota`,
`rate_limit`, `invalid_model`, `provider_unavailable`, `cli_startup`, `cli_missing`,
`timeout`, `interrupted`, `busy`, `unknown`, plus `incomplete_result` for a clean exit with no
report. It records the sanitized stderr excerpt and the path to the full stderr.

For an implementation it then decides whether Sonnet may take over: only for
infrastructure failures (not for a cancellation), only when no process of the run is alive,
no other delegated writer is active in the repository, the working tree could be read, and
the run did not modify files that already had the user's uncommitted changes. The result
says `fallback.allowed` and, if not, why. The orchestrator allows one transition per task.

For a review, failures become `verdict: BLOCKED` with the category as `blocker_reason`, and
a recovery: `blocked_quota`, `blocked_reauth`, `blocked_fix_model` (do not retry),
`retry_once`, `retry_once_later`.

## Models without editing the plugin

- Claude: aliases only (`opus`, `sonnet`), resolved by Claude Code.
- OpenCode: `orch models status` shows the effective model and whether the catalog offers
  it; `orch models discover` lists candidates in `implementers.opencode.candidate_families`;
  `orch models verify <id>` runs one real smoke task on a candidate in a throwaway
  repository (it costs provider usage, so the hook asks); `orch models promote <id>` makes
  a candidate verified within 14 days the implementation model (a different provider
  needs `--allow-provider-change`); `orch models reset` returns to the stable default. If a
  promoted model leaves the catalog, runs fall back to the stable model and say so.
- Codex: `orch models codex <id>` pins a catalog model; otherwise its own config is used,
  and a config model the CLI does not offer fails fast as `invalid_model` with the
  offered list.
- Nothing is checked over the network on the task path. The catalog is read from each
  CLI's local cache; `orch models discover --refresh` is the only network refresh.
- `~/.local/state/frappe-orchestrator/model-health.json` records how each model's real
  runs ended (operational availability), separately from catalog presence.

## Measurement

Every dispatcher run appends one line to `~/.local/state/frappe-orchestrator/metrics.jsonl`
(agent, mode, tier, model, status, failure category, seconds, files changed, verdict, and
Codex's own token count when it prints one). `orch metrics --days 7` summarises it. Nothing
is estimated: token and cost figures appear only when an agent reported them. Run
workspaces live under `~/.local/state/frappe-orchestrator/runs/` and are pruned after 14
days.

## What was deliberately not added

No server, queue, database, workflow engine or background monitor. State is a handful of
small JSON files; the lifecycle guarantee is process groups, a parent-death signal, a
watchdog process per run, and environment markers.

## Dispatcher reference

Every combination the dispatcher accepts. `--cwd` is always the repository root.

```text
delegate --agent opencode --mode implement --tier <TIER> --cwd <repo root>
delegate --agent codex --mode review --tier <TIER> --cwd <repo root>
delegate --agent codex --mode test --tier <TIER> --cwd <repo root>
delegate --agent codex --mode onboard --tier <TIER> --cwd <repo root>
delegate --agent codex --mode deliberate --stage position --trigger <reason> --tier <TIER> --cwd <repo root>
delegate --agent claude --mode deliberate --stage position --trigger <reason> --tier <TIER> --cwd <repo root>
```

`test` (Codex writes tests only) and `onboard` (read-only repository analysis for
`docs/ai-context/`) are for when the user asks; `deliberate` is run by `scripts/debate`.
