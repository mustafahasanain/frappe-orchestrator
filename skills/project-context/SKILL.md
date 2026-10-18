---
name: project-context
description: "Use when the user asks to create, update or read a project's docs/ai-context/ (PROJECT.md, ARCHITECTURE.md, OPERATIONS.md), or to onboard an unfamiliar Frappe/ERPNext or Next.js repository. Not needed for ordinary implementation tasks."
---

# Project context

`docs/ai-context/` in the project repository is a navigation layer, not a replacement for
the code. The repository always wins; context exists so the same discovery is not
repeated on every task.

```text
docs/ai-context/
├── PROJECT.md        orientation
├── ARCHITECTURE.md   what matters for change impact
└── OPERATIONS.md     bench path, development site, test/build commands, gotchas
```

- **Reading:** only the section a task needs. Never re-scan the repository because a task
  arrived.
- **Creating** (only when the user asks, or before substantial DIFFICULT work in an
  unfamiliar repository): copy the templates from
  `${CLAUDE_PLUGIN_ROOT}/skills/project-context/templates/`, keep their length caps, and
  fill them from an architecture-level read — entry points, `hooks.py`, `modules.txt`,
  doctypes, `api/`, `patches/`, `public/`, tests, `package.json`. For a large repository,
  `delegate --agent codex --mode onboard` does the read-only analysis and returns findings
  with evidence paths; you validate them and write the files.
- **Updating:** after a task, only if it changed what a future developer must know (a new
  DocType, API, integration, permission model, test command, development site). Most
  tasks change nothing here.
- **Stale context:** trust the code, fix the section, continue. Never change code to match
  outdated documentation.
- Never write a secret. Paths, site names and app names are fine; credentials are not.
  No timestamps, changelogs or task journals — Git has the history.
- Document only what you verified. What the repository did not settle stays out, or is
  marked as open.
