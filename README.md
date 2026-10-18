# frappe-orchestrator

A Claude Code plugin for Frappe/ERPNext and Next.js work. The main session (Opus)
orchestrates; OpenCode implements routine coding to save Claude tokens; a Sonnet subagent
handles trivial edits and takes over when OpenCode fails; Codex reviews only the changes
that carry real risk. A hook holds every run inside the same Git, site and destructive-
operation boundaries, with as few prompts as that allows.

| Tier | Implementer | Codex review |
|---|---|---|
| FAST — text, labels, minor styling | Sonnet subagent | only on a mandatory trigger |
| SMALL — simple fix, minor UI | OpenCode | only when the gate finds risk |
| NORMAL — typical feature | OpenCode | risk-based |
| DIFFICULT — architecture, data integrity, permissions | Opus directly, or OpenCode | required for significant changes |

Mandatory review triggers, on any tier: authentication/authorization and permissions,
financial calculations, data integrity and destructive data operations, schema changes and
migrations, locking, global hook overrides, secrets and deployment files, dependencies and
shell scripts, and whitelisted endpoints, public pages or Jinja templates that read, write
or expose data. The gate reads the actual diff (`orch gate`) and fails closed: anything it
could not assess, or a gate that errored, requires a review. A skipped review is recorded
as `review: not_required`, never as a pass.

| Component | Where |
|---|---|
| Skills | `skills/orchestration` (runtime rules, ~8 KB), `skills/frappe-operations`, `skills/project-context`, `skills/development-report` |
| Sonnet subagent | `agents/implementer.md` (`model: sonnet`) |
| Hook | `hooks/guard.py` — Bash (Pre/Post) and Edit/Write (Pre) |
| Dispatcher | `scripts/delegate` — one agent run, structured JSON result |
| Control | `scripts/orch` — status/stop, review gate, models, sites, Claude default, metrics |
| Shared mechanics | `scripts/orchlib.py` |
| Debate Mode | `scripts/debate` (on request only) |
| Rules and routing | `config/command-boundaries.json`, `config/model-routing.json` |
| Reference | `docs/reference/` (safety, orchestration, debate); history in `docs/history/` |

## Requirements

- Claude Code with the `plugin` CLI (verified on 2.1.302), and Python 3 (standard library only).
- [OpenCode](https://opencode.ai), Linux build first on `PATH` (`which -a opencode`). On
  WSL a Windows build would not receive the permission policy.
- [Codex CLI](https://github.com/openai/codex) for reviews.
- For the development report only: Chrome/Chromium, poppler-utils, an Arabic font.

## One-time setup

```bash
scripts/orch claude-default            # new sessions default to "model": "opus"? (--apply sets it, with a backup)
scripts/orch models status             # OpenCode and Codex models, and whether each CLI offers them
scripts/orch sites allow <dev-site>    # each development site with NO real client data
scripts/orch sites protect <site>      # sites holding restored client data: always ask
```

A `.local` name no longer makes a site a development site. Until a site is listed, the
first routine command reaching it asks once per Claude Code session.

## Models without editing the plugin

- Claude: aliases only (`opus` for the session, `sonnet` for the subagent).
- OpenCode: the stable model is `opencode-go/kimi-k2.7-code`. `orch models discover` lists
  newer candidates in the configured families; `orch models verify <id>` runs one real smoke
  task (it costs usage, so the hook asks); `orch models promote <id>` switches to a verified
  candidate; `orch models reset` goes back. A promoted model that leaves the catalog falls
  back to the stable one automatically.
- Codex: its own `config.toml` model, or `orch models codex <id>`. A model the installed CLI
  does not offer fails in under a second as `invalid_model`, listing what it does offer.

## Installation and activation

The marketplace source is a `directory`, so **the checkout it points at is what runs** —
for every session in every repository. Develop in a separate worktree, never in the
installed checkout, and only point the marketplace at a commit whose tests pass.

```bash
claude plugin marketplace add /path/to/frappe-orchestrator
claude plugin install frappe-orchestrator@frappe-orchestrator --scope user
```

Hooks and scripts reload on the next command; skills on the next session or
`/reload-plugins`. To try a checkout for one session without touching the install:
`claude --plugin-dir /path/to/checkout`.

## Tests

```bash
for t in tests/test_*.py; do python3 "$t" || break; done
```

All stub-based: no provider is called. `test_lifecycle` (signals, timeouts, orphans,
fallback safety), `test_permissions` and `test_scenarios` (prompt counts against the
baseline hook, protected commands, the edit guard, the delegated policy under OpenCode's
matcher), `test_review_gate`, `test_parser`, `test_site_approval`, `test_debate`,
`test_dev_report`.

## Limits

- The hook reads command text. It cannot see a site chosen inside a script file, or what
  runs on a remote host (remote connections ask instead).
- The delegated OpenCode policy is a deny list under `--auto`, where everything else is
  approved. Wrapped and path-qualified forms are covered; interpreters and variables are
  not. The real containment is the tree snapshot around every run, the diff, and the
  review gate. An interactive OpenCode "Allow always" and its server's shell endpoint are
  outside the dispatcher's reach.
- The edit guard covers Claude's Edit/Write tools. A Bash command that writes files
  (`sed -i`) while a delegated writer is running is not blocked by it.
- A commit's approval is the hook's prompt. Whether a hook `ask` still prompts in a session
  running with permissions bypassed is not documented by Claude Code; do not rely on that
  mode for work whose commits you want to approve.
- An agent that escapes both its process group and the run marker (clearing its own
  environment) would not be found by `orch status`. Nothing observed does this.

## Disabling

```bash
claude plugin disable frappe-orchestrator@frappe-orchestrator   # reversible: enable
claude --safe-mode                                              # one session, no plugins
```

Disabling removes the hook along with the skills, and with it every boundary above.
