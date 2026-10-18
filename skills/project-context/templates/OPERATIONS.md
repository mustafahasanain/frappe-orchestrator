<!-- Cap: ~80 lines. How to work with and verify this project locally. No secrets:
     paths and site names are fine, credentials and tokens are not.
     Replace each hint comment with real content; delete sections that do not apply. -->

# Operations

## Setup assumptions

<!-- What must already exist for commands here to work: bench path, package manager,
     required services.
     Name the bench path and the development site explicitly — "Bench: ~/frappe-bench",
     "Development site: dev.local". Operations that target a site refuse to guess one,
     and this file is where that answer lives. Writing a site here does not let it run
     without prompts: only `orch sites allow <site>` (the user's own list) does that, and
     only for a site with no real client data. List any other sites with what they are
     (restored client copy, demo, staging, production) - they stay protected.
     Say whether the bench runs under `bench start` (no restarts needed) or supervisor. -->

## Development

<!-- Commands to run the project locally. -->

## Tests

<!-- How tests are run, and how to run a targeted subset — the single most useful line
     in this file, because targeted verification depends on it. -->

## Lint, type-check, build

<!-- The exact commands, as the project defines them. -->

## Verification steps

<!-- Project-specific checks beyond the commands above: migrations to apply, caches or
     assets to rebuild, manual checks that matter. -->

## Gotchas

<!-- Operational traps: commands that look right but are not, steps that must run in a
     given order, things that fail silently. -->

<!-- Remote deployment is out of scope for this workflow. Deployment context may be
     described here for understanding, but is never controlled from here. -->
