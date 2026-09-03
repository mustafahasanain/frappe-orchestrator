# Repository Audit — frappe-orchestrator

**Audit type:** static review, read-only. No project file was modified, no external coding
agent was invoked, no bench/site/database command was run, and no Git state in this
repository was changed. The only file created is this one.

| | |
| :-- | :-- |
| Repository | `https://github.com/mustafahasanain/frappe-orchestrator` |
| Local path | `/home/mustafa/Projects/frappe-orchestrator` |
| Branch | `main` |
| Commit at start of review | `a970b295cace96cd32a33a2c36150656f73b39fa` (`chore(install): install from the repo instead of a session flag`) |
| Working tree at start | **clean** (`git status --porcelain` empty) |
| Tracked files | **29** |
| Files reviewed in full | **29** |
| Files skipped | **0** |
| Total tracked lines | 10,663 |
| Claude Code on this machine | 2.1.258 |
| Plugin installed here? | **No** — `claude plugin list` shows only `warp@claude-code-warp`; neither the marketplace nor this plugin is registered, so the enforcement hook was **not active** during the audit (see `ARCH-001`) |
| Test suite | `python3 tests/test_parser.py` → `ok`, exit 0, 10.25 s |

---

## 1. Executive Summary

This is an unusually careful, unusually well-documented repository. The engineering
discipline on display — a build contract, per-phase reports that record what was
*believed* alongside the correction, single-sourced boundary rules with a drift test that
fails by rule name, real captured fixtures rather than invented stubs, and explicit
"this conclusion was right but its reason was wrong" corrections — is better than almost
anything of this size. Several classes of defect that normally survive for years here got
found, measured, and written down.

That quality is uneven, though, and it is uneven in a specific way: **the reasoning about
each individual rule is excellent, and the reasoning about the matching layer underneath
all of them is thin.** Every rule in `config/command-boundaries.json` is well-argued,
correctly scoped, and documented. But both engines that consume it match on a
lightly-normalized command string, and neither engine's normalization is adequate. The
result is that a boundary the README describes as enforced can be crossed by an ordinary
alternate spelling of the same command — `git add ./` instead of `git add -A`,
`/home/frappe/frappe-bench/env/bin/bench migrate` instead of `bench migrate`,
`cd /bench && bench migrate` instead of either.

| Dimension | Assessment |
| :-- | :-- |
| **Code quality** | **Good.** ~1,100 lines of Python, standard library only, no dead code, no TODO/FIXME markers, comments that explain *why* and are (with two exceptions noted below) accurate. Both scripts are readable and the abstraction boundaries are sensible. |
| **Security posture** | **Weaker than documented.** The layered design is right and the rule set is well-chosen, but the matching layer is bypassable by non-adversarial alternate command forms in both engines (`SEC-001`…`SEC-003`), the hook fails **open** silently on a structurally-valid-but-unusable rule file (`SEC-004`) and on unexpected payload shapes (`SEC-005`), and neither layer covers destructive Git or filesystem operations at all (`SEC-006`). |
| **Architecture quality** | **Good, with one soft spot.** Single-sourced rules with two translations is the correct design and the drift test earns its keep. The soft spot is that "translation" is where all the risk lives and there is no shared normalization step, so the two translations are independently and differently wrong. |
| **Test quality** | **Narrow but genuinely load-bearing.** 38 parser cases + boundary/matrix/invocation/agent-path/cwd checks, all fast and framework-free, with a `KNOWN_GAPS` mechanism that is a good idea. But `hooks/guard.py`'s entry point (`main()`, payload parsing, segment splitting, degraded mode) is **entirely untested**, `execute()` is untested, and every test of the delegated policy uses `fnmatch` as a stand-in for OpenCode's real matcher. The tests prove the two engines agree about the *examples in the data*; they do not prove either engine catches the command it is about. |
| **Documentation quality** | **Excellent in substance, drifting in detail.** The README is one of the better plugin READMEs I have read — it explains PATH order as a safety property, not a preference. But `claude plugin validate . --strict` now fails, several verification rows in the phase reports are no longer true, and the Phase 02/03 specs still contradict the shipped `onboard` mode while the build contract says the spec wins. |
| **Readiness for regular use** | **Usable with eyes open, not yet safe to rely on.** As a *guidance* layer it is strong today. As the *enforcement* layer it advertises, it has one P0 and eight P1 gaps, and its own failure modes are quieter than its design intends. |

**Overall confidence in this audit: High** for everything demonstrated by direct execution
against the repository's own code (which is most of it — every P0/P1 finding below carries
a reproduction I ran), **Medium** for the two findings that depend on how OpenCode's
permission matcher behaves internally, which I deliberately did not exercise because the
audit rules forbid invoking the agent CLIs.

---

## 2. Repository Coverage

### Reviewed in full (29 of 29 tracked files)

| Path | Lines | What it is |
| :-- | --: | :-- |
| `.claude-plugin/plugin.json` | 14 | Plugin manifest |
| `.claude-plugin/marketplace.json` | 14 | Single-plugin marketplace catalogue |
| `.gitattributes` | 1 | `* text=auto eol=lf` |
| `.gitignore` | 22 | OS/editor/log/env/`__pycache__` |
| `README.md` | 126 | Install, update, disable, PATH-order warning |
| `config/command-boundaries.json` | 390 | **The** rule set; 9 rules |
| `config/model-routing.json` | 93 | Models, tiers, escalation ladder, special models |
| `hooks/guard.py` | 265 | `PreToolUse` enforcement hook |
| `hooks/hooks.json` | 18 | Hook registration |
| `scripts/delegate` | 857 | Delegation dispatcher |
| `skills/orchestration/SKILL.md` | 525 | Orchestrator rules |
| `skills/project-context/SKILL.md` | 191 | Context + impact rules |
| `skills/frappe-operations/SKILL.md` | 253 | Which bench operations a diff needs |
| `skills/project-context/templates/PROJECT.md` | 23 | Context template |
| `skills/project-context/templates/ARCHITECTURE.md` | 32 | Context template |
| `skills/project-context/templates/OPERATIONS.md` | 40 | Context template |
| `tests/test_parser.py` | 791 | The whole test suite |
| `tests/fixtures/codex-review-clean.txt` | 9 | Real captured `codex exec` stdout |
| `tests/fixtures/codex-review-inner-fence.txt` | 22 | Real captured output that broke the old parser |
| `docs/BUILD_CONTRACT.md` | 319 | Build governance |
| `docs/phases/PHASE_01_ORCHESTRATION_FOUNDATION.md` | 840 | Spec |
| `docs/phases/PHASE_02_PROJECT_CONTEXT_AND_IMPACT.md` | 909 | Spec |
| `docs/phases/PHASE_03_IMPLEMENTATION_AND_QUALITY_LOOP.md` | 1128 | Spec |
| `docs/phases/PHASE_04_FRAPPE_OPERATIONS.md` | 748 | Spec |
| `docs/reports/PHASE_01_REPORT.md` | 272 | Phase report |
| `docs/reports/PHASE_01_5_REPORT.md` | 377 | Phase report |
| `docs/reports/PHASE_02_REPORT.md` | 172 | Phase report |
| `docs/reports/PHASE_03_REPORT.md` | 1764 | Phase report |
| `docs/reports/PHASE_04_REPORT.md` | 448 | Phase report |

### Skipped

**None.** There are no generated, cached, or binary artifacts in the tracked set. Every
tracked file was read end to end. `.git/` internals were consulted only through
read-only `git` commands (`ls-files`, `log`, `show --stat`, `rev-parse`, `status`).

### What was executed, and what was deliberately not

**Executed (all non-destructive, all local):**

- `python3 tests/test_parser.py` — the project's own suite, twice.
- `claude --version`, `claude plugin validate .`, `claude plugin validate . --strict`,
  `claude plugin list`, `claude plugin marketplace list` — read-only.
- Read-only `git` commands against this repository.
- Eight probe scripts written to the session scratchpad, which **import**
  `hooks/guard.py` and `scripts/delegate` as modules, or run them as subprocesses against
  **stub** CLIs and **throwaway** temp directories. Every probe target was created for the
  probe inside `/tmp/claude-1000/.../scratchpad` and deleted afterwards. One throwaway
  `git init` repository was created in the scratchpad to verify how `git add` parses
  equivalent option forms (`SEC-003`); it was removed. This repository's index, HEAD, and
  working tree were never touched.

**Deliberately not executed, per the audit's safety rules:**

