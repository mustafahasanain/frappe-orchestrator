# Safety boundaries

What `hooks/guard.py` and the delegated permission policy enforce, and why. The rules
themselves are data in `config/command-boundaries.json`; this page explains them. The
orchestration skill carries only a short summary and links here.

Decisions: **deny** blocks the command and tells Claude why; **ask** shows the user a
permission prompt; **allow** runs with no prompt; no decision leaves the command to Claude
Code's own permission check.

## Git

| Command | Hook | Delegated agent |
|---|---|---|
| `git push` (any form, any wrapper) | ask | deny |
| `git commit` | ask — this prompt *is* the approval | deny |
| `git add .`, `./`, `:/`, `-A`, `--all`, `-u`, `--update` | deny | deny |
| `git reset --hard/--merge/--keep`, `checkout -- <path>`, `restore`, `clean` | ask | deny |
| `git stash drop/clear`, `branch -D/-M/-f`, `reflog expire`, `gc --prune=now` | ask | deny |
| `filter-branch`, `filter-repo`, `update-ref`, `rebase` | ask (rebase: no decision) | deny |

The orchestrator never commits or stages on its own: a task ends with the change in the
working tree. When the user asks for a commit, it runs
`git add <files> && git commit -m "feat: …"` as one command; the hook's prompt shows the
exact files and message, and approving it is the approval. Deny the prompt to change
anything.

## Sites

A site runs routine commands (`console`, `execute`, `migrate`, `clear-cache`,
`run-tests`, `list-apps`, read-only `mariadb -e "SELECT …"`, Python snippets that name it)
without a prompt only when:

1. it is listed as a development site in `~/.config/frappe-orchestrator/sites.json`
   (`orch sites allow <site>`), or
2. the user approved a command reaching it earlier in the same Claude Code session.

A `.local` name grants nothing by itself: some `.local` sites hold restored client data.
Sites listed with `orch sites protect <site>` ask every time and are never remembered.
`orch sites allow`, `orch sites remove` and any edit to the config directory ask.

Always asked, whatever the site: a bench command with no `--site` (bench would pick one
from `default_site`), `--site all`, a site the hook cannot read (a variable, a loop, a
computed `frappe.init(site=…)`), and every destructive operation below. A command that
reaches several sites is allowed only when every one of them qualifies.

`bench build` touches no site and runs without a prompt. `bench restart` gets no hook
decision (it is a no-op under `bench start`); the skill tells Claude not to run it by
reflex, and delegated agents may not run it.

Hook limits, stated plainly: the hook sees the text of a Bash command. It cannot see a site
chosen inside a Python file it runs (`python3 script.py`), and it cannot see what runs on a
remote host. Those are covered by instructions and by the remote-execution ask, not by
matching.

## Destructive operations

| Command | Hook | Delegated agent |
|---|---|---|
| `rm -r/-rf/-R …`, `find … -delete`, `find … -exec rm -r …`, `shred`, `truncate`, `dd` | ask | deny |
| `bench reinstall/restore/partial-restore/drop-site/uninstall-app/trim-*/transform-database/clear-log-table/destroy-all-sessions/set-*-password` | ask, on every site | deny |
| `bench --site <s> mariadb` / `db-console` / `postgres` (interactive or writing SQL) | ask | deny |
| `bench update/setup/new-site/get-app/remove-app/switch-to-branch/init` | ask | deny |
| `mysql`, `mariadb` clients | ask | deny |
| `ssh`, `scp`, `sftp` | ask | deny |

Wrappers do not hide a command: `env A=1 …`, `sudo …`, `nohup …`, `timeout 30 …`,
`xargs …`, `bash -c '…'`, `eval …`, `$(…)` and backticks are all looked through. Text is not
a command: a grep pattern, an `echo`, a commit message, a brief on the dispatcher's stdin,
or a heredoc written to a file is not matched. A heredoc read by a shell is matched as
commands; one read by Python or `bench console` is matched as Python.

## Agents

- Coding-agent CLIs run only through `scripts/delegate`; bare `opencode run`, `codex exec`
  and `claude -p` are denied. The dispatcher pins the working directory, the verified model,
  the timeout and the permission policy, and contains the process tree.
- **Lifecycle.** Each delegated agent runs in its own process group with marker variables
  in its environment. SIGTERM, SIGHUP and SIGINT to the dispatcher stop the whole group,
  then every marked process that left it, and still write `result.json`
  (`status: interrupted`). The agent gets `PR_SET_PDEATHSIG`. Before any pre-run work
  (catalog query, snapshot) the dispatcher forks a watchdog twice into its own session -
  neither in the dispatcher's process group nor its descendant - holding a pipe only the
  dispatcher writes to. EOF without "done" means the dispatcher died however it died
  (SIGKILL to it, to its group, or to its whole tree), and the watchdog SIGKILLs the
  agent's process groups and every marked process. Tested with stub agents whose
  grandchildren include one with its environment cleared and one in its own session
  (`tests/test_lifecycle.py`). A writer-mode run refuses to start (`status: busy`) while
  another delegated writer is alive in the same repository, and the hook denies Edit/Write
  there for the same reason. `orch status` / `orch stop --cwd <repo>` find and stop
  survivors.
- **Lifecycle limits.** Linux/WSL only (`/proc`, process groups, `fork`). Not covered: a
  process that both clears its environment and leaves the agent's process group (double
  fork plus `env -i`) - nothing identifies it as the run's; a supervisor that kills the
  watchdog too (cgroup or session-wide SIGKILL, machine shutdown); a process that becomes
  uninterruptible (D state). The dispatcher cannot confirm cleanup when `/proc` cannot be
  scanned, a group survives SIGKILL, or the run had no watchdog; any of these, or HEAD
  moving during the run, blocks the automatic Sonnet fallback (`fallback.blockers`).
- **Delegated OpenCode permissions are best-effort.** Under `--auto`, OpenCode approves every
  command no rule denies, so the policy is a deny list. Each deny is also emitted with the
  prefixes `* `, `*/`, `*'` and `*"`, so path-qualified, wrapped and quoted forms (`/usr/bin/git push`,
  `env X=1 git push`, `bash -c 'git push'`) are denied too. It cannot see through
  interpreters (`python -c "subprocess.run(['git','push'])"`) or variables. Two further
  OpenCode behaviours are outside the dispatcher's control: an interactive "Allow always"
  outranks a config deny, and the server's `/session/{id}/shell` endpoint is unguarded.
  The real containment is therefore the tree snapshot taken before and after every run
  (`files_changed`, `mixed_files`), the diff the orchestrator inspects, and the review gate.
- Codex runs read-only (`review`, `onboard`, `deliberate`) or workspace-write (`test`), with
  no network, and `--ephemeral`.
- The Sonnet subagent runs inside Claude Code, so this hook applies to its commands and
  edits like any other tool call.
