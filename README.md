# frappe-orchestrator

A Claude Code plugin that makes Claude the orchestrator rather than the implementer:
it classifies a task, picks a model from central routing, delegates the work to an
external coding-agent CLI (OpenCode or Codex) through a single dispatcher, runs a
bounded review loop over the result, and holds every run inside the same Git, staging
and live-site boundaries.

| Component | Where |
| :-- | :-- |
| Skills | `skills/orchestration`, `skills/project-context`, `skills/frappe-operations` |
| Enforcement hook | `hooks/guard.py` (`PreToolUse` on `Bash`) |
| Delegation dispatcher | `scripts/delegate` |
| Boundaries and routing | `config/command-boundaries.json`, `config/model-routing.json` |

The hook and the dispatcher's permission policy are the two enforcement layers, and
they read their rules from `config/command-boundaries.json` rather than keeping copies.

## Requirements

- **Claude Code with the `plugin` CLI** (`claude plugin --help`). Verified on 2.1.240.
- **Python 3.** `hooks/guard.py` and `scripts/delegate` run under the system
  interpreter; no packages beyond the standard library.
- **[OpenCode](https://opencode.ai), Linux build.** The only agent that runs `implement`.
- **[Codex CLI](https://github.com/openai/codex).** Runs `review`, `test`, and `onboard` —
  a reviewer that wrote the code it reviews is not an independent reviewer, so the two
  agents never overlap.

### PATH order matters

On WSL, an npm install on the Windows side puts a second `opencode` and `codex` on your
PATH. The Linux build must resolve first:

```bash
which -a opencode   # the Linux path must be the first line
which -a codex
```

This is not a preference. The dispatcher delivers OpenCode's deny-list through
`OPENCODE_CONFIG_CONTENT` in the child environment. A Linux OpenCode reads it directly.
A *Windows* OpenCode only receives an environment variable that `WSLENV` names, and if it
does not arrive the permission policy is not weakened but **absent** — zero bash rules,
after which `--auto` approves everything. A delegated run has executed `bench migrate`
unrefused that way. `scripts/delegate` sets `WSLENV` unconditionally to cover the case,
but which binary `opencode` resolves to is a property of PATH, which nothing in this
repo controls. Each result records the binary that actually ran in `agent_path`.

## Installation

This repository is its own single-plugin marketplace (`.claude-plugin/marketplace.json`),
so it installs from the working tree. Run both commands once, from anywhere:

```bash
claude plugin marketplace add /path/to/frappe-orchestrator
claude plugin install frappe-orchestrator@frappe-orchestrator --scope user
```

`--scope user` registers it in `~/.claude/settings.json`, so it loads in every session in
every repository with no `--plugin-dir` flag. Confirm:

```bash
claude plugin list          # frappe-orchestrator@frappe-orchestrator — enabled
claude plugin details frappe-orchestrator@frappe-orchestrator   # 3 skills, 1 PreToolUse hook
```

A `directory` marketplace source is used **in place**. `CLAUDE_PLUGIN_ROOT` resolves to
this checkout, so the `hooks/guard.py` that runs, the `config/` it reads its boundaries
from, the `scripts/delegate` its messages point at, and the skills Claude loads are all
the files in this directory — not a copy. Keep the repository where it is: the
marketplace entry is a path to it, and moving or deleting the directory disables
enforcement everywhere.

## Updating after a commit

Because the plugin runs from the working tree, a change is live as soon as a session
loads it. There is nothing to sync:

| What you changed | When it takes effect |
| :-- | :-- |
| `skills/**/SKILL.md` body | Immediately, in sessions already open |
| `hooks/`, `config/`, `scripts/` | Next session, or `/reload-plugins` in an open one |

The cost of that is worth stating plainly: a broken working tree is broken enforcement in
every session, not just this repository's. Run `python3 tests/test_parser.py` before you
leave a change in the tree.

The two update commands are bookkeeping. `plugin.json` carries **no `version` field**, so
Claude Code stamps the install with the source commit SHA; a pinned version would freeze
that stamp and, if this marketplace ever moves to a git or GitHub source — where plugins
*are* copied into `~/.claude/plugins/cache` — would silently keep serving a stale copy.
Re-stamp after a commit:

```bash
claude plugin marketplace update frappe-orchestrator
claude plugin update frappe-orchestrator@frappe-orchestrator
```

The stamp should then match `HEAD`. This tells you the recorded version is current; it is
not what decides which code runs.

```bash
git rev-parse --short=12 HEAD                     # repository
claude plugin list | grep -A1 frappe-orchestrator # installed stamp
```

## Disabling

Turn it off without losing the install — reversible with `enable`:

```bash
claude plugin disable frappe-orchestrator@frappe-orchestrator
claude plugin enable  frappe-orchestrator@frappe-orchestrator
```

To remove it completely:

```bash
claude plugin uninstall frappe-orchestrator@frappe-orchestrator
claude plugin marketplace remove frappe-orchestrator
```

For one session only, `claude --safe-mode` starts with all customizations disabled,
this plugin included.

Disabling removes the enforcement hook along with the skills. The push, blanket-staging,
live-site and bare-agent boundaries stop being enforced.
