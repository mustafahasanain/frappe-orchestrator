---
name: frappe-operations
description: "Use after changing a Frappe/ERPNext repository to work out which bench operations the change actually needs — build, migrate, clear-cache, restart — and to run them safely on a local development site. Also use when asked directly to build assets, migrate a site, clear a cache, restart the development services, install an app, or run Frappe tests."
---

# Frappe operations

This decides **which bench operations a change requires**, resolves the site they run
against, runs them locally, and verifies they worked.

It never deploys. Remote servers, demo, and production are outside the plugin entirely —
see `## Deployment request handling` in the orchestration skill for what to say.

## The default is nothing

Do not run build, migrate, clear-cache, and restart after every change. That habit hides
which operation was actually needed, costs minutes per task, and migrates sites for
changes that touched no schema.

```text
actual Git diff  +  docs/ai-context/OPERATIONS.md  +  the rules below
        ↓
only the operations this change requires — often none
```

The diff is the input, not the task description. A task called "add a field" that turned
out to edit only a `.js` file needs a build and no migration.

## Required plan line

Before running the first operation, emit exactly one line:

    Frappe ops: build <yes|no> | migrate <yes|no> | clear-cache <yes|no> | restart <yes|no> | site: <name|n/a>

All four fields are always present, so a `no` is a decision on the record rather than an
omission. `site:` is `n/a` only when every required operation is site-independent.

    Frappe ops: build no | migrate no | clear-cache no | restart no | site: n/a

That line is the common case and it is a complete answer. Emit it and run nothing.

## Where these commands run

`bench` runs from the **bench directory** — the one containing `apps/`, `sites/`, and
`env/`. The repository you changed is an app inside it, at `apps/<app>/`, and `bench`
fails outside a bench directory.

These are two different directories and they are not interchangeable:

- Frappe operations run from the bench directory.
- `--cwd` for any delegated run is the **repository root**, never the bench directory.
  It is required, it is validated, and a delegated run scoped to the whole bench is not
  what any brief asked for.

`OPERATIONS.md` records the bench path under Setup assumptions. If it does not, ask
rather than searching upward from the repository and assuming what you find.

## What each operation requires

These are defaults. The project overrides them — see below.

### build

Compiled frontend assets changed: `.js`, `.ts`, `.vue`, `.css`, `.scss`, `.less`, files
under `public/`, bundle entry points (`*.bundle.js`), or the asset build configuration.

```text
bench build --app <app>
```

Scope it to the app you changed; a bare `bench build` rebuilds every app in the bench.
Not required for Python-only changes, DocType JSON changes, or anything that never
reaches the asset pipeline. Site-independent.

### migrate

Schema or metadata changed: a new or modified DocType JSON, added or changed fields,
a new patch plus its entry in `patches.txt`, fixtures that carry metadata, custom fields
or property setters defined in code, or a schema-affecting configuration change.

```text
bench --site <site> migrate
```

Not required for logic-only changes to existing methods, and not for frontend work.

### clear-cache

Something cached outside the database changed: `hooks.py`, website or portal settings,
translations, or configuration read through the cache rather than the row.

```text
bench --site <site> clear-cache
```

`hooks.py` is the common real case — hooks are cached, so an edit to them is invisible
until the cache is dropped. This is not a universal post-change command; run it when
there is a reason and name the reason.

### restart

Whether Python changes need a restart depends on how the project runs locally, which is
why `OPERATIONS.md` decides it and not this list. Two defaults worth knowing: a
`bench start` development server reloads changed Python itself, while background workers
and the scheduler do not — so a change to a queued job, a scheduled task, or a hook that
runs in a worker needs the processes restarted even though a browser request would pick
it up.

Restart only what the running environment actually requires, and only locally. A remote
restart is refused, not confirmed.

## The project overrides these rules

`docs/ai-context/OPERATIONS.md` outranks everything above. When it defines a custom build
command, a different test command, a required generation step, or a local service that
must be started, use what it says. The rules here are what to do when the project has not
spoken, not a description of every Frappe project.

If the project's real workflow turns out to differ from what `OPERATIONS.md` says, the
repository wins and that section gets fixed — the stale-context rule in the project
context skill, applied to operations.

## Site resolution

A site is a **development site** only when `docs/ai-context/OPERATIONS.md` identifies it
as one, or the user identifies it for this task. Belonging to the same bench is not
enough, and neither is a name that looks local.

```text
exactly one known development site  →  use it
more than one could be affected     →  stop and ask
none identified, or unclear         →  stop and ask
```

Never guess a site. This holds in development too, and it holds when the answer seems
obvious.

