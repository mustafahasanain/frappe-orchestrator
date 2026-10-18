---
name: frappe-operations
description: "Use after changing a Frappe/ERPNext app to decide which bench operations the diff actually needs (usually none), or when asked to build assets, migrate, clear the cache, or run Frappe tests on a development site."
---

# Frappe operations

**The default is nothing.** Decide from the actual diff, not the task title. Each
unnecessary build, migrate, clear-cache or restart cost minutes per task in the audit.

| The diff changes | Run |
|---|---|
| Python controllers, API methods, reports (served by `bench start`) | nothing |
| DocType `.js` (`doctype/<x>/<x>.js`), page/report JS | nothing — reload the page |
| `public/**/*.bundle.{js,ts,css,scss,vue}` or files they import | `bench build --app <app>` |
| other `public/` files (symlinked into `sites/assets`) | nothing — hard-reload |
| DocType JSON fields/schema, `patches.txt` + patch, fixtures, custom fields in code | `bench --site <site> migrate` |
| `hooks.py`, translations, website/portal settings | `bench --site <site> clear-cache` |
| background job / scheduler code | nothing under `bench start`; restart workers only if `OPERATIONS.md` says the project runs under supervisor |

- **Never `bench restart` by reflex.** Under `bench start --noreload` it does nothing, and
  twice it was taken as the fix for a change that was never applied.
- Rebuild once, for the one app, only when bundled assets changed.
- Before a migration that drops or renames a field with data, removes a DocType, or runs
  a patch that rewrites rows: stop and ask.
- When something runs, say so in one line:
  `Frappe ops: build <yes|no> | migrate <yes|no> | clear-cache <yes|no> | site: <site|n/a>`.

## Site

- The development site named in `docs/ai-context/OPERATIONS.md`, or by the user, and
  listed by `orch sites list`. Never `ls sites | head -1` — that picked the wrong site three
  times. Never `--site all`, never a loop over sites.
- Always write `--site <site>`: without it bench silently picks `default_site`.
- A site not in the list asks once per session. If the user confirms it is a development
  site with no real client data, they can run `orch sites allow <site>`; you never decide
  that for them. Sites with restored client data belong under `orch sites protect`.
- `bench` runs from the bench directory (the one with `apps/` and `sites/`), which is
  recorded in `OPERATIONS.md`. `--cwd` for a delegated run is the app's repository root,
  never the bench.

## Tests

- Run targeted tests yourself, only on the development site:
  `bench --site <site> run-tests --app <app> --module <dotted.module>` (or `--doctype`).
  Never the whole suite without a stated reason, never on a non-development site.
- Save the output to a file and pass it to the review with `--test-results <file>`: the
  reviewer's sandbox cannot reach MariaDB or Redis.
- A test that could not run is reported as not run, never as passed.

## Failures

A failed bench command is an environment problem (service down, missing dependency,
wrong site, bad config) unless the diff clearly caused it. Do not retry it blindly and do
not count it as a failed implementation; fix what is local and safe, otherwise report it.

Bench operations are never put in a brief or delegated: the hook only sees your own
commands.