- `scripts/delegate` against a real agent (only against stub `opencode` executables on a
  PATH the probe controlled — the same technique `check_agent_path_record()` in the
  project's own suite uses).
- Any `opencode` or `codex` invocation, including `--help` and `--version`. This is why
  `BUG-010` and part of `SEC-001` carry Medium rather than High confidence.
- Any `bench`, `mysql`, `mariadb`, `psql`, or site command.
- Any `git push`, `reset`, `clean`, `add`, `commit`, or `stash` in this repository.
- `claude plugin install` / `marketplace add` — installing would have changed the user's
  global configuration.

---

## 3. Architecture Summary

This is what the implementation actually does, reconstructed from code rather than from
the specs.

### Components and how they are loaded

```
.claude-plugin/marketplace.json   one entry, source "./"  -> installed in place
.claude-plugin/plugin.json        manifest; declares NO component paths, NO version
        |
        +-- skills/               discovered by convention (3 skills)
        +-- hooks/hooks.json      discovered by convention -> PreToolUse on Bash
        |        -> ${CLAUDE_PLUGIN_ROOT}/hooks/guard.py, exec form, timeout 10 s
        +-- scripts/delegate      NOT auto-loaded; invoked by Claude as a Bash command
        +-- config/               read at runtime by guard.py and delegate
        +-- docs/, tests/         never loaded at runtime
```

Because the marketplace source is a directory, the install is used *in place*:
`CLAUDE_PLUGIN_ROOT` is this checkout, so an edit to `guard.py` or `config/` is live in
the next session with no copy to sync. That is a deliberate, well-documented trade — and
it means a broken working tree is broken enforcement in every repository, which the README
says plainly.

### Execution flow for one task

```
user request
   |
   v
[skills/orchestration]  activated by frontmatter description (semantic, stochastic)
   |  emits: "Orchestration: <TIER> | model: <name> | tree: <clean|dirty> | context: <present|absent>"
   |  reads config/model-routing.json for the tier's model name
   |  runs `git status` and checks for docs/ai-context/    <-- the only two pre-preamble calls
   v
[skills/project-context]  read when context is absent, or the task is NORMAL/DIFFICULT
   |  emits: "Impact: <area> | affected: ... | risks: ... | verify: ..."
   |  bootstrap: copy skills/project-context/templates/* into the project's docs/ai-context/
   |  onboarding of an unfamiliar repo -> delegate --agent codex --mode onboard
   v
model routing: routing.models[name].executor
   |  "opencode" -> delegate the implementation
   |  "claude"   -> Claude implements directly (DIFFICULT tier and the Opus rung)
   v
[scripts/delegate]  one process per delegated run
   |  1. validate_invocation(agent, mode, model)      agent x mode matrix; --model rules
   |  2. load_routing()   -> model id, tier effort, tier timeout_seconds
   |  3. load_boundaries() -> REFUSES (exit 2) if unreadable
   |  4. brief on stdin; CONTRACTS[mode] appended by the dispatcher, not the caller
   |  5. resolve_working_directory(--cwd) -> realpath, must be a git work tree ROOT
   |  6. ADAPTERS[agent]:
   |       opencode -> ["opencode","run","--agent","build","--auto","--dir",cwd,
   |                    "--model",id, ("--variant",effort)?, brief]
   |                   env += OPENCODE_CONFIG_CONTENT = generated permission policy
   |                   env += PWD = cwd ;  env += WSLENV = ...:OPENCODE_CONFIG_CONTENT/w
   |       codex    -> ["codex","exec","--sandbox",<read-only|workspace-write>,"-C",cwd,"-"]
   |                   brief on stdin
   |  7. mkdtemp() workspace OUTSIDE the repo; brief.md written; path echoed to stderr
   |  8. resolve_program() -> agent_path / agent_real_path recorded
   |  9. Popen(argv, cwd, env, text=True) + communicate(timeout)
   |  10. extract_report(stdout, mode): scan backwards for a balanced JSON object whose
   |      mode-specific discriminator has an enumerated value
   |  11. strip_off_contract(): remove verdict/blocker_reason in modes with no verdict
   |  12. print result JSON to stdout; also write workspace/result.json
   v
Claude inspects the REAL diff (git status / git diff) — the authority, not agent_report
   v
[skills/frappe-operations]  which bench operations the diff requires
   |  emits: "Frappe ops: build <y/n> | migrate <y/n> | clear-cache <y/n> | restart <y/n> | site: <name|n/a>"
   |  run by Claude directly, never delegated; every site-dependent command names --site
   v
delegate --agent codex --mode review   -> PASS | FAIL | BLOCKED
   |  FAIL -> fix loop, max 3 attempts, same agent then escalate; re-review each time
   |  PASS -> context update if needed -> cleanup checklist -> stage by path -> local commit
   v
git push: never automatic
```

### Where the trust boundaries actually are

| Boundary | What is on the other side | What enforces it | Strength |
| :-- | :-- | :-- | :-- |
| Claude's own Bash calls | the user's machine, Git, live sites | `hooks/guard.py` via `PreToolUse` | Token matching over separator-split segments. Bypassable by wrappers and alternate spellings (`SEC-002`, `SEC-003`). Fails **open** on unusable config (`SEC-004`) and on odd payloads (`SEC-005`). |
| A delegated **OpenCode** run's shell | same | `OPENCODE_CONFIG_CONTENT` deny globs, base `"*": "ask"`, `--auto` | The only layer. Glob prefixes anchored on the bare program name; permits path-qualified and chained forms (`SEC-001`). Base `ask` + `--auto` means *everything not denied is auto-approved* (`SEC-006`). |
| A delegated **Codex** run's shell | same | `codex exec --sandbox`, read-only by default, `workspace-write` only for `mode == "test"` | Strongest layer in the system. Measured (Phase 04) to refuse AF_UNIX, loopback TCP and public TCP with `EPERM` from the seccomp filter. |
| Skill prose | everything | nothing | Activation is semantic and stochastic; this is precisely why the hook exists. |
| Agent output → orchestrator | Claude's context and decisions | `extract_report` + `strip_off_contract` | Structural, bounded, never raises — but a nested object can shadow the real report and flip FAIL to PASS (`BUG-001`). |
| The CLI process itself | the user's home directory | nothing | Phase 04 found a delegated Codex run writing `trust_level = "trusted"` into `~/.codex/config.toml`. Recorded, unmitigated. |

The single most important architectural fact, and the report states it correctly: **for a
delegated run the hook does not count.** The dispatcher's per-agent containment is not one
layer of several; it *is* the layer. Which is why `SEC-001` is a P0 and not a P2.

---

## 4. Findings Summary

39 findings: **1 P0, 8 P1, 13 P2, 11 P3, 6 Improvements.**

| ID | Severity | Category | File | Short description |
| :-- | :-- | :-- | :-- | :-- |
| SEC-001 | **P0** | Command boundary | `scripts/delegate:81-135` | Delegated deny globs are anchored on the bare program name, so path-qualified, wrapped and chained forms of every denied command are permitted inside an unattended run |
| SEC-002 | **P1** | Command boundary | `hooks/guard.py:144-153` | Every hook rule — `deny` included — is bypassed by a wrapped invocation (`bash -c`, `sh -c`, `sudo`, `env`, `npx`, `( … )`, `VAR=x cmd`, `command`, `time`, `xargs`) |
| SEC-003 | **P1** | Command boundary | `config/command-boundaries.json:46-78` | The blanket-staging `deny` is bypassed by ordinary equivalents: `git add ./`, `git add *`, `git add -Av`, `git add :/`, `git add -u` — all verified to stage the same files as `git add -A` |
| SEC-004 | **P1** | Fail-open | `hooks/guard.py:118-141,222-234` | A boundary file that parses but yields no usable rules (`rules: []`, `rules: {}`, non-dict rules, every `hook` null) makes the hook enforce **nothing, silently** — the documented degraded "ask" path never fires |
| SEC-005 | **P1** | Fail-open | `hooks/guard.py:237-243` | Unexpected payload shapes and some malformed rule data raise an uncaught exception (exit 1); a non-2 exit is a *non-blocking* hook error, so the command proceeds |
| SEC-006 | **P1** | Missing rule | `config/command-boundaries.json` | Neither layer guards destructive Git (`reset --hard`, `clean -fdx`, `checkout -- .`, branch deletion, history rewriting) or destructive filesystem operations; inside a delegated run the base policy auto-approves them |
| BUG-001 | **P1** | Correctness | `scripts/delegate:553-576,605-632` | A nested object carrying the mode's discriminator shadows the real report: a review that returned FAIL is handed to the orchestrator as `{"verdict":"PASS"}` with all findings discarded |
| BUG-002 | **P1** | Reliability | `scripts/delegate:508-531` | The timeout does not bound the run: after `proc.kill()` the second `communicate()` has no timeout, so a surviving grandchild holding the stdout pipe hangs the dispatcher indefinitely; grandchildren are never killed |
| BUG-003 | **P1** | Robustness | `scripts/delegate:512-520,796-797` | A single non-UTF-8 byte on the agent's stdout crashes the dispatcher (`UnicodeDecodeError`, exit 1, no result JSON, no transcript written) |
| SEC-007 | P2 | Missing rule | `config/command-boundaries.json:254-280` | `database-client` covers only `mysql`/`mariadb`, although the same file lists `bench postgres`; `psql`, `redis-cli`, `sqlite3` and direct HTTP calls to a running site are unguarded |
| SEC-008 | P2 | Missing rule | `config/command-boundaries.json:141-253` | `bench drop-site`, `new-site`, `update`, `restart`, `remove-app`, `backup-all-sites` are unguarded in the hook — a deliberate, still-open decision |
| SEC-009 | P2 | Trust boundary | `config/command-boundaries.json`, `README.md` | Five of nine rules decide `ask`, which is only a boundary while a human is present; the docs never state what happens in `-p`, auto-accept, or bypass-permissions sessions |
| BUG-004 | P2 | Robustness | `scripts/delegate:383-412,67-78,727-732` | Wrong-typed config raises an uncaught exception (exit 1), violating the documented "exit 2 means the invocation was wrong"; and a rule file with zero usable rules yields a zero-deny policy without complaint |
| BUG-005 | P2 | Validation | `scripts/delegate:678,730-732` | `--timeout 0` silently becomes the tier default; negative timeouts are accepted and kill instantly; a string `timeout_seconds` passes `--dry-run` and crashes at run time |
| BUG-006 | P2 | False positive | `hooks/guard.py:24,247` | Separator splitting runs on the raw command, so a legitimate `git commit -m "…; git add . "` is **denied** |
| CFG-001 | P2 | Configuration | `scripts/delegate:667`, `config/model-routing.json:54-85` | `--tier` choices are a second hard-coded copy of the routing file's tier names, and two escalation-ladder rungs have no tier at all, so they have no timeout or effort source |
| CFG-002 | P2 | Validation | `config/*.json` | Neither config file has a schema or any type validation; a degenerate `identifiers: []` turns one rule into "ask on every command" |
| DOC-001 | P2 | Documentation | `README.md`, `docs/reports/*` | `claude plugin validate . --strict` now **fails** (no `version` in `plugin.json`) while every phase report records it passing — and it exits 0 either way, so the reports' "(exit 0)" evidence never proved the result |
| DOC-002 | P2 | Documentation | `docs/phases/PHASE_02*.md:337`, `PHASE_03*.md` | Both specs still say onboarding uses REVIEW mode; the build contract says the spec wins on behaviour, so the authoritative documents contradict the shipped `onboard` mode |
| ARCH-001 | P2 | Architecture | `skills/orchestration/SKILL.md:11-35` | Nothing tells a session whether enforcement is actually active. The preamble reports tier, model, tree and context — not hook state. The plugin is not installed on this machine and nothing in a session would say so |
| PATH-001 | P2 | Portability | `skills/*/SKILL.md` | The skills instruct Claude to read and execute `${CLAUDE_PLUGIN_ROOT}/…` paths, but it is unverified that this variable is set in the Bash tool's environment; if it is not, the paths silently resolve to `/config/…` and `/scripts/delegate` |
| TEST-001 | P2 | Test coverage | `tests/test_parser.py` | `hooks/guard.py`'s entry point is entirely untested: payload parsing, segment splitting, deny-over-ask precedence, degraded mode, and the JSON output shape have no test |
| BUG-007 | P3 | Resource | `scripts/delegate:785-788` | Delegation workspaces are never cleaned up; briefs and full transcripts accumulate in the system temp directory indefinitely |
| BUG-008 | P3 | Correctness | `scripts/delegate:553-556` | Discriminators are matched case-insensitively but passed through verbatim, so `agent_report.verdict` can be `"pass"` where every skill rule speaks of `PASS` |
| BUG-009 | P3 | False positive | `scripts/delegate:93-124` | Delegated globs over-match in the other direction: `mysql*` denies `mysqldump`, `bench backup*` denies `bench backup-all-sites`, `git commit*` denies `git commit --dry-run` — divergences the drift test cannot see |
| BUG-010 | P3 | Command boundary | `config/command-boundaries.json:324-328,362-366` | The `--help`/`--version` exemption matches the token anywhere in the segment, so `opencode run 'brief' --help` is exempt from the deny |
| DOC-003 | P3 | Documentation | `hooks/hooks.json:2` | The hook's own description lists three boundaries; there are now five rule families including bare-agent and unnamed-site |
| DOC-004 | P3 | Documentation | `docs/BUILD_CONTRACT.md:38` | The contract says `.claude-plugin/` contains **only** `plugin.json`; `marketplace.json` is now there, and three phase reports' `ls -A .claude-plugin` verification rows are false |
| DOC-005 | P3 | Process | HEAD commit `a970b29` | The commit carries `Co-Authored-By` and `Claude-Session` trailers, which the contract's Git rules forbid outright; it also adds files outside every phase's allowed list with no report |
| DOC-006 | P3 | Documentation | `docs/reports/PHASE_01_REPORT.md:5,49` | Records a `version` field in `plugin.json` and `GLM-5.2` in the routing file; neither is true now |
| DOC-007 | P3 | Documentation | `scripts/delegate:808-827`, `skills/orchestration/SKILL.md:302-318` | `agent-stderr.txt` is written but never named in the result, and the skill points only at `transcript` (stdout) — so a plain `failed` run's cause is not in-band |
| DOC-008 | P3 | Documentation | `README.md:81` | `/reload-plugins` is presented as the way to pick up hook/config changes in an open session; unverified |
| TEST-002 | P3 | Test coverage | `tests/test_parser.py` | `execute()`, `opencode_permissions()`, `load_routing`/`load_boundaries`/`resolve_model` error paths, and `--tier`-vs-routing consistency are all untested |
| IMP-001 | Improvement | Architecture | `scripts/delegate` | Adopt the per-run random delimiter token the project's own Phase 03 report already recommends, and retire report *identification* as a heuristic |
| IMP-002 | Improvement | Architecture | `hooks/guard.py`, `scripts/delegate` | Add one shared command-normalization layer and drive both engines from it, so a bypass is fixed once rather than twice |
| IMP-003 | Improvement | Validation | `config/*.json` | Give both config files a schema, validate on load, and make *unusable* rule data fail the same way *unreadable* data does in each consumer |
| IMP-004 | Improvement | Security | `scripts/delegate:324,370` | The child inherits the dispatcher's entire environment, including unrelated credentials; pass an allowlist instead |
| IMP-005 | Improvement | Performance | `skills/orchestration/SKILL.md` | 23.7 KB (~5.9k tokens) loaded on a very broad trigger, on every task including a one-word typo fix |
| IMP-006 | Improvement | Reliability | `hooks/`, `skills/orchestration/SKILL.md` | Give the plugin a way to say "enforcement is live" inside a session, so a lapsed install is visible rather than inferred |

---

## 5. Detailed Findings

### SEC-001 — P0 — Delegated deny globs are anchored on the bare program name

- **File:** `scripts/delegate:81-135` (`rule_patterns`, `denied_bash`), consumed at
  `scripts/delegate:138-143` (`opencode_permissions`) and `310-352` (`adapt_opencode`).
- **Config keys:** every rule in `config/command-boundaries.json` with `"delegated": "deny"`.
- **Confidence:** **Medium-High.** The pattern *generation* is confirmed by direct
  execution. What is not confirmed is whether OpenCode's permission matcher canonicalizes
  a command before matching; I did not invoke OpenCode, per the audit's safety rules.

**Description.** `rule_patterns` builds OpenCode bash patterns as literal prefixes of the
command string: `"git push*"`, `"git * push*"`, `"bench migrate*"`, `"bench * migrate*"`,
`"mysql*"`, `"git add -A*"`. Every pattern begins with the bare program name. There is no
step that strips a leading path, unwraps `sudo`/`env`/`bash -c`, or splits a chained
command — all three of which `hooks/guard.py` does at least partially
(`program()` at `hooks/guard.py:151-153` strips everything before the last `/`;
`SEPARATORS` at `:24` splits on `&&`, `||`, `;`, `|`, `&`, newline).

**Why it matters.** For a delegated OpenCode run this policy is not one layer of several —
it is the only layer. `hooks/guard.py` binds `PreToolUse` on Claude's Bash calls; a
delegated agent runs its own shell inside its own process, which the hook never sees. The
project states this itself in `skills/frappe-operations/SKILL.md:160-172` and in
`docs/reports/PHASE_03_REPORT.md`'s "the hook does not count" table. So a gap here is not
defence-in-depth thinning; it is the boundary being absent, with no human watching.

**Evidence.** Generated the real policy from the real rule data and matched commands
against it with `fnmatch` (the same approximation the project's own
`check_command_boundaries()` uses at `tests/test_parser.py:456`):

```
hook     delegated  command
ask      deny       git push
ask      allow      /usr/bin/git push
ask      deny       bench migrate
ask      allow      /home/frappe/frappe-bench/env/bin/bench migrate
ask      deny       mysql -u root
ask      allow      /usr/bin/mysql -u root
ask      allow      cd /r && bench migrate
ask      allow      echo hi && git push
allow    allow      sudo bench migrate
allow    allow      bash -c 'bench migrate'
```

The generated policy is 173 bash rules — `{"*": "ask"}` plus 172 denies — set identically
at `permission.bash` and `agent.build.permission.bash`, with zero `allow` entries. That
part is correct and well-built. The problem is entirely in what the 172 patterns match.

The path-qualified row is the important one, because **running bench from the bench
virtualenv's absolute path is the normal way to run bench**, not an evasion:
`/home/frappe/frappe-bench/env/bin/bench` is what a Frappe developer's own notes and
`OPERATIONS.md` will often contain. `skills/project-context/templates/OPERATIONS.md:9-14`
explicitly asks the project to record its "bench path" — so the brief a delegated agent
receives may well contain the absolute form.

The chained row is the project's own unresolved `Limitation 2`
(`docs/reports/PHASE_03_REPORT.md`: *"Pattern matching against chained commands is
unverified… A `git push` buried in a compound command may or may not match."*). It has
been unverified since Phase 03 and is still unverified.

**Realistic failure scenario.** A NORMAL-tier implement task is delegated to OpenCode in a
Frappe app repository. The brief mentions that the bench lives at
`/home/frappe/frappe-bench`. The agent decides it needs the schema applied before it can
check its own change and runs
`/home/frappe/frappe-bench/env/bin/bench --site prod.example.com migrate`. `--auto`
approves it because no deny pattern matches, no hook sees it, nobody is watching, and the
result reports `status: completed`. This is the same shape as the incident already in the
record — a delegated Codex run reaching for `bench --site masa.local run-tests` that
nothing in its brief asked for — except that Codex's seccomp sandbox stopped that one and
OpenCode has no equivalent.

**Recommended fix.** Two parts, in order:

1. Generate patterns that cover the forms the hook already normalizes. For each rule,
   additionally emit `*/<program> …` variants and, where OpenCode's glob syntax allows it,
   a leading `*` variant for chained/wrapped commands (e.g. `"* bench migrate*"`,
   `"*/bench migrate*"`). This is a change confined to `rule_patterns`.
2. Establish what OpenCode actually matches on — the raw command string, a parsed argv, or
   a canonicalized program — with one `opencode debug config` run plus a probe following
   the isolation rules the Phase 03 report already lays out. Record the answer in the
   dispatcher's comment block. Everything above assumes raw-string matching; if OpenCode
   parses and canonicalizes, some of these rows collapse, and knowing which is worth one
   command.

Longer term this is `IMP-002`: both engines should consume one normalization step.

**Regression test:** yes. Extend `check_command_boundaries()` with an *equivalent-forms*
table per rule — path-qualified, chained, and wrapped spellings — asserted against **both**
engines, not just the `examples` list already in the data.

---

### SEC-002 — P1 — Every hook rule is bypassed by a wrapped invocation

- **File:** `hooks/guard.py:144-153` (`split_tokens`, `program`), `:210-219` (`match_rule`).
- **Confidence:** **High** — reproduced through the hook's real process entry point.

**Description.** `match_rule` takes `tokens[0]` (minus any leading path) as *the* program
name. Anything that puts another word first — a shell, a privilege wrapper, an environment
prefix, a subshell, a runner — makes every rule inert.

**Evidence.** Payloads piped to `hooks/guard.py` exactly as Claude Code delivers them
(`{"tool_name":"Bash","tool_input":{"command": …}}`); every one of these returned **no
output at all**, i.e. allow:

```
allow   bash -c 'git add -A'          <- deny rule
allow   sh -c "git push"
allow   bash -c 'bench migrate'
allow   env FOO=1 git push
allow   sudo mysql -u root
allow   sudo bench --site dev.local migrate
allow   eval 'git add -A'             <- deny rule
allow   command git push
allow   time git push
allow   nohup bench migrate
allow   ( git add -A )                <- deny rule
allow   { git add -A ; }              <- deny rule
allow   GIT_DIR=/x git push
allow   PATH=/usr/bin git push
allow   ${PATH:0:0}git push
allow   $(which git) push
allow   npx opencode run 'x'          <- deny rule
allow   xargs -I{} git push
allow   ssh host 'bench migrate'
allow   python3 -c "import subprocess; subprocess.run(['git','push'])"
```

Two of these are not adversarial at all. `sudo bench …` and `npx opencode run …` are
things a person or an agent types for ordinary reasons. `( … )` and `{ …; }` grouping
appears in generated shell whenever output redirection spans several commands.

To be fair to the design: `shlex` already neutralizes the *quoting* tricks — `\git push`,
`'g'it push` and `git   push` are all caught correctly. The gap is structural (the first
token is not always the program), not lexical.

**Why it matters.** This is not a subtle degradation. It is the difference between "the
hook enforces these boundaries" — which is what `README.md:16-17`, `hooks/hooks.json:2`
and `docs/BUILD_CONTRACT.md:93-98` all say — and "the hook enforces these boundaries when
they are written in one particular spelling".

The mitigating context is real and should be weighed: the guard's threat model is an
*aligned* Claude that might take a dangerous step out of habit, not an adversary trying to
escape. An aligned Claude does not wrap a command to evade its own hook. But it does type
`sudo bench …`, and it does receive prose from a repository, a brief, or a user that
suggests a wrapped form.

**Realistic failure scenario.** A project's `OPERATIONS.md` records the migrate command as
`sudo -u frappe bench --site dev.local migrate` because that is how the bench is owned on
that machine. Claude follows the documented command. The live-site ask never fires; the
migration runs against whatever `dev.local` currently is, unconfirmed.

**Recommended fix.** Add a normalization pass before `program()`:

- Strip a leading run of `VAR=value` assignments.
- Unwrap a known set of prefix commands (`sudo`, `env`, `nice`, `nohup`, `time`,
  `command`, `stdbuf`, `setsid`, `doas`, `timeout`, `xargs`) by skipping the wrapper and
  its options and re-testing the remainder.
- For `bash -c`/`sh -c`/`zsh -c`/`eval`, recursively feed the quoted payload back through
  `check()` — `shlex` has already extracted it as a single token, so this is cheap.
- Strip surrounding `(`/`)`/`{`/`}` tokens.

Each of these is a handful of lines and none of them is the "config system" the phase
report was right to rule out. **Prefer fail-loud over silent extension:** if the first
token is a shell or a known wrapper and the payload cannot be re-parsed, `ask` rather than
allow.

**Regression test:** yes — a wrapped-forms table per rule, in `check_command_boundaries()`.

---

### SEC-003 — P1 — The blanket-staging `deny` is bypassed by ordinary equivalents

- **File:** `config/command-boundaries.json:46-78` (rule `blanket-staging`),
  matched at `hooks/guard.py:199-205`.
- **Confidence:** **High** — both halves reproduced.

**Description.** The rule matches only the literal argument tokens `.`, `-A`, `--all`.
Git accepts several other spellings of "stage everything", and none is covered.

**Evidence, part 1 — the guard's decision** (through the real hook process):

```
deny    git add .
deny    git add -A
deny    git add -A -- .
allow   git add -Av
allow   git add -vA
allow   git add -u
allow   git add :/
allow   git add *
allow   git add ./
```

**Evidence, part 2 — those forms really are blanket staging.** Verified in a throwaway
repository created and destroyed inside the audit scratchpad (5 files eligible; `git add
-A` stages 5 as the control):

```
git add -Av  -> staged 5 file(s)
git add -vA  -> staged 5 file(s)
git add :/   -> staged 5 file(s)
git add *    -> staged 5 file(s)
git add ./   -> staged 5 file(s)
git add -u   -> staged 1 file(s)   (every tracked modification, repo-wide)
git add -A   -> staged 5 file(s)   (control)
```

**Why it matters.** This is the one rule the whole system chose to make a `deny` rather
than an `ask`, on the stated grounds that "deny is free where a correct alternative always
exists". A deny that five ordinary spellings walk past is a deny in name. And unlike
`SEC-002`, no adversarial intent is needed: `git add ./` and `git add *` are things people
and agents type by habit. `git add -u` in particular is the natural command for "stage my
modifications", and it sweeps in exactly the unrelated tracked edits that
`skills/orchestration/SKILL.md:454-461` ("Dirty, safe to continue… leave those files
untouched") exists to protect.

Note the asymmetry with the delegated engine: `git add -Av` **is** denied there (the glob
`git add -A*` matches it) while the hook allows it. The two engines disagree, and the
drift test cannot see it because it only checks the `examples` array.

**Realistic failure scenario.** The user has unrelated uncommitted work in three tracked
files. The task completes, review passes, and the commit step runs `git add -u` (or
`git add ./` from the repository root) because it reads as "stage what I changed". The
unrelated work is committed under the task's commit message. The pre-commit cleanup
checklist at `skills/orchestration/SKILL.md:468-471` asks Claude to verify no unrelated
dirty files are included, but that is prose, and the hook — the mechanism that exists
because prose gets skipped — did not fire.

**Recommended fix.** In `config/command-boundaries.json`, extend
`blanket-staging.any_argument` to include `-u`, `--update`, `:/`, `./`, `*`, and `:/*`;
and, in `hooks/guard.py`, match short-option *clusters* rather than whole tokens — a token
matching `^-[A-Za-z]*A[A-Za-z]*$` is `-A`. The delegated translation needs the mirror
change so the two engines agree. Consider whether `-u` deserves its own rule with its own
reason text, since "stage only what this task changed" is a different correction from
"never sweep the tree".

**Regression test:** yes. All nine forms above, asserted against both engines, with the
`git add hooks/guard.py` / `git add .gitignore` counter-examples kept so the fix does not
over-reach.

---

### SEC-004 — P1 — The hook fails open, silently, on structurally-valid-but-unusable rule data

- **File:** `hooks/guard.py:118-141` (`load_rules`), `:222-234` (`check`).
- **Confidence:** **High** — reproduced against a copy of the plugin tree.

**Description.** `load_rules()` returns `None` only when reading or indexing the file
raises `OSError`, `ValueError`, `KeyError` or `TypeError`. Every other outcome returns a
*list*, possibly empty. `check()` (`:222-229`) tests `if RULES is None` to decide whether
to enter the documented degraded mode — asking on `GUARDED_PROGRAMS`. An empty or
all-filtered list is not `None`, so `match_rule` iterates nothing, returns `None`, and the
hook allows every command with no output and exit 0.

This is precisely the failure the file's own comment says it must not have
(`hooks/guard.py:105-109`): *"If the boundary data cannot be read there are no rules to
apply, and silently enforcing nothing is the one failure mode this hook must not have."*
The guard is correct for *unreadable* data and wrong for *unusable* data.

**Evidence.** Copies of the plugin tree with a mutated `config/command-boundaries.json`,
probed through the real hook process (`allow` = no output, exit 0):

| Mutation | `git push` | `git add .` | `bench migrate` | `ls -la` |
| :-- | :-- | :-- | :-- | :-- |
| *(unmodified)* | ask | deny | ask | allow |
| file absent | ask | ask | ask | allow |
| empty file | ask | ask | ask | allow |
| invalid JSON | ask | ask | ask | allow |
| no `rules` key | ask | ask | ask | allow |
| **`rules: []`** | **allow** | **allow** | **allow** | allow |
| **`rules: {}`** | **allow** | **allow** | **allow** | allow |
| **`rules: "x"`** | **allow** | **allow** | **allow** | allow |
| **every rule `hook: null`** | **allow** | **allow** | **allow** | allow |
| **rules are strings** | **allow** | **allow** | **allow** | allow |
| `identifiers: []` on one rule | ask | deny | ask | **ask** *(see `CFG-002`)* |
| one rule's `kind` unimplemented | **allow** | deny | ask | allow |

The last row deserves separate attention: changing one rule's `match.kind` to something
neither engine implements silently removes *that rule only*, from both engines, with no
signal at runtime. `git push` becomes unguarded and the other eight rules keep working, so
nothing looks broken.

**Why it matters.** The four rows in the middle are all reachable by a plausible edit: a
merge that resolves `rules` to `[]`, a truncated write, a `jq` filter that returns an
object instead of an array, a well-meaning "temporarily disable the hook" that nulls the
decisions. In each case the plugin still loads, `claude plugin list` still says enabled,
no error appears anywhere, and every boundary is gone.

**Recommended fix.** Make `load_rules()` return `None` whenever it cannot produce a usable
rule set — no rules at all, no rule with a `hook` decision, any element that is not a dict,
or any rule whose `match.kind` this engine does not implement. Then the existing degraded
`ask` path covers all of it. Add the unimplemented-kind case to `UNREADABLE_REASON`'s
wording so the user is told *which* rule is being ignored. Mirror the same change in
`scripts/delegate` (see `BUG-004`), where the equivalent state currently produces a
zero-deny policy rather than a refusal.

**Regression test:** yes, and it is cheap — the mutation table above, driven through
`check()` with a patched `RULES`. This is currently untestable-by-omission because the
tests never exercise `load_rules` at all.

---

### SEC-005 — P1 — The hook crashes on unexpected payload shapes, which fails open

- **File:** `hooks/guard.py:237-243` (`main`).
- **Confidence:** **High** for the crash (reproduced); **High** for the consequence, which
  follows from Claude Code's documented hook exit-code semantics (exit 2 = blocking error;
  any other non-zero = non-blocking error, execution continues).

**Description.** `main()` guards against invalid JSON (`except ValueError`) and against a
non-string `command`, but not against the payload — or `tool_input` — being something
other than a mapping. `payload.get(...)` then raises `AttributeError`, the process exits
1, and the tool call proceeds.

**Evidence** (payloads piped to the real hook):

| Payload | Result |
| :-- | :-- |
| `[]` | **exit 1** — `AttributeError: 'list' object has no attribute 'get'` |
| `"hello"` | **exit 1** — `AttributeError: 'str' …` |
| `5` | **exit 1** — `AttributeError: 'int' …` |
| `{"tool_input": ["git push"]}` | **exit 1** — `AttributeError: 'list' …` |
| `{"tool_input": "git push"}` | **exit 1** — `AttributeError: 'str' …` |
| `null`, `{}`, `{"tool_input": null}`, `{"tool_input":{"command":null}}`, `{"tool_input":{"bash_id":"x"}}`, `not json`, empty stdin | allow, exit 0 (correct) |

`docs/reports/PHASE_01_5_REPORT.md` records "Malformed payloads … Exit 0, no stdout, no
stderr — nothing is blocked when the payload is not understood" as verified. That
verification used four payloads, all of which are dict-shaped; the shapes above were never
tried, and the claim as stated is not true.

The same class shows up in the rule data: `rules: 42` (uncaught `TypeError` from iterating
an int at `hooks/guard.py:125`) and a rule missing its `match` key (uncaught `KeyError` at
`:171`) both make the hook exit 1 for **every** command, i.e. enforce nothing while
printing a traceback into the user's session on each Bash call.

**Realistic failure scenario.** Claude Code adds a field or changes the payload envelope in
a future release — for instance wrapping `tool_input` in a list for batched calls. Every
Bash command in every session then produces a traceback and no enforcement, and because
the failure is non-blocking, the only visible symptom is stderr noise the user learns to
ignore.

**Recommended fix.** Wrap the whole body of `main()` in
`try: … except Exception: return` — a hook whose entire contract is "print a decision or
print nothing" should never propagate an exception — and additionally type-check:
`if not isinstance(payload, dict): return`, and the same for `tool_input`. Optionally write
one line to stderr on the exception path so a persistent failure is diagnosable rather than
merely silent.

**Regression test:** yes. The payload table above, run through `main()` with stdin
redirected — this is `TEST-001`'s first case.

---

### SEC-006 — P1 — Destructive Git and filesystem operations are unguarded in both layers

- **File:** `config/command-boundaries.json` (rule set), `scripts/delegate:138-143`
  (`opencode_permissions`, base `{"*": "ask"}`).
- **Confidence:** **High** — reproduced against both engines.

**Description.** The rule set covers `push`, `add`, `commit`, bench/site access, database
clients, `frappe.*` snippets and bare agent runs. It covers nothing that destroys work.
Inside a delegated OpenCode run the base policy is `{"*": "ask"}` and the dispatcher passes
`--auto`, whose documented meaning is "auto-approve permissions that are not explicitly
denied" — so *everything not on the deny list runs without a prompt and without a human*.

**Evidence** (hook decision / delegated decision):

```
allow  allow     git reset --hard HEAD~5
allow  allow     git reset --hard origin/main
allow  allow     git checkout -- .
allow  allow     git restore .
allow  allow     git clean -fdx
allow  allow     git stash          /  git stash clear
allow  allow     git rebase -i HEAD~3
allow  allow     git filter-branch --all
allow  allow     git branch -D main
allow  allow     git update-ref -d refs/heads/main
allow  allow     git reflog expire --expire=now --all
allow  allow     git remote set-url origin x
allow  allow     rm -rf /home/mustafa/Projects
allow  allow     rm -rf .
allow  allow     find . -name '*.py' -delete
allow  allow     truncate -s 0 README.md
allow  allow     shred -u README.md
allow  allow     chmod -R 777 .
```

**Why it matters.** The plugin's stated purpose includes "Git safety rules"
(`.claude-plugin/plugin.json:3`) and it protects the *staging* boundary — the one whose
worst case is a messy commit that `git reset` can undo — while leaving the boundary whose
worst case is unrecoverable loss of the user's uncommitted work completely open. The
priority is inverted relative to impact.

For Claude's own commands the practical exposure is moderate: an `ask` on
`git reset --hard` would be useful, but Claude Code's own permission system may prompt on
some of these anyway depending on the user's settings, and a human is present. For a
**delegated** run there is no such backstop. An implement-mode agent that decides the
working tree is in a bad state and "cleans up" with `git reset --hard` or `git clean -fdx`
destroys whatever the user had uncommitted, unattended, and the dispatcher reports
`status: completed`.

`docs/BUILD_CONTRACT.md:263-264` states the rule that ought to be enforced here — *"If the
working tree is dirty before you start with changes that are not yours, stop and ask. Do
not stage or revert anything you did not create."* — and `skills/orchestration/SKILL.md:454-461`
repeats it. Neither is enforced anywhere.

**Realistic failure scenario.** A delegated implement run's first edit produces a syntax
error; its tests fail; it decides to start over from a clean state and runs
`git checkout -- .` (or `git reset --hard HEAD`). The user's three unrelated uncommitted
files — which the orchestrator specifically inspected and decided were safe to leave
alone — are gone, with no reflog entry for unstaged work and no record in the result.

**Recommended fix.** Add two rules to `config/command-boundaries.json`:

- `destructive-worktree` — `program_subcommand` on `git` for `reset`, `checkout`,
  `restore`, `clean`, `stash`, `rebase`, `filter-branch`, `filter-repo`, `update-ref`,
  `reflog`, `gc`, `prune`, `branch` (with `any_argument` narrowing where a safe form
  exists: `git reset` without `--hard`/`--merge`/`--keep` is safe, `git checkout <branch>`
  is safe, `git stash list` is safe). `hook: "ask"`, `delegated: "deny"` — a delegated
  implementer never needs to discard the tree, and the orchestrator owns recovery.
- `destructive-filesystem` — a `program`-kind or new `program_option`-kind rule for
  `rm -r`/`rm -f`, `shred`, `truncate`, `dd`, and `find … -delete`. `hook: "ask"`,
  `delegated: "deny"`.

Narrowing matters here: an over-broad `git checkout*` deny would break ordinary branch
switching, which is exactly the "rule that fires on nothing dangerous teaches the reader
the rule is noise" failure the Phase 01.5 report reasons about correctly. Use
`any_argument` and keep counter-examples in the data.

**Regression test:** yes, in both directions — the destructive forms denied/asked, and
`git reset HEAD~1`, `git checkout -b feature`, `git stash list`, `rm README.bak` left
alone.

---

### BUG-001 — P1 — A nested object shadows the real report, turning FAIL into PASS

- **File:** `scripts/delegate:553-576` (`_is_report`, `_reports`), `:605-632`
  (`extract_report`).
- **Confidence:** **High** for the mechanism (reproduced). **Medium** for likelihood — it
  needs the agent to emit a nested object carrying the discriminator key, which the
  contracts do not ask for.

**Description.** `_reports` scans backwards with `text.rfind("{", 0, index)` and yields the
first candidate that satisfies the mode's discriminator; `extract_report` returns that one.
Because `rfind` finds the *last opening brace*, and a nested object's brace comes after its
parent's, **a nested object is always considered before the object that contains it**. If
the nested object happens to carry the discriminator with an enumerated value, it wins —
and the outer report, including all its findings, is discarded.

The docstring at `:617-619` describes this as a feature: *"a nested report is found rather
than skipped along with its wrapper."* That is true for the `{"wrapper": {…report…}}`
shape the test at `tests/test_parser.py:105-106` covers. The same mechanism, applied to a
report that *contains* a nested discriminator, silently substitutes the wrong verdict.

**Evidence** (`extract_report` called directly on each string):

| Input | Mode | Result |
| :-- | :-- | :-- |
| `{"verdict":"FAIL","summary":"blocking issue found","previous_run":{"verdict":"PASS","summary":"old"}}` | review | `present`, **`verdict='PASS'`**, keys `['summary','verdict']` |
| `{"verdict":"FAIL","summary":"s","findings":[…],"context":{"verdict":"PASS"}}` | review | `present`, **`verdict='PASS'`**, keys `['verdict']` |
| `{"status":"incomplete","summary":"could not finish","prior":{"status":"completed"}}` | implement | `present`, **`status='completed'`** |
| `{"analysis":"partial","not_analysed":["tests"],"note":{"analysis":"complete"}}` | onboard | `present`, **`analysis='complete'`** |
| `{"verdict":"FAIL","summary":"the earlier run said {\"verdict\": \"PASS\"}"}` | review | `present`, `verdict='FAIL'` — correct; escaped braces inside strings are handled properly |

The fourth row is the mildest and the second the worst: the orchestrator receives
`{"verdict": "PASS"}` with **no findings at all**, `result_block: "present"`, and
`off_contract_keys: []`. Nothing about the result says anything went wrong.

**Why it matters.** `skills/orchestration/SKILL.md:351-368` makes PASS the gate to
"context check, cleanup, and commit". A FAIL silently converted to a PASS means the
orchestrator commits a change that the independent reviewer rejected — the exact defect the
`onboard` mode was created to prevent, running in the opposite direction. The report's own
framing applies: *"at the point the orchestrator reads `agent_report.verdict`, a fabricated
PASS is indistinguishable from a real one."*

The fail-direction is what makes this P1 rather than P2. Every other bounded failure in
this parser fails closed (`missing`, `invalid`, a dropped over-long report). This one fails
open into a false approval.

**Realistic failure scenario.** Attempt 2 of a fix loop. Codex, reviewing a fix, structures
its answer to include what the previous attempt concluded:
`{"verdict":"FAIL", …, "previous_review":{"verdict":"PASS","summary":"attempt 1 passed the unit tests"}}`.
The dispatcher hands the orchestrator `PASS`. The fix loop exits, cleanup runs, the commit
is created, and the blocking finding is never seen. Note that this shape is *encouraged* by
the fix loop's own design, which asks the agent to reason about the previous attempt.

**Recommended fix.** Short term, two lines: prefer the **outermost** qualifying object. The
cleanest form given the existing scan is to keep collecting qualifying candidates and
return the one with the smallest start offset among those whose decoded span is maximal —
or, more simply, scan forward with `find("{")` from position 0 and, among qualifying
candidates, return the last *top-level* one (a candidate whose start offset is not inside a
previously decoded span). Either way the invariant to assert is: **a qualifying object that
is nested inside another qualifying object never wins.**

Long term this is `IMP-001`, and the project already knows the answer. From
`docs/reports/PHASE_03_REPORT.md`: *"Stop guessing. Have the dispatcher generate a random
token per run, put it in the brief as the delimiter the agent must wrap its report in, and
extract by that token."* That change also retires the two `KNOWN_GAPS` and the whole
class this finding belongs to. It was left as the user's decision; this finding is the
argument for making it.

**Regression test:** yes — all four shadowing rows above, plus the existing wrapper case
kept green, plus an assertion that the returned report retains its `findings` key.

---

### BUG-002 — P1 — The timeout does not bound the run; grandchildren survive it

- **File:** `scripts/delegate:508-531` (`execute`).
- **Confidence:** **High** — reproduced.

**Description.**

```python
except subprocess.TimeoutExpired:
    proc.kill()
    out, err = proc.communicate()      # <-- no timeout
    status = "timeout"
```

Two defects in three lines. First, `proc.kill()` signals only the direct child; any
grandchild it spawned keeps running and keeps the inherited stdout/stderr pipe open.
Second, the recovery `communicate()` has no timeout, so it blocks until those pipes close —
which, with a live grandchild holding them, is never.

**Evidence.** Stub `opencode` that leaks one background grandchild and then sleeps:

```sh
#!/bin/sh
sh -c "sleep 25" &
sleep 25
```

Run through the real dispatcher with `--timeout 2`:

```
VERDICT: dispatcher HUNG >20s despite a 2s agent timeout
         (grandchild inherited the stdout pipe; the second communicate() has no timeout)
```

The dispatcher never returned; the harness had to abandon it.

**Why it matters.** Real agent CLIs spawn children constantly — a shell per tool call, and
in OpenCode's case an LSP or MCP subprocess. The timeout exists for exactly one scenario, a
hung agent, and a hung agent is precisely the case most likely to have left a child behind.
`config/model-routing.json` sets the DIFFICULT timeout to 1800 s and
`skills/orchestration/SKILL.md:264-267` instructs Claude to run those in the background, so
a hung dispatcher is a background process nobody is watching, holding a workspace and a
zombie agent, with no result ever produced. Worse: after the "timeout" the grandchildren are
still executing the agent's shell commands.

**Realistic failure scenario.** A NORMAL implement run wedges. At 900 s the dispatcher
kills `opencode` but its LSP child holds the pipe. The background Bash call never
completes; the orchestrator waits for a result that will not come; the fix loop's attempt
accounting stalls; and the agent's leftover child processes continue to run against the
repository.

**Recommended fix.**

1. `subprocess.Popen(..., start_new_session=True)`, then on timeout
   `os.killpg(os.getpgid(proc.pid), signal.SIGTERM)`, a short grace period, then `SIGKILL`
   on the group. That kills the whole tree.
2. Give the recovery read a bound: `proc.communicate(timeout=15)`, and on a second
   `TimeoutExpired` accept `out, err = "", ""` and still return `"timeout"`. The dispatcher
   must always produce a result — that is its documented contract
   (`scripts/delegate:8-10`).
3. While there, record partial output: today a timed-out run's stdout is whatever
   `communicate()` managed to collect, and if step 2 gives up it is empty. Reading the
   pipes non-blockingly before the kill would preserve the transcript, which is the one
   artifact a timed-out run leaves behind.

**Regression test:** yes — the leaked-grandchild stub above, asserting the dispatcher
returns within a bounded wall-clock time with `status == "timeout"`, and that no
descendant survives.

---

### BUG-003 — P1 — Non-UTF-8 bytes on the agent's stdout crash the dispatcher

- **File:** `scripts/delegate:512-520` (`Popen(..., text=True)`), `:796-797`
  (`write_text` without an explicit encoding).
- **Confidence:** **High** — reproduced.

**Description.** `Popen(..., text=True)` decodes the child's streams with the locale
encoding and `errors="strict"`. A single invalid byte raises `UnicodeDecodeError` inside
`communicate()`, which `execute()` does not catch (it catches only `OSError`, at `:521`).
The exception propagates out of `main()`; the process exits 1; no result JSON is printed;
`agent-output.txt` and `agent-stderr.txt` are never written, so even the transcript is lost.

**Evidence.** Stub `opencode` emitting `{"status":"completed","summary":"\xff\xfe"}`:

```
rc=1
stdout: b''
stderr tail: UnicodeDecodeError: 'utf-8' codec can't decode byte 0xff in position 33: invalid start byte
```

The symmetric hazard is on the write side: `Path.write_text(out)` uses the locale encoding,
so under an ASCII locale a perfectly valid UTF-8 transcript raises `UnicodeEncodeError`.
CPython's PEP 538 locale coercion usually prevents this, but it is one `LC_ALL` away and
costs nothing to close.

**Why it matters.** This is a parser of untrusted output that the project has correctly
hardened against hostile *structure* — bounded three ways, never raising, fails closed —
while leaving hostile *bytes* able to take out the whole run before the parser is reached.
Agent transcripts routinely contain command output; an agent that `cat`s a binary file, a
truncated multi-byte character at a buffer boundary, or an ANSI-heavy progress renderer are
all ordinary ways to get a stray byte. And exit 1 is outside the documented contract
(`scripts/delegate:8-10`: *"Exit status is 0 whenever a result was produced… Exit status 2
means the invocation itself was wrong"*), so the orchestrator has no defined handling for it.

**Realistic failure scenario.** A 900-second NORMAL implement run finishes successfully and
its transcript happens to include a byte from a binary file the agent inspected. The
dispatcher exits 1 with a traceback. The orchestrator has no result, no report, and no
transcript — only the workspace path from stderr, which contains just `brief.md`. The work
was done; the record of it is gone; the natural next step is to re-run it.

**Recommended fix.** Two lines. Pass `errors="replace"` to `Popen` (or drop `text=True`,
capture bytes, and decode explicitly with `errors="replace"`), and give both `write_text`
calls `encoding="utf-8", errors="replace"`. Also widen `execute`'s `except OSError` to
`except Exception` so that any decode-layer surprise becomes `status: "error"` with a
message rather than a traceback — the function's contract is to return a five-tuple, and it
should hold that unconditionally.

**Regression test:** yes — a stub emitting invalid UTF-8, asserting `status` is a real
value, the result JSON is printed, and `agent-output.txt` exists.

---

### SEC-007 — P2 — `database-client` covers only MySQL/MariaDB

- **File:** `config/command-boundaries.json:254-280` (rule `database-client`).
- **Confidence:** **High.**

**Description.** The rule names `mysql` and `mariadb`. The same file's `site-unnamed` rule
lists `postgres` and `db-console` among the bench subcommands that resolve a site
(`:189`, `:164`) — so the data itself acknowledges that Frappe runs on PostgreSQL here.
`psql` is not guarded. Neither is `redis-cli` (Frappe's cache and queue, where
`FLUSHALL` destroys queued jobs), `sqlite3`, or an HTTP call to a running site's API.

**Evidence:**

```
allow  allow     psql -U postgres
allow  allow     redis-cli FLUSHALL
allow  allow     sqlite3 sites/db.sqlite
allow  allow     curl -X POST http://localhost:8000/api/method/frappe.client.delete
```

**Why it matters.** The rule's stated intent is *"A direct route to the database, bypassing
every Frappe-shaped rule around it."* `psql` is that route on a Postgres bench, and the
guard's own subcommand list proves the authors know such benches exist. `curl` against
`frappe.client.delete` is the same reachability over HTTP, which no rule contemplates.

**Recommended fix.** Add `psql`, `pg_dump`, `pg_restore`, `redis-cli`, `mongo`, `mongosh`
and `sqlite3` to `database-client.programs`. The HTTP route is a genuinely different shape
and probably deserves its own rule or an explicit `not_enforced_because` entry saying why
it is out of scope — the value of that field is exactly this: making a deliberate omission
visible.

**Regression test:** yes — extend the rule's `examples`, and keep `cat /etc/mysql/my.cnf`
and `grep mysql notes.txt` as counter-examples.

---

### SEC-008 — P2 — `bench drop-site`, `new-site`, `update`, `restart`, `remove-app` are unguarded

- **File:** `config/command-boundaries.json:141-253` (`site-unnamed`).
- **Confidence:** **High**; the omission is deliberate and documented.

**Evidence:**

```
allow  allow     bench drop-site dev.local
allow  allow     bench new-site x.local
allow  allow     bench update
allow  allow     bench restart
allow  allow     bench remove-app x
allow  allow     bench --force drop-site dev.local
allow  deny      bench backup-all-sites      <- delegated only, via the `bench backup*` glob
```

**Description and why it matters.** `docs/reports/PHASE_01_5_REPORT.md` explains the
omission clearly and the reasoning is sound as far as it goes: the rule is about an
*unnamed* site, and these commands name their site positionally, so they fail the rule's
stated test. `docs/reports/PHASE_04_REPORT.md` open question 4 leaves the decision with the
user: *"`bench drop-site` and `bench new-site` remain unguarded, deliberately… Destructive
and unguarded is still worth your decision."*

That decision is still open, and it should not be. `bench drop-site` deletes a site's
entire database. `bench update` pulls, builds and migrates every site in the bench —
`bench --site x migrate` asks, and `bench update` (which migrates *all* sites) does not.
`bench restart` restarts services. The rule's test is a good test; the conclusion should be
that a *second* rule is needed for the positional-site and bench-wide families, not that
those families are fine.

**Recommended fix.** A new rule, `site-positional-destructive`, covering `drop-site`,
`new-site`, `remove-app`, `uninstall-app` (already covered by `site-unnamed` but harmless
to state), plus a `bench-wide` rule covering `update`, `backup-all-sites`, `restart`,
`migrate-all` and similar. `hook: "ask"`, `delegated: "deny"`, with `intent` text that says
which mistake it prevents — "the wrong named site" and "every site at once" are different
corrections and deserve different reason strings, following the precedent
`site-named`/`site-unnamed` already sets.

**Regression test:** yes.

---

### SEC-009 — P2 — An `ask` is only a boundary while a human is present

- **File:** `config/command-boundaries.json` (five of nine rules decide `ask`),
  `README.md:106-126`.
- **Confidence:** **Medium** — the mechanism is documented Claude Code behaviour; I did not
  exercise the non-interactive modes.

**Description.** `push`, `site-named`, `site-unnamed`, `database-client` and
`frappe-connection` all resolve to `permissionDecision: "ask"`. An `ask` is a prompt. In a
non-interactive session (`claude -p`), in auto-accept mode, or with permission prompts
bypassed, a prompt is not a gate in the same sense — at best it becomes an automatic
refusal, at worst an automatic approval. `deny` is unconditional; `ask` is conditional on a
mode the plugin cannot see and does not document.

**Why it matters.** The live-site boundary — the plugin's most safety-relevant rule family,
the one added after a real incident where three sites were queried unasked — is entirely
built out of `ask`. The README's "Disabling" section correctly explains that disabling the
plugin removes enforcement; it says nothing about the session modes in which the asks stop
being asks. A user running `claude -p "fix the label"` in CI would reasonably believe the
live-site boundary is in force.

The Phase 01.5 report's reasoning for `ask` over `deny` on `push` is correct and should
stand (*"a hook that obstructs every legitimate push gets disabled, which is worse than no
hook"*). The gap is documentation plus, for the live-site family, a possible
reconsideration: `bench --site x migrate` inside an unattended session has no correct
automatic answer.

**Recommended fix.** Document it: one short README subsection stating which rules are
`ask`, that an `ask` requires a human, and that `-p`/auto-accept/bypass sessions should be
treated as unguarded for those rules. Then verify empirically what each mode does with an
`ask` decision, and if any of them auto-approves, consider `deny` for the live-site family
specifically — a delegated run already gets `deny` there for exactly this reason (nobody is
watching), and an unattended Claude session is the same situation.

**Regression test:** not applicable (behavioural, host-dependent). Worth a line in the
README and a note in the boundary data's `decisions` block.

---

### BUG-004 — P2 — Wrong-typed config crashes the dispatcher; zero usable rules do not

- **File:** `scripts/delegate:383-412` (`load_routing`, `resolve_model`), `:67-78`
  (`load_boundaries`), `:727-732` (tier lookup), `:81-135` (`rule_patterns`).
- **Confidence:** **High** — reproduced.

**Evidence** (all with `--dry-run`, so nothing was executed):

| Mutation | Result |
| :-- | :-- |
| routing file absent / invalid JSON | exit 2, clear message *(correct)* |
| `models` is a list | exit 2, "unknown model" *(acceptable)* |
| `tiers` is a list | exit 2, "tier not in …" *(acceptable)* |
| `id` is null | exit 2, clear message *(correct)* |
| **routing is a list** | **exit 1**, `AttributeError: 'list' object has no attribute 'get'` |
| **a model entry is a string** | **exit 1**, `AttributeError: 'str' …` |
| **a tier entry is a string** | **exit 1**, `AttributeError: 'str' …` |
| **`timeout_seconds` is a string** | **exit 0**, dry run succeeds — crashes at run time |
| **`timeout_seconds` is negative** | **exit 0**, accepted |
| **boundary rule missing `match`** | **exit 1**, `KeyError: 'match'` |
| **boundary `rules` are strings** | **exit 1**, `AttributeError: 'str' …` |
| **boundary `rules: []` / `{}` / all `hook: null`** | **exit 0**, policy generated with **0 deny rules** |
| **one rule's `kind` unimplemented** | **exit 0**, policy silently drops that rule (171 rules, `git push` no longer denied) |
| **`subcommands` is a string** | **exit 0**, 179 rules — the string is iterated character by character, generating `bench p*`, `bench u*`, `bench s*`, `bench h*` |

**Why it matters.** Three separate problems.

1. **The exit-code contract is violated.** `scripts/delegate:8-10` promises exit 0 with a
   result or exit 2 for a bad invocation. Exit 1 with a traceback is neither, and the
   orchestration skill's result-reading rules (`skills/orchestration/SKILL.md:302-318`)
   have no case for it.
2. **`load_boundaries`'s fail-closed stance has the same hole as the hook's** (`SEC-004`).
   Its comment is emphatic — *"Refused, not degraded… a run without its permission policy
   is a run with no boundary at all"* — and it is right for an unreadable file and wrong for
   an unusable one. `rules: []` produces `{"*": "ask"}` with zero denies, which under
   `--auto` is unrestricted shell access, and the dispatcher proceeds happily.
3. **Silent rule loss.** The unimplemented-kind row is the worst of these: one rule
   disappears from the delegated policy with no error, while the other eight keep working.
   The test suite catches it (`tests/test_parser.py:449-454`) but only if someone runs the
   tests; at runtime it is invisible. The comment at `scripts/delegate:126` says *"a kind
   this consumer does not implement; the suite fails by rule name"* — which is true, and
   which is a different guarantee from failing at run time.

**Recommended fix.** Validate on load (see `IMP-003`) and route every config problem
through `fail` so it becomes exit 2 with a message. Specifically:
`if not isinstance(routing, dict): fail(...)`; the same for each `models`/`tiers` entry;
`if not isinstance(timeout, (int, float)) or timeout <= 0: fail(...)`. And make
`rule_patterns` returning `[]` for a rule whose `delegated` is `"deny"` a **hard refusal**
rather than a silent omission — that is the one place where "the suite catches it" is not
good enough, because the consequence is a missing boundary in production.

**Regression test:** yes — the mutation table above, asserting exit 2 (not 1) for every
invalid shape and a refusal for the zero-deny and dropped-rule cases.

---

### BUG-005 — P2 — Timeout arguments and values are unvalidated

- **File:** `scripts/delegate:678` (`--timeout`, `type=int`, no bounds), `:730-732`.
- **Confidence:** **High.**

**Description.** `timeout = args.timeout or tier.get("timeout_seconds")` uses truthiness,
so `--timeout 0` is falsy and silently becomes the tier default (confirmed: resolved to
180 for FAST). A negative value passes through to `communicate(timeout=-5)`, which raises
`TimeoutExpired` immediately, so the run is killed instantly and reported as a timeout — a
result that looks like a hung agent. A non-numeric `timeout_seconds` in the routing file
passes `--dry-run` and raises at run time.

**Why it matters.** `--timeout 0` is the natural way to ask for "no timeout", and it
silently means the opposite of both plausible readings. `--timeout -1` produces a result
(`status: "timeout"`, `blocker_reason: "timeout"`, and for review/test modes
`verdict: "BLOCKED"`) that the orchestration skill's `### Handling BLOCKED` rules will act
on as a real environment blocker.

**Recommended fix.** `type=int` plus an explicit check: `if args.timeout is not None and
args.timeout <= 0: fail("--timeout must be a positive number of seconds")`. Use
`args.timeout if args.timeout is not None else tier.get(...)` — the same
`is not None` discipline `--effort` already uses correctly at `:736`. Validate
`timeout_seconds` from the config the same way.

**Regression test:** yes, cheap — three `fail` assertions.

---

### BUG-006 — P2 — A legitimate commit message can be denied

- **File:** `hooks/guard.py:24` (`SEPARATORS`), `:247` (`SEPARATORS.split(command)`).
- **Confidence:** **High** — reproduced.

**Description.** The separator split runs on the raw command text, before any quote
awareness. A `;`, `&&`, `|` or `&` inside a quoted argument therefore creates a fake
segment, and the fragment after it is matched as if it were a command.

**Evidence** (through the real hook):

```
deny    git commit -m "wip; git add . "        <- a legitimate commit, DENIED
deny    echo 'a && git add -A '                <- DENIED
ask     echo "step; bench migrate "
ask     echo "see frappe.db docs"
ask     grep -r myfrappe.db .
allow   git commit -m "see docs; git add ."    <- the same shape, allowed (no trailing space)
allow   echo "a | git add ."
```

The last two rows show how fragile this is: whether a false positive fires depends on
trailing whitespace, because `shlex` fails on the unbalanced quote and the fallback
`segment.split()` happens to leave `.'` (no match) versus `.` and `"` (match).

**Why it matters.** The `ask` false positives are documented and accepted
(`docs/reports/PHASE_01_5_REPORT.md` open question 2: *"Harmless direction — an ask on a
harmless command, never a deny"*). That claim is now false: this is a **deny** on a
harmless command, and a deny is unconditional. The user cannot approve it; the only route
forward is to reword the commit message. And the Phase 01.5 report's own reasoning about
why a false deny is costly applies directly: *"A deny that fires on nothing dangerous
teaches the reader that the rule is noise. The next deny it issues is the one that
matters."*

The `grep -r myfrappe.db .` row is a second, smaller issue: the `segment_text` pattern at
`hooks/guard.py:134-136` has a trailing `\b` but no leading boundary, so any identifier
suffixed onto another word matches.

**Recommended fix.** Split on separators *after* tokenizing, not before — walk the
`shlex.split` token list and start a new segment at a token that is exactly `;`, `&&`,
`||`, `|` or `&` (shlex yields these as separate tokens when unquoted, and keeps them
inside the string when quoted, which is exactly the distinction needed). Keep the current
raw-text split only as a fallback when `shlex` raises. Add a leading `\b` to the
`segment_text` pattern.

Note that this change would also *lose* the heredoc-body catch that the current raw split
gives for free (`bash <<'EOF'\ngit add -A\nEOF`), so keep the newline split on the raw text
and apply the token-aware split within each line.

**Regression test:** yes — the six rows above as counter-examples, plus the heredoc case as
a positive, so the fix cannot silently trade one for the other.

---

### CFG-001 — P2 — Tier names are duplicated, and two ladder rungs have no tier

- **File:** `scripts/delegate:667` (`--tier` choices), `config/model-routing.json:27-85`.
- **Confidence:** **High.**

**Description.** Two related problems in the routing data's relationship with its consumer.

1. `build_parser` hard-codes `choices=("FAST", "SMALL", "NORMAL", "DIFFICULT")` while the
   tier's effort and timeout are read from `routing["tiers"][args.tier]`. That is a second
   copy of the tier names, in the one file whose design principle
   (`config/command-boundaries.json:4`, and the whole Phase 03 single-sourcing patch) is
   that a rule is written once. A tier added to the routing file is rejected by the parser;
   a tier removed from the file passes the parser and then fails at `:728`.
2. `escalation_ladder` has six rungs; two of them — `"fallback"` (GLM-5.3) and
   `"exceptional escalation"` (Claude Opus) — have `stage` values that are not tier names,
   so there is no `tiers` entry for them and therefore no `effort` or `timeout_seconds`.
   `skills/orchestration/SKILL.md:164-173` instructs Claude to *"move up the
   `escalation_ladder` in the routing file one step at a time"*, and
   `:405-415` makes attempt 3 use "one step up the escalation ladder". When that step
   lands on the fallback rung, `--tier` has no value that expresses it and Claude must
   substitute an unrelated tier to get a timeout. The behaviour is undefined and
   undocumented.

**Why it matters.** Problem 2 is the substantive one: the escalation path — the mechanism
that handles repeated implementation failure, i.e. the highest-stakes moment in the
workflow — has two rungs whose timeout and effort come from nowhere. Nothing surfaces this;
Claude will pick something and the choice will be invisible.

Also worth recording under this ID: the routing file contains several keys that **no code
reads** — `tiers.*.description`, `tiers.DIFFICULT.effort_upgrade`, the whole
`escalation_ladder`, and all of `special_models`. That is not a defect (they are there for
the model to read, and the skills reference them), but the audit brief asks which keys code
ignores, and it should be stated: the dispatcher reads only
`models[<name>].{executor,id}` and `tiers[<tier>].{effort,timeout_seconds}`.
`effort_upgrade` in particular is *never* read by any consumer — not the dispatcher, and
not by name in any skill (`skills/orchestration/SKILL.md` says "Raise effort to high" only
via the tier `description` string).

**Recommended fix.** Derive `--tier` choices from `routing["tiers"]` at parser-build time
(the routing file is already loaded before `main` needs the parser, or can be loaded
first). Give the two nameless rungs real tier entries — `FALLBACK` and `EXCEPTIONAL`, with
their own effort and timeout — or state in the routing file which tier's timeout they
borrow. Either way, add a consistency check to the suite: every `escalation_ladder` stage
resolves to a tier, and every tier is a valid `--tier` value.

**Regression test:** yes — one assertion that `set(parser --tier choices) == set(routing
tiers)`, and one that every ladder `stage` and every tier `model` resolves.

---

### CFG-002 — P2 — Neither config file has a schema or any type validation

- **File:** `config/command-boundaries.json`, `config/model-routing.json`, and both
  consumers.
- **Confidence:** **High** — reproduced.

**Description.** Both files are read with `json.loads` and then indexed by key with no
shape checking anywhere. The consequences are enumerated in `SEC-004` and `BUG-004`; this
finding records the underlying cause and one further symptom worth its own note.

**The degenerate-regex symptom.** `hooks/guard.py:134-136` builds the `segment_text`
pattern as `"(?:%s)\\b" % "|".join(...)`. With `identifiers: []` that becomes `(?:)\b`,
which matches at any word boundary — i.e. **every** command. Verified: with that one edit,
`ls -la` returns `ask` with the live-site reason. The hook becomes unusable in a way that
looks like extreme caution rather than a broken config.

**Why it matters.** These two files are the plugin's entire behavioural surface. The design
deliberately moved rules *out* of code and *into* data precisely so they could be edited —
`config/command-boundaries.json:4` says *"Add or edit a rule here, not in a consumer"* —
and then provided no validation for the thing people are invited to edit. The test suite is
the only validator, and it only runs when someone runs it.

**Recommended fix.** See `IMP-003`. At minimum, and without adding a dependency: a
`validate_rules(rules)` function in each consumer that checks each rule is a dict with a
`name` (string), a `match` (dict) whose `kind` this consumer implements, non-empty
`programs`/`subcommands`/`options`/`identifiers` lists as the kind requires, and a
`hook`/`delegated` value in `{null, "ask", "deny"}`. Failure means the whole rule set is
unusable — degraded `ask` in the hook, refusal in the dispatcher. A JSON Schema file in
`config/` plus a suite check that both real files validate against it is the belt-and-
braces version and costs nothing at runtime.

**Regression test:** yes — the mutation tables in `SEC-004` and `BUG-004`.

---

### DOC-001 — P2 — `claude plugin validate . --strict` now fails, and always exited 0 anyway

- **File:** `.claude-plugin/plugin.json`, `README.md:87-99`, every
  `docs/reports/PHASE_0*_REPORT.md` verification table.
- **Confidence:** **High** — reproduced on Claude Code 2.1.258.

**Evidence:**

```
$ claude plugin validate .
Validating marketplace manifest: …/.claude-plugin/marketplace.json
⚠ Found 1 warning:
  ❯ plugins[0] plugin.json → version: No version specified. …
✔ Validation passed with warnings
rc=0

$ claude plugin validate . --strict
… same warning …
✘ Validation failed (--strict treats warnings as errors)
rc=0
```

**Description.** Three separate things fall out of this.

1. **The documented verification step now fails.** `docs/BUILD_CONTRACT.md:313-314`
   requires every phase report to record *"Commands run and their results — at minimum
   `claude plugin validate .`"*, and every report records
   `claude plugin validate . --strict` → `✔ Validation passed (exit 0)`. That command now
   prints `✘ Validation failed`. The cause is the deliberate removal of `version` in commit
   `a970b29`, whose reasoning (recorded in `README.md:87-99` and the commit body) is sound
   — a pinned version would freeze the install stamp. But the trade-off with `--strict` was
   not noticed, and the repository's own standard verification command is now red.
2. **The exit code proved nothing, in either direction.** `validate --strict` exits **0**
   even when it prints "Validation failed". Every report row that reads
   `✔ Validation passed (exit 0)` was therefore recording an exit code that would have been
   0 regardless. This is worth stating because the reports lean heavily on exit codes as
   evidence, and here the evidence was inert.
3. **What is being validated changed.** With `marketplace.json` present, the command
   validates the *marketplace* manifest, not `plugin.json` directly, contradicting
   `docs/reports/PHASE_01_REPORT.md`'s "validated `.claude-plugin/plugin.json`".

**Recommended fix.** Decide and document. Either (a) keep no `version` and change the
documented verification to `claude plugin validate .` without `--strict`, adding one line
to the README explaining that `--strict` will flag the missing version *on purpose*; or
(b) add a `version` and accept the install-stamp pinning, which the README argues against.
(a) is the better trade given the reasoning already recorded. Whichever is chosen, stop
citing the exit code of `validate --strict` as evidence — grep the output instead.

**Regression test:** not a unit test — a one-line note in the README and, if desired, a
line in `tests/test_parser.py` that shells out to `claude plugin validate .` and greps for
`✘`. That last one adds an external dependency to a suite that is proudly dependency-free,
so a README note is probably the right weight.

---

### DOC-002 — P2 — The authoritative specs contradict the shipped `onboard` mode

- **File:** `docs/phases/PHASE_02_PROJECT_CONTEXT_AND_IMPACT.md:337-341`,
  `docs/phases/PHASE_03_IMPLEMENTATION_AND_QUALITY_LOOP.md` ("Codex Modes"),
  vs `scripts/delegate:27` and `skills/project-context/SKILL.md:84-91`.
- **Confidence:** **High.**

**Description.** Phase 02 says *"This onboarding analysis uses Codex **REVIEW** mode as
defined in Phase 03."* Phase 03 says *"Codex has two execution modes: REVIEW and TEST.
REVIEW covers both diff review and the read-only repository analysis used for project
onboarding."* The implementation has four modes and onboarding uses `onboard`, which has no
verdict field. The change is correct — the Phase 03 report's write-up of *why* is one of
the best pieces of reasoning in the repository — and it is recorded as a deviation.

The problem is governance, not correctness. `docs/BUILD_CONTRACT.md:20-21` states: *"If
this file and a phase document disagree about **scope**, this file wins. If they disagree
about **behaviour or rules**, the phase document wins."* A phase document and the
implementation now disagree about behaviour, and by the contract's own rule the phase
document wins — which would mean reverting a correct fix. Meanwhile
`docs/reports/PHASE_02_REPORT.md` open question 4 anticipated exactly this: *"If Phase 03
renames the mode or splits onboarding analysis away from diff review, this section needs
the corresponding edit."* It was not made.

**Why it matters.** Anyone reading the specs to understand the system — which is what they
are for — is told something false about the mode set, and the contract tells them to
believe the specs over the code. The next person to touch the onboarding path has a
documented instruction to route it through `review`, which is the defect the mode was
created to fix.

**Recommended fix.** The specs are deliberately kept as written ("they are the
authoritative specs and record what was specified"), which is a defensible archival
stance. If it is kept, the contract needs a fourth precedence rule: *a spec superseded by a
recorded deviation in a phase report loses to the report.* Otherwise, add a one-line
amendment note at the top of each affected spec section pointing at the deviation. Either
is a five-minute edit; leaving both undone is the only bad option.

**Regression test:** the same mechanism the boundary rules already use — assert that each
spec section that names a Codex mode either matches `d.MODE_NAMES` or carries an explicit
superseded marker.

---

### ARCH-001 — P2 — Nothing tells a session whether enforcement is actually active

- **File:** `skills/orchestration/SKILL.md:11-35` (required preamble), `README.md:58-71`.
- **Confidence:** **High** — observed directly during this audit.

**Description.** The preamble reports `<TIER>`, model, `tree: <clean|dirty>` and
`context: <present|absent>`. It does not report whether the hook is installed and enabled.
There is no in-session way to find out. The README's confirmation step is an out-of-band
`claude plugin list`.

**Evidence.** On this machine, right now:

```
$ claude plugin list
Installed plugins:
  ❯ warp@claude-code-warp   Version: 2.2.0   Scope: user   Status: ✔ enabled
$ claude plugin marketplace list
  ❯ claude-plugins-official
  ❯ claude-code-warp
```

The plugin is not installed and its marketplace is not registered. During this audit I ran
`git init`, `git add a.txt`, `git add -A` and `git commit` inside a throwaway repository
and no hook fired — consistent with enforcement being absent. Nothing in a session would
have told me that.

**Why it matters.** The README itself names the failure mode
(`README.md:66-71`): *"Keep the repository where it is: the marketplace entry is a path to
it, and moving or deleting the directory disables enforcement everywhere."* Combined with
`SEC-004` (a rule file that yields nothing enforces nothing, silently) and `SEC-005` (a
crashing hook is a non-blocking error), there are now three distinct ways for enforcement
to be absent while everything looks normal — and the plugin's own required output line,
which exists precisely to make compliance visible, does not carry the one field that would
show it.

The reasoning that produced the preamble applies here verbatim
(`docs/reports/PHASE_01_REPORT.md`): *"A prose rule can be read and skipped silently; a
required visible output cannot be skipped without the omission being obvious."* The same
argument says enforcement state belongs on that line.

**Recommended fix.** Two options, and the first is nearly free:

1. Add a `guard: <active|unknown>` field to the preamble, established by the same kind of
   cheap check the other two fields use — e.g. `test -n "$CLAUDE_PLUGIN_ROOT"` or a
   `--self-check` flag on `guard.py` that Claude can run. This depends on `PATH-001` being
   resolved.
2. Better, because it does not depend on Claude cooperating: have `guard.py` write a
   heartbeat (a `SessionStart` hook, or a note in the deny reason) so the *hook* announces
   itself rather than being asked about. A `SessionStart` hook that prints one line —
   "frappe-orchestrator: boundaries active, N rules from <path>" — would also surface
   `SEC-004`'s degraded state, since it could report the rule count.

Option 2 is outside Phase 01.5's current scope wording ("Any hook on events other than
`PreToolUse` … Nothing asked for them") and would need the same contract amendment route
the other cross-phase changes took.

**Regression test:** partially — the suite can assert that the preamble template in the
skill contains the new field, the same way `check_dispatcher_invocation()` asserts the
skill's delegate lines.

---

### PATH-001 — P2 — `${CLAUDE_PLUGIN_ROOT}` in skill prose is unverified

- **File:** `skills/orchestration/SKILL.md:143,187,225,336`,
  `skills/project-context/SKILL.md:53`.
- **Confidence:** **Low-Medium** — I could not verify this without installing the plugin,
  which the audit rules exclude.

**Description.** Five places in the skills tell Claude to read or execute a path written as
`${CLAUDE_PLUGIN_ROOT}/…`, including the dispatcher itself
(`skills/orchestration/SKILL.md:225`) and the routing file that the mandatory preamble
requires reading (`:143`). `docs/BUILD_CONTRACT.md:44-45` makes this a layout rule.

`${CLAUDE_PLUGIN_ROOT}` is documented as being substituted in **hook and command
definitions** and exported to **hook processes** — and `hooks/guard.py:91` relies on
exactly that, reading `os.environ.get("CLAUDE_PLUGIN_ROOT", "")` at hook runtime and
degrading to a relative `scripts/delegate` when it is absent. That degradation comment
suggests the authors knew the variable is not universally present.

What is not established anywhere in the repository is whether the variable is set in the
environment of the **Bash tool** when Claude runs a command. If it is not,
`cat ${CLAUDE_PLUGIN_ROOT}/config/model-routing.json` expands to
`cat /config/model-routing.json` — a silent, wrong path, failing with "No such file", after
which Claude will most likely fall back to recalling a model name from memory, which the
skill explicitly forbids (`:18-19`: *"never a name recalled from memory"*).

`CLAUDE_PLUGIN_ROOT` is unset in this session's shell, but that proves nothing here since
the plugin is not installed.

**Why it matters.** If the assumption is wrong, the mandatory preamble's model field, the
delegation command, and the conditional skill reads all break in the same silent way. If it
is right, this finding is a documentation gap only. Either way the repository should not be
guessing about its own most-used runtime path.

**Recommended fix.** Verify it once, in a session with the plugin installed:
`echo "root=[${CLAUDE_PLUGIN_ROOT}]"` through the Bash tool. Record the answer in the
README. If the variable is not available there, the skills need a different mechanism — the
most robust being that `guard.py`'s deny reason already emits an absolute path, so a
`SessionStart` hook could emit the plugin root the same way, once, at the top of the
session.

**Regression test:** not automatable from inside the repository; this is a one-time
verification plus a README line.

---

### TEST-001 — P2 — `hooks/guard.py`'s entry point is entirely untested

- **File:** `tests/test_parser.py`.
- **Confidence:** **High** — measured.

**Description.** The suite imports `guard.py` and exercises `check()` and `match_rule()`
against each rule's `examples`/`not_examples`. It never exercises `main()`. Symbol counts
across the whole test file:

```
guard.main             0 direct calls   (2 textual mentions in comments)
guard.split_tokens     0
guard.program          0
guard.load_rules       0
guard.SEPARATORS       0
guard.GUARDED_PROGRAMS 0
guard.UNREADABLE_REASON 0
guard.OPTS_WITH_ARG    0   (referenced once, not asserted)
grep 'tool_input|hookSpecificOutput|permissionDecision' tests/  ->  no matches
```

So none of the following has a test: the hook payload contract (`tool_input.command`
extraction), the JSON output shape Claude Code parses, segment splitting, deny-outranks-ask
precedence, the degraded `ask` path, or the behaviour on malformed rule data.

**Why it matters.** Four of this audit's P1 findings live in exactly that untested region
(`SEC-002`, `SEC-004`, `SEC-005`, `BUG-006`). The 51-payload matrices in the phase reports
were run **by hand** and are recorded in prose; nothing re-runs them. The contract's own
rule (`docs/BUILD_CONTRACT.md:219-223`) is *"Tests are for the components that fail
silently… a hook that denies the wrong command… announce themselves."* That premise is the
part that turned out to be wrong: a hook that *allows* the wrong command announces nothing,
which is the failure mode of every finding above.

**Recommended fix.** Add `check_hook_payloads()` to the existing suite, in the same style —
a table of `(payload, expected decision)` driven through `main()` with stdin redirected,
plus the malformed-payload table from `SEC-005` and the config-mutation table from
`SEC-004`. This is perhaps 80 lines and needs no new dependency. The hand-run matrices in
`docs/reports/PHASE_01_5_REPORT.md` are the corpus; they should be moved into the suite
rather than left in prose.

**Regression test:** this finding *is* the regression test.

---

### BUG-007 — P3 — Delegation workspaces are never cleaned up

- **File:** `scripts/delegate:785-788, 796-797, 851`.
- **Confidence:** **High.**

`tempfile.mkdtemp` creates `/tmp/delegate-<agent>-<mode>-<random>/` containing `brief.md`,
`agent-output.txt`, `agent-stderr.txt` and `result.json`. Nothing removes it, ever. The
directory is mode `0700` (good) but the files inside are `0664`, so on a machine with a
different umask or a shared `/tmp` the protection is the directory alone.

Persistence is deliberate and correct — `skills/orchestration/SKILL.md:264-267` relies on
the workspace surviving a cut-short run — but "never removed" and "removed eventually" are
different designs, and only the second is a design. Every delegated run leaves a full agent
transcript on disk permanently; on a busy day that is dozens of directories containing the
brief (which may quote repository content) and the complete transcript.

**Recommended fix.** On startup, remove `delegate-*` workspaces older than N days (7 is
generous) from the temp directory, guarded by a `try/except` so cleanup can never break a
run. Or add a `--keep-workspace/--no-keep-workspace` flag defaulting to keeping it and
prune on success. Set the file mode to `0600` while there. **Regression test:** low value;
a single assertion that an old workspace is pruned and a fresh one is not.

---

### BUG-008 — P3 — Discriminator values are matched case-insensitively but passed through raw

- **File:** `scripts/delegate:553-556` (`_is_report`).
- **Confidence:** **High** — the suite asserts the behaviour at
  `tests/test_parser.py:107-108`.

`_is_report` accepts `value.strip().casefold() in allowed`, so `{"verdict":"pass"}` is a
valid report — and `agent_report.verdict` is then delivered to the orchestrator as the
literal string `"pass"`. Every rule in `skills/orchestration/SKILL.md:351-368` and every
contract in the dispatcher speaks of `PASS`/`FAIL`/`BLOCKED`. A case-sensitive comparison
anywhere downstream — Claude's own, or a future consumer's — silently fails to recognise it.
The same applies to `status`, `analysis`, and leading/trailing whitespace, which
`.strip()` accepts but does not remove from the stored value.

**Recommended fix.** Normalize on the way out: after `strip_off_contract`, rewrite the
discriminator to its canonical form (`report[key] = value.strip().upper()` for verdicts,
`.lower()` for `status`/`analysis`), and say so in the skill's result-reading section. Or
decide not to normalize and state that the orchestrator must compare case-insensitively.
Doing neither is the current state. **Regression test:** yes, one case.

---

### BUG-009 — P3 — The delegated globs over-match, and the drift test cannot see it

- **File:** `scripts/delegate:93-124` (`rule_patterns`).
- **Confidence:** **High** — reproduced.

Trailing `*` on program and subcommand prefixes produces denials the hook does not make:

```
hook     delegated  command
allow    deny       mysqldump -u root db          (via "mysql*")
allow    deny       bench backup-all-sites        (via "bench backup*")
allow    deny       git commit --dry-run          (via "git commit*")
```

Some of these are arguably desirable (`mysqldump` and `backup-all-sites` are things a
delegated run should not do). The issue is that they are *accidental* — nobody decided
them, they are not in the data, and the drift check at `tests/test_parser.py:494-507` only
compares the two engines on each rule's declared `examples`, so a divergence in either
direction on any other command is invisible. `git add -Av` (`SEC-003`) is the same class
running the other way: denied in a delegated run, allowed by the hook.

**Recommended fix.** Either narrow the patterns (`"mysql "`, `"mysql"` exact, plus
`"mysql *"`) and add the wanted extras to the data as their own entries, or accept the
over-match and record it in the rule's comment so it is a decision. Extend the engine-
agreement check with a shared corpus of commands — not only the `examples` — so divergences
in both directions fail by name. **Regression test:** yes, as part of the equivalent-forms
corpus `SEC-001` and `SEC-003` also need.

---

### BUG-010 — P3 — The `--help` exemption matches the token anywhere in the segment

- **File:** `config/command-boundaries.json:324-328, 362-366` (`unless_flags`),
  `hooks/guard.py:197-199`.
- **Confidence:** **Medium** — the guard behaviour is reproduced; whether it constitutes a
  real bypass depends on the CLIs, which I did not invoke.

**Evidence:**

```
deny    opencode run 'x'
allow   opencode run 'x' --help
allow   codex exec 'x' --version
allow   codex exec - -h
```

The exemption's design note (`config/command-boundaries.json:190-196` in the `match_kinds`
comment, and the Phase 01.5 patch write-up) is careful and correct about the *substring*
hazard — `codex exec "explain the --help output"` must stay denied, and it does, because
the flag is inside a quoted argument and `shlex` keeps it there. What is not considered is
the flag appearing as a genuine trailing token *after* a real brief.

Whether this is exploitable rests on whether `opencode`/`codex` short-circuit on `--help`
regardless of position. Both are conventional argument parsers (clap and commander-style),
which normally do short-circuit, so the practical risk is low — the command would print
help and exit, not run an agent. But the rule is stated as "an informational flag means the
CLI prints text and exits", and that premise is assumed rather than established, for two
external programs whose parsers are outside this repository's control.

**Recommended fix.** Scope the exemption to the case it was written for: the flag appears
and there is **no other non-option argument** after the subcommand. That keeps
`opencode run --help` and `codex exec --help` exempt and re-denies `opencode run 'brief'
--help`. Two lines in `rule_matches`. **Regression test:** yes — the four rows above.

---

### DOC-003 — P3 — The hook's own description is stale

`hooks/hooks.json:2`: *"Enforces the push, staging, and live-site boundaries whether or not
the orchestration skill loaded."* There are now five rule families — push, blanket staging,
live-site (four rules), commit-inside-a-delegated-run, and bare-agent invocation. The
bare-agent rule is the one a reader is most likely to be surprised by, and it is not
mentioned. `hooks/guard.py`'s module docstring (`:1-13`) has the same omission in its first
line, though its body is accurate. One-line fixes. **Confidence: High.**

---

### DOC-004 — P3 — The contract's `.claude-plugin/` rule is contradicted by the repository

`docs/BUILD_CONTRACT.md:38`: *"`.claude-plugin/` contains **only** `plugin.json`."*
`.claude-plugin/marketplace.json` has been there since commit `a970b29`. Three phase
reports carry a verification row reading `ls -A .claude-plugin` → *"`plugin.json` only —
layout rule holds"* (`PHASE_01_REPORT.md`, `PHASE_01_5_REPORT.md`, `PHASE_04_REPORT.md`),
which is now false.

`marketplace.json` belongs in `.claude-plugin/` — that is where Claude Code looks for it —
so the file is right and the rule is wrong. Amend the contract to
*"`.claude-plugin/` contains only `plugin.json` and `marketplace.json`"*, and note in the
affected reports that the row was superseded, following the convention those reports
already use for corrections. **Confidence: High.**

---

### DOC-005 — P3 — The HEAD commit violates the contract's own Git rules

`docs/BUILD_CONTRACT.md:260-262`: *"No attribution trailers of any kind. No
`Co-Authored-By`, no 'Generated with Claude Code', no tool or model name anywhere in the
message."*

Commit `a970b29` (HEAD) ends with:

```
Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01M31ZSNeburMJkDsjHyaVmV
```

The same commit also adds `.claude-plugin/marketplace.json` and `README.md` — neither of
which is in any phase's allowed file list — and produced no report, which
`docs/BUILD_CONTRACT.md:281-315` requires at the end of every phase. It is labelled
`chore(...)` rather than a phase commit, and the contract has no provision for work outside
the phase system except the amendment route.

This is process drift rather than a defect, but it is worth recording precisely because
this repository's discipline is its main asset: the contract is what makes the phase
reports trustworthy, and the first commit to ignore it is the one that establishes it can
be ignored. Either amend the contract to allow non-phase `chore` commits with a stated
lighter standard, or bring the commit's work under a report. **Confidence: High.**

---

### DOC-006 — P3 — `PHASE_01_REPORT.md` records two things that are no longer true

`docs/reports/PHASE_01_REPORT.md:5` describes `plugin.json` as carrying
`(name, description, version, author, keywords)` — there is no `version` field now, by
deliberate decision. `:49` and the Deviations section record `GLM-5.2` in the routing file;
it is `GLM-5.3`, restored in a later patch.

Both are historical records and the repository's convention is to leave superseded text in
place with a pointer to the correction — a good convention, applied consistently in the
Phase 03 and Phase 04 reports. It was simply not applied here. Add two pointer lines.
**Confidence: High.**

---

### DOC-007 — P3 — `agent-stderr.txt` is written but never named in the result

`scripts/delegate:797` writes it; the result dict (`:808-827`) has `transcript` pointing at
`agent-output.txt` (stdout) and no key for stderr. `skills/orchestration/SKILL.md:309-310`
tells the orchestrator: *"`result_block` — `missing` or `invalid` means the agent returned
no usable report. Read the file at `transcript` before concluding anything."*

For Codex that is exactly the wrong file. The Phase 03 report established by measurement
that Codex puts the banner, the prompt echo, the rendered answer and the token footer on
**stderr**, with stdout carrying only the final message (246 bytes on the clean run). So for
a `status: "failed"` Codex run — where stdout is likely empty and the cause is on stderr —
the orchestrator is pointed at an empty file, and the only in-band diagnostic (`result.error`)
is populated for `error`, `usage_error` and `cli_missing` but **not** for plain `failed`.

Add `"stderr": str(workspace / "agent-stderr.txt")` to the result, include a truncated tail
of stderr in `result["error"]` for `status == "failed"`, and update the skill's bullet to
name both files. **Confidence: High.**

---

### DOC-008 — P3 — `/reload-plugins` is unverified

`README.md:81` tells the user that changes to `hooks/`, `config/` and `scripts/` take
effect *"Next session, or `/reload-plugins` in an open one."* I could not confirm that this
slash command exists in Claude Code 2.1.258 — it is not something the CLI's own help
exposes, and I did not want to assert either way from memory.

If it does not exist, the sentence sends a user to a command that does nothing, and they
will conclude their edit is live when it is not — which is the same shape as the
"protections appear active but are not" class this audit is most concerned with. Verify it
in a live session; if it is wrong, `/plugin` or restarting the session is the correction.
**Confidence: Low** on the claim being wrong; **High** that it is unverified.

---

### TEST-002 — P3 — Further untested critical paths

Measured against the suite:

| Function | Direct references in `tests/test_parser.py` |
| :-- | --: |
| `delegate.execute` | 0 |
| `delegate.opencode_permissions` | 0 |
| `delegate.denied_bash` | 0 |
| `delegate.load_routing` | 0 |
| `delegate.load_boundaries` | 0 |
| `delegate.resolve_model` | 0 |
| `delegate._reports` / `_is_report` | 0 (covered indirectly through `extract_report`) |
| `guard.rule_matches` | 0 (covered indirectly) |

The two that matter most:

- **`opencode_permissions`** produces the structure that Phase 03's "Finding B" was
  entirely about — that agent-level permissions resolve separately and must be written at
  `agent.build.permission.bash` as well as the top level. That finding cost a live probe to
  discover, and **nothing asserts the structure today**. Deleting the `agent` key would
  pass the whole suite. So would changing the base from `"ask"` to `"allow"`.
- **`execute`** is where `BUG-002` and `BUG-003` live.

Also missing: an assertion that `--tier` choices match the routing file's tiers
(`CFG-001`), and any check that `MODES`/`--agent` choices match `ADAPTERS`.

**Recommended fix.** Three small checks: assert `opencode_permissions(rules)` has denies at
both levels and base `"*": "ask"` with zero `allow`; assert `execute` returns a five-tuple
with a bounded wall clock for a hung stub; assert parser choices against the config.

---

### IMP-001 — Improvement — Extract the report by delimiter, not by heuristic

- **File:** `scripts/delegate:153-158` (`_TAIL`), `:538-632` (identification and parsing).

The project already reached this conclusion and left it as the user's call. From
`docs/reports/PHASE_03_REPORT.md`: *"Three rounds tightened it from any fenced JSON to two
contract keys to the contract's own enumerated discriminator, and a counterexample survived
each time… Stop guessing. Have the dispatcher generate a random token per run, put it in
the brief as the delimiter the agent must wrap its report in, and extract by that token."*

`BUG-001` is the counterexample that survived the *fourth* round, and it is the first one
that fails in the unsafe direction. That should settle the decision. Concretely: generate
`token = secrets.token_hex(8)` per run; append to `_TAIL` *"wrap the block in
`<<<REPORT:{token}>>>` … `<<<END:{token}>>>`"*; extract between the markers and
`json.loads` the contents. Keep the existing brace scanner as a **fallback** with its
current bounds, and record which path was used in the result (`result_block: "present" |
"present_fallback" | "invalid" | "missing"`) so the fallback's frequency is measurable
rather than assumed. Both `KNOWN_GAPS` disappear with it.

---

### IMP-002 — Improvement — One shared command-normalization layer

- **File:** `hooks/guard.py`, `scripts/delegate`.

`SEC-001`, `SEC-002`, `SEC-003` and `BUG-009` are one problem seen from four angles: the
rules are single-sourced but the *normalization* is not, so each engine is independently
and differently wrong about what a command is.

The current split is defensible — the file comment argues that "which token is the
subcommand is a fact about each CLI's argument parser, and the dispatcher's glob patterns
have no equivalent question to ask" — and it was right when the dispatcher's job was to emit
globs for a foreign engine. It stopped being right once the two engines were found to
disagree on ordinary commands.

Proposal: a small `boundaries.py` module beside the config, importable by both, providing
`segments(command) -> list[list[str]]` (quote-aware splitting plus wrapper unwrapping plus
recursion into `sh -c` payloads) and `normalize(tokens) -> (program, subcommand, args)`.
`guard.py` uses it directly. `scripts/delegate` uses it to generate patterns *for each
normalized form it needs to cover*, so the glob set widens automatically as normalization
improves. The suite then tests one normalizer against a shared corpus instead of testing
two translations against nine `examples`.

This is a real structural change and it cuts against the contract's "fewer files is better"
principle, so it should be weighed rather than assumed. The argument for it is that the
alternative is fixing every bypass twice, in two idioms, forever — and the divergence this
repository already paid for once (four bench subcommands vs seventy-six) was the same shape.

---

### IMP-003 — Improvement — Schema-validate both config files, and fail closed on unusable data

See `SEC-004`, `BUG-004`, `CFG-002`. A `config/boundaries.schema.json` plus a ~30-line
validator in each consumer, and a suite check that both real config files validate. The
principle to encode: **"unusable" must fail the same way "unreadable" already does** — the
hook degrades to asking, the dispatcher refuses. Today they diverge, and the divergence
always lands on the permissive side.

---

### IMP-004 — Improvement — Sanitize the child environment

- **File:** `scripts/delegate:324` (`env = dict(os.environ)`), `:370` (same for Codex).

Verified: a variable set in the dispatcher's environment is readable by the agent process.
A stub reading `$MY_FAKE_SECRET` returned its value in `agent_report.summary`, i.e. it
would also land in `result.json` and in the orchestrator's context.

The agent CLIs legitimately need most of the environment (`HOME`, `PATH`, `XDG_*`, their
own auth variables), so a strict allowlist is awkward. A pragmatic middle: strip variables
matching an obvious-secrets pattern that the agent has no business with —
`AWS_*`, `GITHUB_TOKEN`, `GH_TOKEN`, `*_SECRET`, `*_PASSWORD`, `NPM_TOKEN`, and any
`FRAPPE_*`/site credential the bench exports — unless explicitly opted in. Record the
stripped names in the result so the behaviour is visible. This is defence in depth rather
than a defect: an agent that wanted secrets could read them from disk anyway. It is worth
doing because the agent's *output* flows back into the orchestrator's context, which is a
much wider audience than the agent's own process.

---

### IMP-005 — Improvement — The orchestration skill's context cost

Measured:

| Skill | Bytes | ≈ tokens |
| :-- | --: | --: |
| `skills/orchestration/SKILL.md` | 23,740 | ~5,900 |
| `skills/frappe-operations/SKILL.md` | 11,369 | ~2,800 |
| `skills/project-context/SKILL.md` | 8,315 | ~2,100 |

The orchestration skill's frontmatter description is deliberately broad — *"any request to
change, add, fix, rename, refactor, or remove something… and equally for any request to
inspect or investigate"* — and that breadth was earned: the Phase 01 report documents three
rounds of live testing to get activation working, and the current wording is the one that
finally covered inspection requests. So the breadth should stay.

The cost is that ~5.9k tokens load on every matching request, including the one-word typo
fix the skill uses as its own example. Roughly 40% of the file is content needed only in
uncommon situations: `## Agent debate` (24 lines, for a feature that has never been
exercised and has no dispatcher mode), `### Handling BLOCKED` triage, `## Deployment request
handling`, and the detailed `### Reading the result` field list.

The pattern the repository already uses successfully is the one to apply: the context skill
is loaded *conditionally* by path reference, with four inline rules covering the FAST/SMALL
case. The same split would work here — keep classification, the preamble, routing, the
delegation invocation, Git/commit/push and live-site rules inline; move debate, BLOCKED
triage and deployment handling behind a path reference read when they apply.

Weigh this against the real risk that a second file is a second chance not to be read. The
Phase 02 report's reasoning applies — *"A second skill whose loading is a second coin flip
would put the context rules behind two of them"* — which is why the split should be by
**path reference from within the loaded skill**, not by a second frontmatter description.

---

### IMP-006 — Improvement — Let the plugin say it is active

See `ARCH-001`. The concrete suggestion: a `SessionStart` hook printing one line —
`frappe-orchestrator: 9 boundary rules loaded from <path>` — which simultaneously
(a) makes a missing install visible, (b) makes `SEC-004`'s zero-rule state visible as
`0 boundary rules`, and (c) gives the user the plugin root, which is the answer to
`PATH-001`. Roughly fifteen lines, one new hook event, and it needs the contract amendment
route since Phase 01.5's scope names `PreToolUse` only.

---

## 6. Security & Trust Boundary Review

### Threat model

Nine actors/inputs, what protects each boundary today, and where it is weak.

| # | Actor / input | What protects it | Weakness |
| :-- | :-- | :-- | :-- |
| 1 | **Accidental or careless user prompt** ("just push it", "clean up the tree") | `hooks/guard.py` asks on push; skill prose for the rest | Push is covered. `git reset --hard` / `git clean -fdx` are not (`SEC-006`). A wrapped or alternately-spelled command is not (`SEC-002`, `SEC-003`). |
| 2 | **Malicious repository contents** (a hostile `opencode.json`, a poisoned `docs/ai-context/OPERATIONS.md`, prompt injection in source comments) | `OPENCODE_CONFIG_CONTENT` outranks a project's `opencode.json` at both levels — **verified live, twice**, and this is genuinely strong work | `OPERATIONS.md` is *designed* to be authoritative (`skills/frappe-operations/SKILL.md:112-117`: *"outranks everything above"*) and is read as instructions. A repository that records its bench path as `sudo -u frappe /opt/bench/env/bin/bench` gets both `SEC-001` and `SEC-002` for free, from a file the workflow is told to trust. |
| 3 | **Malicious filename / path** | `resolve_working_directory` realpaths and requires a git work-tree root; argv is a list, never a shell string | Solid. `--cwd` handling is the best-defended part of the dispatcher. Residual: a TOCTOU between validation and `Popen` (theoretical), and no constraint that `--cwd` is *this* repository (a stated non-goal). |
| 4 | **Malformed Claude Code payload** | `except ValueError` on the JSON parse; `isinstance(command, str)` | Incomplete — non-dict payloads crash, and a crash is a non-blocking error, so the command runs (`SEC-005`). |
| 5 | **Compromised / surprising agent output** | `extract_report` is bounded three ways, never raises, requires the contract's own enumerated discriminator; `strip_off_contract` removes volunteered verdicts | Two gaps. Structurally, a nested object can shadow the real report and flip FAIL to PASS (`BUG-001`). Byte-wise, invalid UTF-8 crashes the whole dispatcher before parsing (`BUG-003`). And `agent_report` flows into the orchestrator's context as data with no injection framing — an agent's `summary` is text Claude reads. The skill's "keep observation and claim apart" rule is the mitigation, and it is prose. |
| 6 | **Unsafe environment variables** | `WSLENV` is extended, not replaced; `PWD` is pinned to `--cwd` | The child inherits everything (`IMP-004`). `PATH` is inherited, which is the mechanism behind #7. |
| 7 | **PATH / executable confusion** | `resolve_program` records `agent_path` and `agent_real_path` in every result and dry run | Excellent mitigation, arrived at the hard way — the repository has a documented case of an entire phase's findings being about the wrong binary. It makes the problem *visible*; it does not prevent it, which the README states plainly. Nothing verifies at run time that the resolved binary is the Linux build. |
| 8 | **Malformed project configuration** (`config/*.json`) | Nothing | The largest structural gap. `SEC-004`, `BUG-004`, `CFG-002`: unusable-but-parsable data disables enforcement silently in the hook and produces a zero-deny policy in the dispatcher. |
| 9 | **A developer working inside a production Frappe repository** | `site-named` and `site-unnamed` ask on every site-touching bench command; the skills require an explicitly-declared development site and forbid `--site all` and site loops | This is the best-reasoned part of the rule set, and the derivation of the 76 subcommands from frappe's own CLI is the right method. But: the ask is only a boundary with a human present (`SEC-009`); a delegated OpenCode run can reach a site via an absolute bench path (`SEC-001`); `bench drop-site` and `bench update` are unguarded (`SEC-008`); and Postgres/Redis routes are unguarded (`SEC-007`). |

### Can a denied command be represented differently and get through?

**Yes, in both engines, and in more than one way.** Demonstrated:

- **Wrapping** — `bash -c`, `sh -c`, `eval`, `sudo`, `env`, `nohup`, `time`, `command`,
  `xargs`, `npx`, `( … )`, `{ …; }`, `VAR=x cmd`. Hook: all bypass. Delegated: all bypass.
- **Path qualification** — `/usr/bin/git push`, `/home/frappe/frappe-bench/env/bin/bench
  migrate`. Hook: caught (it strips the path). Delegated: bypass.
- **Chaining** — `cd /bench && bench migrate`. Hook: caught (it splits on separators).
  Delegated: bypass (under raw-string matching).
- **Equivalent options/pathspecs** — `git add -Av`, `-vA`, `-u`, `:/`, `*`, `./`. Hook: all
  bypass. Delegated: `-Av` caught, the rest bypass.
- **Long-form option syntax** — `bench --site=dev.local migrate`. Both catch it, but the
  hook attributes it to the wrong rule (`site-unnamed` instead of `site-named`) and
  therefore gives a reason text that says no site was named when one was. Same decision,
  wrong explanation.
- **Informational-flag exemption** — `opencode run 'brief' --help`. Hook: exempt
  (`BUG-010`); probably harmless in practice, unverified.

### Can a safe command be blocked because parsing is too broad?

**Yes.** `git commit -m "wip; git add . "` is **denied** — a hard block on a legitimate
command with no user override (`BUG-006`). `echo "see frappe.db docs"` and `grep -r
myfrappe.db .` ask (accepted, documented, but the missing leading `\b` makes the second one
avoidable). `mysqldump`, `bench backup-all-sites` and `git commit --dry-run` are denied
inside a delegated run by accident (`BUG-009`).

### Do configuration failures fail open or closed?

| State | `hooks/guard.py` | `scripts/delegate` |
| :-- | :-- | :-- |
| File absent / unparsable / no `rules` key | **closed** — asks on 6 guarded programs | **closed** — exit 2, refuses |
| `rules: []`, `rules: {}`, all `hook: null`, non-dict rules | **OPEN — allows everything, silently** | **OPEN — 0 deny rules, proceeds** |
| A rule whose `match.kind` is unimplemented | **OPEN for that rule, silently** | **OPEN for that rule, silently** |
| A rule missing `match`, or `rules: 42` | **crash → exit 1 → OPEN** | **crash → exit 1**, no result |
| `identifiers: []` | closed, pathologically (asks on everything) | unaffected |
| Wrong-typed routing values | n/a | mixed: exit 2, exit 1, or accepted-then-crash |

The design *intends* the first row's behaviour everywhere, and says so in both files'
comments. It achieves it only for the case where the file cannot be read at all.

### What is genuinely strong

Worth stating, because the list above is long and the picture would be unfair without it:

- **The Codex sandbox** is the strongest containment in the system, and Phase 04 measured
  *why* rather than assuming: `EPERM` across AF_UNIX, loopback TCP and public TCP, traced
  to `--apply-seccomp-then-exec` rather than the network namespace, with a
  no-seccomp reproduction proving the namespace alone leaves a MariaDB unix socket open.
  That is real security work.
- **`OPENCODE_CONFIG_CONTENT` precedence**, including writing the policy at both the top
  level and `agent.build`, verified live against a hostile project config that allowed
  everything at both levels, with ground truth read from the bare remote's ref rather than
  the agent's account.
- **`--cwd` validation** — required, realpathed, must be a work-tree root, subdirectories
  refused rather than resolved upward, with the error naming the root.
- **The `onboard` mode and `strip_off_contract`** — recognising that a mode is a contract
  and that a fabricated verdict is worse than no verdict is a subtle, correct insight.

---

## 7. Frappe / Bench Safety Review

**Is this plugin safe around Frappe development and live sites?**
**Mostly, for Claude's own commands, with a human present. Not yet, for delegated runs.**

### What it gets right

- **The unnamed-site insight is the single best piece of work in the repository.**
  Recognising that `bench migrate` is not a site-free command — that frappe resolves one
  from `default_site` and then `currentsite.txt` — and then deriving the subcommand set
  from *every* command in `frappe/commands/*.py` that resolves a site rather than filtering
  by which look dangerous, is exactly the right method. The stated reason is the right
  reason too: *"`bench list-apps` is harmless and `bench trim-tables` is not, and they pick
  their site by the identical mechanism. A set filtered by apparent danger would have kept
  the hole open for whichever command the filter underrated."*
- **All 76 subcommands are checked through both engines by the suite**, not sampled
  (`tests/test_parser.py:477-492`).
- **The "default is nothing" stance** in `skills/frappe-operations/SKILL.md:14-24` is
  correct and unusual — most such tooling runs build+migrate+clear-cache+restart by reflex.
- **The four-field plan line** (`build no | migrate no | clear-cache no | restart no |
  site: n/a`) makes a `no` a decision on the record rather than an omission. Good design.
- **`bench build --app <app>`** rather than a bare `bench build`, scoped to the changed app.
- **Operations are never delegated**, with a measured reason
  (`skills/frappe-operations/SKILL.md:160-172`) rather than a hand-wave: the hook cannot see
  a delegated shell, and neither agent's containment was built to decide *which site* an
  operation should touch. That reasoning is correct and it is load-bearing.
- **Site resolution refuses to guess**, including in development, including when the answer
  seems obvious, with `OPERATIONS.md` as the declared home for the answer and a template
  hint that asks for it by name.
- **`install-app` is never inferred**; `--site all` and site loops are forbidden.

### Where it is not safe yet

1. **A delegated OpenCode run can reach a live site** via a path-qualified bench command
   (`SEC-001`). This is the serious one. `/home/frappe/frappe-bench/env/bin/bench --site
   prod migrate` matches no deny pattern, `--auto` approves it, the hook cannot see it, and
   nobody is watching. And the absolute form is *normal* on a Frappe machine — it is what
   `OPERATIONS.md` is asked to record.
2. **`bench drop-site` deletes a site's database and is unguarded** in both layers
   (`SEC-008`). So is `bench update`, which migrates every site in the bench —
   `bench --site x migrate` asks, `bench update` does not.
3. **PostgreSQL and Redis routes are unguarded** (`SEC-007`), although the rule data itself
   lists `bench postgres` among the site-resolving subcommands.
4. **The live-site rules are all `ask`**, so in a non-interactive session they may not gate
   anything (`SEC-009`). This is the family where that matters most.
5. **The bench-directory-versus-repository-root distinction is prose only.**
   `skills/frappe-operations/SKILL.md:42-56` explains it well — bench runs from the bench
   directory, `--cwd` is the repository root, *"These are two different directories and they
   are not interchangeable"* — and the dispatcher enforces the `--cwd` half. Nothing
   enforces that a bench command is run from the bench directory, and nothing prevents
   `--cwd` from being pointed at the bench root itself (which is a git repository in a
   normal bench, so the work-tree check passes). A delegated run scoped to the whole bench
   would then have every app and `sites/` in scope. Worth a note in the skill at minimum.
6. **A stale or hostile `OPERATIONS.md` is trusted by design.** The override rule
   (*"outranks everything above"*) is correct for build and test commands, and it is also
   an instruction channel from repository contents into command execution. The mitigation
   that exists is the hook's ask on site commands — which brings us back to points 1 and 4.

### The three destructive-migration questions the skill answers well

`skills/frappe-operations/SKILL.md:174-192` requires stopping before a migration that may
drop or rename fields carrying data, remove a DocType, or transform rows irreversibly;
requires explicit intent for multi-site work and data deletion; and *refuses* rather than
confirms remote/demo/production operations. That is the right shape, and the distinction
between "confirm" and "refuse" is drawn in the right place. It is all prose, and the
enforcement underneath it is the `ask` on site-touching commands, which is weaker than the
prose implies. That is the honest summary of Frappe safety here: **the judgement is good and
the enforcement is one layer thinner than the documentation suggests.**

---

## 8. Tests and Missing Coverage

### What was run

| | |
| :-- | :-- |
| Command | `python3 tests/test_parser.py` |
| Result | **passed**, exit 0, 10.25 s (dominated by the deliberate 5-second hostile-input budget) |
| Reported | `38 cases, 3 timed, 8 strip, 9 boundary rules, mode matrix, invocation, agent path, adapters and --cwd checked` |
| Known gaps printed | 2, both documented, neither counted as a failure |
| Tests failed | 0 |
| Tests skipped for safety | 0 — the suite invokes no external agent, touches no site, and confines itself to `tempfile` directories and stub CLIs. It was safe to run in full. |

### What the tests actually prove

Honestly assessed, and the distinction matters:

- **They prove the two engines agree about the commands written in the rule data.** All 76
  bench subcommands go through both engines. That is real and it is the check that would
  have caught the four-versus-seventy-six divergence.
- **They prove the parser is bounded and does not raise** on hostile input, with real
  captured fixtures rather than invented ones — including the inner-fence output that broke
  the previous parser. The fixture discipline is excellent and should be copied.
- **They prove the mode tables cannot drift apart**, that Codex's sandbox is read-only for
  every mode but `test`, that both adapters state the working directory, that `--cwd` is
  validated, and that the three hand-written copies of the dispatcher's invocation still
  describe the dispatcher.
- **They do not prove that either engine catches the command a rule is about.** Every
  boundary assertion runs against the rule's own `examples` array. Nine rules contribute
  about 25 example commands, all written in the canonical spelling. Every bypass in
  `SEC-001`, `SEC-002` and `SEC-003` passes the suite.
- **They do not prove anything about the delegated policy in OpenCode.** The suite matches
  with Python's `fnmatch`; OpenCode's matcher is a different program and has never been
  compared against it. `fnmatch` is a reasonable stand-in, but the suite should say so, and
  the assumption should be checked once.
- **They do not touch `hooks/guard.py`'s entry point at all** (`TEST-001`).

### The most valuable tests to add, in priority order

1. **Hook payload contract** (`TEST-001`) — a table through `main()` with stdin
   redirected. Must include: the five crashing payload shapes from `SEC-005`; the JSON
   output shape (`hookSpecificOutput.{hookEventName,permissionDecision,permissionDecisionReason}`);
   deny-outranks-ask on `bench migrate; git add .`; and the pass-through cases.
   *Catches `SEC-005` and locks the output contract.*
2. **Equivalent-forms corpus, both engines** — for each rule, a list of alternate spellings
   that must be caught (wrapped, path-qualified, chained, option-aggregated) and a list that
   must not be. *Catches `SEC-001`, `SEC-002`, `SEC-003`, `BUG-009`.* This is the single
   highest-value addition: it converts "the engines agree about our examples" into "the
   engines catch the command".
3. **Config-mutation table** (`SEC-004`, `BUG-004`) — the fifteen mutations in this report,
   asserting the hook degrades to `ask` and the dispatcher refuses with exit 2 in every
   unusable case. *Catches the whole fail-open class.*
4. **Nested-report shadowing** (`BUG-001`) — the four shapes, asserting the outer report
   wins and its `findings` survive.
5. **`execute()` under duress** (`BUG-002`, `BUG-003`) — a stub that leaks a grandchild
   (assert bounded wall clock and no survivors), and a stub emitting invalid UTF-8 (assert a
   result is still produced).
6. **`opencode_permissions` structure** (`TEST-002`) — denies at both `permission.bash` and
   `agent.build.permission.bash`, base `"*": "ask"`, zero `allow`. *Locks Phase 03's
   Finding B, which currently has no test at all.*
7. **Config/parser consistency** (`CFG-001`) — `--tier` choices equal the routing file's
   tiers; every `escalation_ladder` stage and every tier `model` resolves in `models`.
8. **False-positive guards** (`BUG-006`) — the commit-message case as a counter-example,
   with the heredoc case kept as a positive so a fix cannot trade one for the other.
9. **Timeout validation** (`BUG-005`) — `--timeout 0` and `--timeout -5` refused.

Items 1–3 would have caught four of this audit's eight P1 findings.

### A note on the contract's testing rule

`docs/BUILD_CONTRACT.md:219-223` says tests are for components that fail silently, and
gives *"a hook that denies the wrong command"* as an example of something that announces
itself. That premise is the root of the coverage gap: a hook that **allows** the wrong
command announces nothing at all, and that is the failure mode of `SEC-002` through
`SEC-005`. The rule is right in spirit and its example is backwards. Worth amending — the
hook is not the loud component; it is the quietest one in the repository.

---

## 9. Architecture Improvements

Only the changes that materially improve correctness, security, testability or clarity.
Deliberately excluded: anything that is only tidier.

### 9.1 Normalize commands once, in one place (`IMP-002`)

The strongest argument for this is historical. The repository already paid for a divergence
between two hand-maintained rule sets, diagnosed it correctly, and fixed it by
single-sourcing the *rules*. What it did not single-source is the *notion of what a command
is* — and that is where four of this audit's findings live. The fix pattern is identical to
the one already applied one level up.

Cost: one new file, importable by both consumers, against a contract principle of "fewer
files is better". Benefit: a bypass is fixed once and both engines improve; the suite tests
one normalizer against a broad corpus instead of two translations against nine examples.

### 9.2 Make "unusable config" a first-class state (`IMP-003`)

Both consumers already reason explicitly about *unreadable* config and reach the right,
deliberately-different answers (hook degrades, dispatcher refuses). Neither reasons about
*unusable* config, and both land on the permissive side. This is a small, high-value change
because it turns three of this audit's findings into one validated invariant.

### 9.3 Replace report identification with a delimiter (`IMP-001`)

The project's own conclusion after three review rounds. `BUG-001` is the fourth
counterexample and the first that fails unsafe. This retires a whole class rather than
narrowing a heuristic again.

### 9.4 Make `execute()` honour its own contract (`BUG-002`, `BUG-003`)

`execute` is documented to return `(status, exit_code, stdout, stderr, seconds)`. Today it
can instead hang forever or raise. Process-group kill, a bounded recovery read, and
`errors="replace"` make the contract unconditional. Small change, removes two P1s.

### 9.5 What should *not* change

- **Two engines, two translations.** The design is right; only the shared normalization is
  missing. Do not collapse the hook and the dispatcher into one matcher — they run in
  different processes with different information, which the file comments explain correctly.
- **Adapters as two functions rather than a plugin framework.** Correct call, and the
  contract's reasoning holds.
- **The deliberate skill-prose duplication** (rows 9, 10, 11 of the Phase 04 duplication
  map). It exists because skill activation is stochastic. Collapsing it removes the property
  it was built for. The map's own recommendation — *"row 5 is worth a check, the rest are not
  worth touching"* — is the right judgement and was correctly acted on.
- **No helper script for Frappe operations.** Phase 04's reasoning is right: every decision
  there is judgement over a diff and a prose document, and a script encoding it would be a
  second rule engine.
- **Exit-code semantics** (0 with a result, 2 for a bad invocation). Good design; it just
  needs to be true in the four cases where it currently is not (`BUG-004`, `BUG-003`).

---

## 10. Documentation Improvements

### Inaccurate

| Where | Says | Reality |
| :-- | :-- | :-- |
| `docs/BUILD_CONTRACT.md:38` | `.claude-plugin/` contains **only** `plugin.json` | `marketplace.json` is also there (`DOC-004`) |
| `docs/BUILD_CONTRACT.md:219-223` | a hook that denies the wrong command announces itself, so does not need tests | a hook that *allows* the wrong command announces nothing; that is the actual failure mode (`TEST-001`) |
| `docs/phases/PHASE_02*.md:337`, `PHASE_03*.md` "Codex Modes" | onboarding uses REVIEW mode | it uses `onboard`; and the contract says the spec wins (`DOC-002`) |
| `docs/reports/PHASE_01_REPORT.md:5` | `plugin.json` carries a `version` | it does not, deliberately (`DOC-006`) |
| `docs/reports/PHASE_01_REPORT.md:49` | routing file uses `GLM-5.2` | it uses `GLM-5.3` (`DOC-006`) |
| `docs/reports/PHASE_01_5_REPORT.md` verification | *"Malformed payloads … Exit 0, no stdout, no stderr"* | five non-dict payload shapes exit 1 with a traceback (`SEC-005`) |
| `docs/reports/PHASE_01_5_REPORT.md` open question 2 | false positives are *"Harmless direction — an ask … never a deny"* | a commit message can trigger a **deny** (`BUG-006`) |
| 3 × phase reports | `ls -A .claude-plugin` → `plugin.json` only | no longer true (`DOC-004`) |
| all 5 phase reports | `claude plugin validate . --strict` → ✔ passed (exit 0) | now prints ✘ Validation failed; and exits 0 either way (`DOC-001`) |
| `hooks/hooks.json:2`, `hooks/guard.py:2-3` | three boundaries | five rule families (`DOC-003`) |

### Incomplete

- **`README.md`** does not say which rules `ask` versus `deny`, nor that an `ask` needs a
  human — so it does not tell a user that `claude -p` sessions are effectively unguarded for
  the live-site family (`SEC-009`).
- **`README.md`** does not state that the plugin's protections can be silently absent for
  reasons other than being uninstalled: a rule file that yields nothing (`SEC-004`), a
  crashing hook (`SEC-005`), a moved directory (mentioned), or a PATH reordering (mentioned,
  well).
- **`skills/orchestration/SKILL.md:302-318`** ("Reading the result") lists `status`,
  `result_block`, `cwd`, `off_contract_keys` and `agent_report`, but not `agent_path` /
  `agent_real_path` — the two fields the Phase 03/04 reports argue hardest for, added
  precisely so a run measured against the wrong binary is visible. If the orchestrator is
  not told to look at them, they are a record nobody reads. Add a bullet.
- The same section points only at `transcript` (stdout) when a report is missing; for Codex
  the cause is on stderr, which the result never names (`DOC-007`).
- **`README.md:19-27`** lists prerequisites but not the minimum Python version.
  `scripts/delegate` and `hooks/guard.py` use f-string-free `%` formatting and standard
  library only, so the real floor is low (3.6+), but `frozenset`/`pathlib` usage and the
  `text=True` subprocess idiom mean 3.7+ is the honest statement. One line.
- **No `CONTRIBUTING`-style note on how to add a boundary rule.**
  `config/command-boundaries.json:4` carries it (*"Add or edit a rule here, not in a
  consumer"*), which is the right place, but it does not mention that a new `match.kind`
  requires code in **both** consumers and that a missing implementation fails silently at
  runtime (`BUG-004`).

### Misleading

- **`README.md:16-17`**: *"The hook and the dispatcher's permission policy are the two
  enforcement layers, and they read their rules from `config/command-boundaries.json`
  rather than keeping copies."* True and well put — but read alongside the boundary list in
  `README.md:125-126` it invites the conclusion that those boundaries hold. Given
  `SEC-001`–`SEC-003`, a short "Known limits" section would be more honest than silence:
  the boundaries match commands by program name and subcommand, so a wrapped, path-
  qualified or otherwise re-spelled command may not be caught.
- **`README.md:73-99`** ("Updating after a commit") is otherwise excellent — the
  *"a broken working tree is broken enforcement in every session"* sentence is exactly the
  right warning to give — and it is undercut by the `--strict` command it recommends now
  failing.

### What the documentation does unusually well

Worth naming, since the table above is long:

- The **PATH-order section** (`README.md:29-46`) explains a subtle safety property in eight
  sentences with the measured consequence attached (*"A delegated run has executed
  `bench migrate` unrefused that way"*). Most projects would have written "make sure the
  right binary is first".
- The **phase reports' correction convention** — leaving the original text in place with a
  pointer to the correction — is a genuinely good practice and is applied consistently in
  the Phase 03 and Phase 04 reports.
- **"The layer under test cannot also be the layer protecting the test"**
  (`docs/reports/PHASE_03_REPORT.md`) is a rule worth extracting into general engineering
  practice, and it was learned the hard way and written down properly.
- **"A conclusion that turns out right does not make its reason verified"** — the sandbox
  correction in the Phase 04 report — is the same.

---

## 11. Recommended Action Plan

### Fix Immediately (P0 / P1)

1. **`SEC-001`** — widen the delegated deny patterns to cover path-qualified, wrapped and
   chained forms, and establish what OpenCode actually matches on. This is the only
   containment layer for a delegated OpenCode run.
2. **`BUG-001`** — prefer the outermost qualifying object in `extract_report`. Two lines,
   and it closes a silent FAIL→PASS conversion.
3. **`SEC-004`** + **`SEC-005`** — make `load_rules` return `None` for any unusable rule
   set, and wrap `main()` so the hook can never exit non-zero. These two are ~10 lines
   together and remove the "enforcement silently absent" class.
4. **`SEC-003`** — add `-u`, `--update`, `:/`, `./`, `*` to `blanket-staging.any_argument`
   and match short-option clusters. Verified-equivalent bypasses of the system's only
   `deny`-class Git rule.
5. **`BUG-002`** + **`BUG-003`** — process-group kill, bounded recovery read,
   `errors="replace"`. Makes `execute()` honour its contract unconditionally.
6. **`SEC-002`** — normalization pass for wrappers and environment prefixes in the hook.
   Larger than the others; do it after 1–5 and preferably as the first slice of `IMP-002`.
7. **`SEC-006`** — add the destructive-worktree and destructive-filesystem rules, narrowed
   with `any_argument` so they do not become noise.

### Fix Next (important P2)

8. **`BUG-004`** — route every config type error through `fail` (exit 2), and make a rule
   whose `kind` is unimplemented a hard refusal in the dispatcher rather than a silent
   omission.
9. **`SEC-007`** + **`SEC-008`** — `psql`/`redis-cli`/`sqlite3` in `database-client`; new
   rules for the positional-site and bench-wide families. Closes `bench drop-site`.
10. **`TEST-001`** — the hook payload table. Cheapest high-value test in the list.
11. **`BUG-006`** — token-aware segment splitting, keeping the heredoc catch.
12. **`DOC-001`** — decide the `version`/`--strict` question and fix the documented
    verification command. It is the repository's own definition of "verified".
13. **`CFG-001`** — derive `--tier` from the routing file; give the two nameless ladder
    rungs tiers.
14. **`ARCH-001`** / **`PATH-001`** — verify `${CLAUDE_PLUGIN_ROOT}` in the Bash
    environment, and give the plugin a way to say it is active. These two answer each
    other.

### Harden

15. **`IMP-003`** — schema + validation for both config files.
16. **`IMP-002`** — the shared normalization module, absorbing the tactical fixes from
    steps 1, 4 and 6.
17. **`IMP-001`** — delimiter-based report extraction; retires both `KNOWN_GAPS`.
18. **`IMP-004`** — child-environment sanitization.
19. **`SEC-009`** — document what an `ask` means in non-interactive sessions; reconsider
    `deny` for the live-site family there.
20. **`BUG-009`** + **`BUG-010`** — decide the over-matches deliberately; narrow the
    informational-flag exemption.

### Improve Later

21. **`IMP-005`** — split the rarely-needed sections out of the orchestration skill behind
    path references.
22. **`BUG-007`**, **`BUG-008`**, **`DOC-002`** … **`DOC-008`**, **`TEST-002`** —
    workspace pruning, discriminator normalization, and the documentation/coverage cleanups.
23. **`DOC-005`** — reconcile the contract's Git rules with the commit that broke them,
    either by amending the contract for non-phase work or by bringing that work under a
    report.

---

## 12. Suggested Implementation Order

Dependency-aware, in slices that each end green.

```
Slice 1 — stop the silent failures (smallest, highest value)
  SEC-004 (load_rules returns None when unusable)
   -> SEC-005 (main() cannot exit non-zero)
   -> TEST-001 (hook payload + config-mutation tables)   <- proves both, locks the output contract
   -> regression run: python3 tests/test_parser.py

Slice 2 — close the verified command bypasses
  SEC-003 (staging equivalents: data + short-option clusters)
   -> equivalent-forms corpus in check_command_boundaries()  <- the test comes with the fix
   -> SEC-001 (widen delegated patterns for path-qualified / chained / wrapped)
   -> one-off: establish OpenCode's matching semantics (opencode debug config + isolated probe,
      following the repo's own four isolation rules)
   -> BUG-009 / BUG-010 fall out of the same corpus
   -> regression run

Slice 3 — the parser
  BUG-001 (outermost qualifying object wins) + its four-shape test
   -> BUG-003 (errors="replace", widen execute's except)
   -> BUG-002 (process-group kill, bounded recovery read) + leaked-grandchild test
   -> regression run

Slice 4 — the rules that are missing rather than broken
  SEC-006 (destructive worktree + filesystem, narrowed)
   -> SEC-007 (psql / redis-cli / sqlite3)
   -> SEC-008 (positional-site + bench-wide families)
   -> each with examples AND not_examples in the data, so the existing drift test covers them
   -> regression run

Slice 5 — configuration integrity
  IMP-003 (schema + validator in both consumers)
   -> BUG-004 (every type error -> exit 2; unimplemented kind -> refusal)
   -> BUG-005 (timeout validation)
   -> CFG-001 (derive --tier from routing; name the two ladder rungs)
   -> regression run

Slice 6 — the structural change, now that the corpus exists to prove it
  IMP-002 (shared normalization module)
   -> re-point guard.py and rule_patterns at it
   -> the Slice 2 corpus is the acceptance test; SEC-002 is closed properly here
   -> BUG-006 (token-aware splitting) lands naturally inside it
   -> regression run

Slice 7 — the brief/parser contract change
  IMP-001 (per-run delimiter token)
   -> retire both KNOWN_GAPS
   -> keep the brace scanner as an instrumented fallback
   -> requires one live agent run to confirm both CLIs honour the delimiter

Slice 8 — visibility and documentation
  PATH-001 (verify ${CLAUDE_PLUGIN_ROOT} in the Bash environment)   <- blocks ARCH-001 option 1
   -> ARCH-001 / IMP-006 (SessionStart heartbeat, or a preamble guard field)
   -> DOC-001 (version / --strict decision)
   -> DOC-002 .. DOC-008, plus a README "Known limits" section
   -> IMP-004, IMP-005, BUG-007, BUG-008
   -> contract amendments: the testing rule's example, .claude-plugin's contents,
      spec-vs-report precedence (DOC-002), non-phase commits (DOC-005)
```

Two notes on sequencing:

- **Slice 2's corpus must land with Slice 2, not after it.** Every bypass fix without a
  corpus entry is a fix that the next refactor can silently undo, and `IMP-002` in Slice 6
  is exactly that refactor.
- **Slices 1–5 need no live agent run at all** — they are testable entirely with stubs and
  temp directories, which is what makes them cheap. Only Slices 2 (the OpenCode semantics
  probe) and 7 need a real CLI. Given that this repository's history is a series of
  discoveries that stubs were tidier than reality, budget for those two properly.

---

## 13. Positive Findings

Supported by the code, not offered as balance.

1. **Single-sourced boundary rules with two translations, and a drift test that fails by
   rule name.** `config/command-boundaries.json` is a genuinely good design: the data
   describes the rule, each engine translates it, and neither owns it. The
   `not_enforced_because` field — *required* whenever a decision is `null` — is a small,
   sharp idea, and the report records that it was added only after a regression probe showed
   a `null` decision passing silently. That is testing the test.

2. **Deriving the bench subcommand set from frappe's own CLI rather than filtering by
   apparent danger.** 76 subcommands, every one checked through both engines by the suite.
   The stated reasoning — that `bench list-apps` and `bench trim-tables` resolve their site
   by the identical mechanism, so a danger filter keeps the hole open for whichever command
   it underrates — is the correct way to think about this class of rule.

3. **Read-only as the default sandbox, expressed so that omission is safe.**
   `sandbox = "workspace-write" if mode == "test" else "read-only"` rather than
   `"read-only" if mode == "review" else ...`. The report explains that the earlier form
   would have given a new mode write access by omission, and the suite asserts the resulting
   sandbox for every mode in `MODES["codex"]`. This is fail-safe-by-construction, and the
   test pins it.

4. **`--cwd` required, validated, and subdirectories refused rather than resolved upward.**
   The reasoning is the best in the dispatcher: resolving upward would silently widen scope,
   which is the same shape of quiet substitution that let the inherited-directory defect
   live. `.git` tested as a path so that linked work trees work and bare repositories are
   correctly refused. Nine assertions in `check_cwd_validation`, including the probe that
   *pins the stated decision* so it cannot be quietly reversed later.

5. **`agent_path` / `agent_real_path` in every result and dry run.** Born from a real,
   expensive discovery — an entire phase's OpenCode findings turned out to be about a
   different program of the same name — and the mitigation chosen (make it visible in the
   record) is the right one, since PATH order is not the plugin's to control. The detail
   that nvm's `opencode` is a symlink to a file called `opencode.exe` that is an ELF binary,
   so only the directory distinguishes the builds, is exactly the kind of thing that is
   worth writing down.

6. **The `onboard` mode, and `strip_off_contract`.** Recognising that a mode *is* a
   contract, that one mode serving two output shapes manufactures artefacts, and that a
   fabricated PASS/FAIL is indistinguishable from a real one at the point of consumption —
   that is a subtle insight, correctly diagnosed and correctly fixed. Removing a volunteered
   verdict while recording the removal in `off_contract_keys` is the right resolution of
   "an agent writes what it writes".

7. **Fences are not parsed.** After a real captured output broke a regex parser, the fix
   deleted the whole category rather than patching the instance — and the fixture that broke
   it is kept, with a note explaining that an invented sample would not have contained it.
   The three-way bound on the scan (candidates, cumulative seconds, per-candidate slice)
   with the reasoning for why a candidate cap alone is insufficient is careful work.

8. **`OPENCODE_CONFIG_CONTENT` at both the top level and `agent.build`, with `--agent build`
   pinned.** Finding B — that agent-level permissions resolve separately and would have left
   a hostile config's rules untouched — is the sort of thing that is only found by looking,
   and it was verified live twice, against a config allowing everything at both levels, with
   ground truth read from the bare remote's ref rather than the agent's account.

9. **Measuring the errno instead of accepting the verdict.** The Phase 04 sandbox probe —
   `EPERM` across three address families, traced to seccomp rather than the network
   namespace, with a no-seccomp reproduction showing that the namespace alone leaves a
   MariaDB unix socket wide open — corrected a claim that had survived a review, a live run
   and three readings *because the outcome kept agreeing with it*. The rule extracted from
   it is worth keeping.

10. **The reporting discipline itself.** Superseded text left in place with pointers to
    corrections; declined review findings recorded with the reason rather than dropped;
    `KNOWN_GAPS` that run, print, and fail if a documented defect changes behaviour; the
    explicit refusal to call anything verified until it ran against a real CLI. And
    `docs/reports/PHASE_03_REPORT.md` records a near-miss against itself — that the
    isolation the deny probes relied on did not exist, so the layer under test was also the
    layer protecting the test — which most projects would simply not have written down.

11. **The dispatcher makes no decisions.** It resolves values by key, enforces the
    agent/mode matrix, and refuses combinations it does not support. No task planning, no
    model selection, no review reasoning. The separation the phase document asked for is
    actually held, and `check_dispatcher_invocation()` verifies that the three hand-written
    copies of its invocation still describe it — including running each documented
    invocation through `validate_invocation`, the same function a real run uses.

---

## 14. Final Verdict

> ### Requires fixes before wider use.

**Why.** As a *guidance* system this is already strong: the skills are well-reasoned, the
Frappe operation rules are better than most human runbooks, the workflow is bounded, and
the reporting discipline is exceptional. If the plugin were described as "structured
guidance with a best-effort backstop", the verdict would be *safe with minor improvements*.

It is not described that way. `README.md:16` calls the hook and the dispatcher's permission
policy "the two enforcement layers", and `README.md:125-126` names the boundaries they hold.
That claim does not currently survive contact with ordinary alternate spellings of the same
commands:

- A delegated OpenCode run — the one context with **no human in the loop and no hook** — can
  reach a live site through a path-qualified bench command, which is the normal way bench is
  invoked on a Frappe machine (`SEC-001`).
- The system's only Git `deny` is bypassed by `git add ./`, `git add *` and `git add -u`,
  all verified equivalent to `git add -A` (`SEC-003`).
- Every rule, `deny` included, is bypassed by `sudo`, `bash -c`, or an environment prefix
  (`SEC-002`).
- Enforcement can be **silently, completely absent** in three distinct ways that leave the
  plugin looking installed and working (`SEC-004`, `SEC-005`, `ARCH-001`).
- A reviewer's FAIL can reach the orchestrator as a PASS with its findings discarded
  (`BUG-001`).
- Neither layer guards anything that destroys the user's uncommitted work, and inside a
  delegated run the base policy auto-approves it (`SEC-006`).

None of these requires an adversary. Several are things an ordinary, well-behaved agent
types by habit.

**The good news is the shape of the work.** These are not architectural failures — the
architecture is right, and it is right for reasons the repository argued out properly. They
are gaps in one layer: the step that decides what a command *is*, before the well-designed
rules get a chance to apply. Slices 1–4 of the suggested order are perhaps 150 lines of
change plus tests, need no live agent run, and close the P0 and six of the eight P1s. After
that, and after the README gains an honest "Known limits" section, the verdict would move to
*safe with minor improvements*.

**One thing to keep in view while fixing it.** This repository's central asset is that its
own documentation can be trusted — the corrections, the declined findings, the "not
verified" notes. Two documented verifications turned out not to hold (`SEC-005`'s malformed
payloads, `BUG-006`'s "never a deny"), and the standard verification command now fails
(`DOC-001`). Those are small, but they are the first cracks in the thing that makes
everything else here credible, and they are worth fixing with the same care as the security
findings.

---

*Audit performed by static analysis and non-destructive local execution. No project file was
modified. `git status --porcelain` before the audit: empty. After: `?? REVIEW_REPORT.md`.*