**Always write `--site <name>` on a site-dependent command, even where bench would find
one on its own.** Bench resolves an unnamed site from `default_site` and then
`currentsite.txt`, so a command with no `--site` still acts on a site — one chosen by
configuration, named nowhere, and invisible in the transcript afterwards. Naming it is
what makes it a decision.

When the user names a development site and `OPERATIONS.md` does not record it, add it
there once the task passes, under Setup assumptions. The next task then resolves it
without asking again.

Never `--site all`, and never a loop over sites.

## The live-site boundary is not restated here

Whether reaching a site is allowed at all is decided in one place: `### Live site access`
in the orchestration skill, enforced by `hooks/guard.py`. This skill decides only **which
operations a change requires**, which is a different question.

So: a site-dependent bench command asks for confirmation when it runs. That is the
boundary working, not an obstacle to route around, and this skill's "may run
automatically" means "is a correct operation to propose", never "may bypass that ask".

## Operations are never delegated

Run every Frappe operation yourself, as a local shell command. Never put a bench command
in a brief, and never route one through the dispatcher.

The reason is that no layer covers a delegated one. `hooks/guard.py` binds Bash tool
calls, and a delegated agent runs its shell inside its own process, where the hook never
sees it. What replaces it differs by agent: a delegated Codex run is held by its sandbox,
which denies socket and network connections at the syscall level; a delegated OpenCode run
is held by the dispatcher's permission policy, which is text-pattern matching over
commands and therefore only as complete as its list. Neither was built to decide which
site an operation should touch. Run it where the hook applies, and where a human is
present to answer the confirmation.

## Confirmation and refusal

**Stop and ask** before a migration that may be destructive: dropped or renamed fields
carrying data, a removed DocType, a patch that deletes or transforms existing rows, an
irreversible transformation, or any migration whose effect on existing data you cannot
predict. Normal development schema migration on a known development site does not need
this; uncertainty does.

**Never infer `install-app`.** An app being present in the bench does not mean it belongs
on a site. `bench --site <site> install-app <app>` runs only when the user asked for it,
or an approved documented workflow requires it.

**Requires explicit intent:** anything across multiple sites, data deletion, and
irreversible database operations. A bench holding several sites is not a reason to
operate on more than the resolved one.

**Refused, not confirmed:** remote execution over SSH, demo operations, production
operations. State that it belongs to a separate standalone deployment script the user
runs explicitly, and stop.

## Verification

An exit code of 0 is not the whole answer, and verification is proportional to the
operation.

| Operation | Verify |
| --- | --- |
| `build` | Completed without a build failure; the app's assets were actually rebuilt. Run the project's frontend smoke check if it has one |
| `migrate` | Completed with no migration exception, and no patch reported as failed. If the change was schema-specific, check that specific behaviour afterwards |
| `clear-cache` | Completed successfully. Nothing further unless the task needs it |
| `restart` | The restart finished and the local service is answering again, where the project has a known way to check |

Do not build a service monitor. Where no meaningful check exists, say so rather than
inventing one.

## When an operation fails

A failed bench command is **BLOCKED**, not a failed implementation attempt, unless the
evidence shows the implementation caused it. Work out which it is before deciding:

- **implementation** — the change itself is wrong; a patch raises, a hook references
  something that does not exist
- **environment** — a service is down, a dependency is missing, the bench is in a bad state
- **configuration** — site or bench configuration is wrong or absent
- **migration** — the schema change genuinely cannot apply as written

Then handle it as `### Handling BLOCKED` in the orchestration skill describes. Do not
retry the same command hoping for a different result, and do not spend an implementation
attempt on an environment fault.

## Where this fits in the workflow

Operations run **after implementation and before the review**, whenever the review or its
tests would otherwise run against stale state:

```text
implementation → actual diff → required Frappe operations → re-inspect the diff
→ Codex review / targeted tests → PASS / FAIL / BLOCKED
```

Migrating after the tests defeats the point: the tests would have run against the old
schema. If an operation changed the working tree — `build` writes compiled assets —
inspect the diff again before delegating the review, and stage generated assets only if
the project already tracks them.

## Routine operations

Thin wrappers over the bench CLI, nothing more. There is no Frappe agent and no operations
framework.

```text
bench build --app <app>                     rebuild one app's assets
bench --site <site> migrate                 apply schema and patches
bench --site <site> clear-cache             drop cached metadata and hooks
bench --site <site> install-app <app>       only on explicit request
bench --site <site> run-tests --app <app>   run the app's tests
bench --site <site> list-apps               read-only check of what is installed
```

Anything beyond these belongs in the project's own `OPERATIONS.md`, not here.
