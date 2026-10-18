# OpenCode Permission-Matching Semantics — Measured

Diagnostic slice (6A). No project source file was modified. No destructive command was
executed. Every runtime probe ran against harmless Python stub executables in a
disposable temporary directory.

---

## 1. Installed Version

| | |
| :-- | :-- |
| `which opencode` | `/home/mustafa/.opencode/bin/opencode` (also first on PATH twice) |
| `readlink -f` | `/home/mustafa/.opencode/bin/opencode` (not a symlink) |
| `opencode --version` | `1.18.18` |
| File type | `ELF 64-bit LSB executable, x86-64, dynamically linked, not stripped`, 176 MB |
| Build | Bun single-file executable; JS modules embedded as `/$bunfs/root/chunk-*.js`, grammars as embedded `.wasm` |
| Version string in-binary | `chunk-fwsvemxz.js`: `var n="1.18.18",t="latest",l=!1` |
| Install provenance | `~/.opencode/package.json` declares only `@opencode-ai/plugin@1.18.18`; `package-lock.json` resolves `@opencode-ai/plugin` and `@opencode-ai/sdk` at `1.18.18` from registry.npmjs.org. The server itself is the prebuilt binary, not an npm-installed JS tree. |

This is a Linux ELF build. The Windows shim that earlier phase reports warned about is not
on PATH in this environment. No upgrade or reinstall was performed.

---

## 2. Matcher Implementation

All identifiers below are the minified names in the installed binary. Byte offsets are
into `/home/mustafa/.opencode/bin/opencode` as installed.

### 2.1 The wildcard matcher — `Wildcard.match`

Namespace `iY`, exported as `Wildcard`/`match`, re-exported as `ny` from
`chunk-kz8qcgw9.js` and imported into the permission module as `g`. Offset **103238184**:

```js
function JH(_,Y){
  let $=_.replaceAll("\\","/"),
      A=Y.replaceAll("\\","/")
         .replace(/[.+^${}()|[\]\\]/g,"\\$&")
         .replace(/\*/g,".*")
         .replace(/\?/g,".");
  if(A.endsWith(" .*")) A=A.slice(0,-3)+"( .*)?";
  return new RegExp("^"+A+"$","s").test($)
}
```

A second, unrelated `Wildcard` exists (`So.match = ql`, offset 96290700) used for
tool/structured matching. The permission path uses `iY`.

### 2.2 The rule evaluator — `Permission.evaluate`

Module `@opencode/Permission` (`chunk-h4ytzs3d.js`), namespace `k`, exported as
`evaluate`. Offset **98817494**:

```js
function c(j,J,...K){
  return K.flat().findLast((z)=>g.match(j,z.permission)&&g.match(J,z.pattern))
      ?? {action:"ask",permission:j,pattern:"*"}
}
```

### 2.3 Config → ruleset — `Permission.fromConfig`

Offset **98820200** (with `LA` at 98819983 expanding `~` / `$HOME` prefixes in patterns):

```js
function RA(j){let J=[];for(let[K,z]of Object.entries(j)){
  if(typeof z==="string"){J.push({permission:K,action:z,pattern:"*"});continue}
  J.push(...Object.entries(z).map(([B,X])=>({permission:K,pattern:LA(B),action:X})))}
  return J}
```

### 2.4 `Permission.ask` — the decision loop

Offset ~98817993 (`"Permission.ask"`):

```js
for(let Y of Z.patterns){
  let W=c(Z.permission,Y,$,M);                       // $ = config ruleset, M = session approvals
  yield* A.logInfo("evaluated",{permission:Z.permission,pattern:Y,action:W});
  if(W.action==="deny") return yield* new U.DeniedError({...});
  if(W.action==="allow") continue;
  _=!0                                               // otherwise this call must be asked
}
if(!_) return;                                       // every pattern allowed → run silently
```

### 2.5 What resource is matched — `ShellTool.collect`

This is the decisive function. `packages/opencode/src/tool/…` shell tool, offset
**96545130**:

```js
$=s.fn("ShellTool.collect")(function*(c,h,b,T,d){
  let w={dirs:new Set,patterns:new Set,always:new Set},O=lo.toKind(xo.name(T));
  for(let U of vi(c)){                               // vi = every `command` node in the parse tree
    let q=Mi(U),R=q.map((J)=>J.text),N=...R[0];
    if(N&&(Bi.has(N)||...)) for(...) { ... w.dirs.add(D) }        // external_directory only
    if(R.length&&(!N||!_e.has(N)))
      w.patterns.add(Pi(U)),                                     // <-- the matched value
      w.always.add(Lo.prefix(R).join(" ")+" *")                  // <-- the "allow always" suggestion
  }
  return w})
```

with, at offsets 96541162 / 96541253 / 96540038:

```js
function Pi(o){return(o.parent?.type==="redirected_statement"?o.parent.text:o.text).trim()}
function vi(o){return o.descendantsOfType("command").filter((e)=>Boolean(e))}
var _e=new Set(["cd","chdir","popd","pushd","push-location","set-location"]),
    Bi=new Set([..._e,"rm","cp","mv","mkdir","touch","chmod","chown","cat", ...]);
```

**The matched resource is the raw source text of each `command` node in the shell parse
tree**, trimmed — or the enclosing `redirected_statement`'s text when the command is
redirected. Parsing is `ShellTool.parse` (offset ~96544000) via tree-sitter:

```js
var ts=s.fn("ShellTool.parse")(function*(o,e){
  let r=yield*s.promise(()=>ns().then((t)=>(e?t.ps:t.bash).parse(o))); ... })
```

`ns()` loads `tree-sitter-bash-hq5s6fxb.wasm` and `tree-sitter-powershell-*.wasm` from the
binary. I extracted both grammars (tree-sitter runtime 205 488 bytes at offset 127655294;
tree-sitter-bash 1 380 818 bytes at offset 127860827) and confirmed they are valid WASM
modules; the loader glue is bun-internal, so grammar behaviour was measured at runtime
instead (§4).

`Lo.prefix` (`BashArity`, offset ~96538700) is an arity table (`git:2`, `"git stash":3`,
`mysql:2`, `rm:1`, `npm:2`, …). It is used **only** to build the `always` suggestion, never
for matching.

---

## 3. Runtime Semantics

| Behaviour | Verdict | Basis |
| :-- | :-- | :-- |
| Strips executable paths | **confirmed: not performed** | `Pi` returns `node.text` verbatim; measured — `/…/probe/bin/git push` was evaluated as the full absolute string and matched only `*` |
| Parses argv | **confirmed: parses, but does not match on argv** | `Mi(U)` builds a token list, used for the arity/`always` suggestion and for `external_directory` path collection. The value matched is the node's source text, not a normalised argv join |
| Splits command chains | **confirmed: yes** | `descendantsOfType("command")`; measured — `echo safe && git push` produced two separate evaluations (`"echo safe"` → ask, `"git push"` → deny) |
| Skips directory-change commands | **confirmed: yes** | `!_e.has(N)`; measured — `cd /tmp && bench migrate` evaluated only `"bench migrate"` (denied). `cd` never reaches the matcher |
| Unwraps shell wrappers | **confirmed: not performed** | measured — `bash -c 'git push'`, `sudo git push`, `env FOO=1 git push` and `FOO=1 git push` each produced exactly one opaque value matching only `*` |
| Normalises quotes | **confirmed: not performed** | measured — the value for `bash -c 'git push'` retains its single quotes verbatim |
| Normalises whitespace | **confirmed: only `.trim()`** | `Pi` ends in `.trim()`; interior spacing is the source text unchanged |
| Normalises path separators | **confirmed: `\` → `/`** on both pattern and value | `replaceAll("\\","/")` in `JH` — the only canonicalisation anywhere in the path |
| Redirections | **confirmed: included in the value** | measured — `git push > /dev/null` was evaluated as `"git push > /dev/null"` (still denied, because `git push*` has a trailing `*`) |
| Wildcards | **confirmed** | only `*` → `.*` and `?` → `.`; `[`/`]` are escaped, so character classes do **not** work. `s` flag ⇒ `*` crosses spaces *and* newlines |
| Full-value match required | **confirmed: yes** | `new RegExp("^"+A+"$")` — fully anchored |
| Trailing `" *"` is optional | **confirmed** | `if(A.endsWith(" .*")) A=A.slice(0,-3)+"( .*)?"` — pattern `git push *` also matches exactly `git push`. Measured: `git add .` was denied by pattern `git add . *` |
| Case sensitivity | **confirmed: case-sensitive** | no `i` flag; `match("GIT push","git push*")` = `false` |
| Which rule wins | **confirmed: LAST match wins** | `findLast`. Not first, not most-specific — see §6 |
| Default when nothing matches | **confirmed: `ask`** | the `?? {action:"ask"}` fallback |
| `--auto` | **confirmed: replies `once`, never `always`** | `run` handler: `if(Yj) await N.permission.reply({requestID:J.id,reply:"once"})`; without `--auto` it **auto-rejects** and prints `permission requested: … ; auto-rejecting`. `--auto` cannot lift a `deny`: `ask` returns `DeniedError` before any reply is solicited |
| Command substitution `$(…)` | **source-confirmed, not runtime-measured** | `command_substitution` contains `command` nodes and `descendantsOfType` is recursive, so `$(git push)` should be caught. Not in the measured matrix |

### 3.1 Two findings outside the documented model

**(a) `POST /session/{id}/shell` bypasses the permission layer entirely.** I submitted all
28 commands — including `git push`, `bench migrate`, `rm -rf .`, `git reset --hard` — to
that endpoint with the repository's real policy loaded. Every one executed the stub, and
the server logged **zero** `evaluated` and zero `asking` lines. This is a user-initiated
shell channel, not an agent tool path, so it is outside the delegation threat model — but
it is an unguarded execution route on any OpenCode server the policy is loaded into.

**(b) A session "always" approval outranks a config `deny`.** `evaluate` is called as
`c(permission, value, $, M)` — config rules first, session approvals second — and
`findLast` therefore lets an approval win. Driven through the extracted matcher:

```
rm -rf .  with no approvals    -> deny
rm -rf .  with "rm *" allowed  -> allow
```

`"rm *"` is exactly what `BashArity` (`rm:1`) proposes as the `always` value for a benign
`rm foo.txt`. So in an **interactive** session, a human pressing "Allow always" once on a
harmless `rm` disables the `recursive-delete` deny for the rest of the session. The
dispatcher is not exposed to this, because `--auto` replies `once` and accumulates no
approvals — but the same config used interactively is.

**(c) The base of the merged ruleset is `allow`, not `ask`.** A `DeniedError` reported its
ruleset beginning `[{"permission":"*","action":"allow","pattern":"*"},{"permission":"bash","pattern":"*","action":"ask"},…]`.
A built-in `*`/`*`/`allow` rule precedes the config. Because it comes *first* and
`findLast` wins, the dispatcher's `"*": "ask"` does correctly override it for `bash` — but
for any permission id the dispatcher does not name, the effective default is `allow`.

---

## 4. Command Matrix

"Generated policy expectation" is what the repository's own `fnmatch`-based test suite
concludes. "Actual OpenCode result" is measured. Evidence keys:

* **RT** — runtime: measured through the real bash tool via `opencode run --agent build
  --auto` with the repository's real generated policy in `OPENCODE_CONFIG_CONTENT`, log
  line `message=evaluated permission=bash pattern=… action.action=…`, plus the stub
  execution log where the command ran.
* **MX** — the matcher extracted verbatim from the installed binary (§2.1–2.3), driven
  with the policy produced by the repository's own `load_boundaries()` +
  `opencode_permissions()`.

### 4.1 Baseline

| Command | Generated policy expectation | Actual OpenCode result | Evidence |
| :-- | :-- | :-- | :-- |
| `git push` | deny | **deny** via `git push*` | RT |
| `bench migrate` | deny | **deny** via `bench migrate*` | RT |
| `mysql -u root` | deny | **deny** via `mysql*` | RT |
| `git reset --hard` | deny | **deny** via `git reset --hard*` | RT (run 1, model reported refusal), MX |
| `rm -rf .` | deny | **deny** via `rm -rf*` | RT |

### 4.2 Absolute / path-qualified executables

| Command | Generated policy expectation | Actual OpenCode result | Evidence |
| :-- | :-- | :-- | :-- |
| `<tmp>/probe/bin/git push` (stub) | deny (hook strips paths; delegated does not) | **ASK → auto-approved → stub executed** | RT (`git push` in stub log) |
| `/usr/bin/git push` | deny | **ask** — value is the full path, matches only `*` | MX (not run: would invoke real git) |
| `/home/frappe/frappe-bench/env/bin/bench migrate` | deny | **ask** | MX |
| `/usr/bin/mysql -u root` | deny | **ask** | MX |
| `/bin/rm -rf .` | deny | **ask** | MX |

### 4.3 Git global options

| Command | Generated policy expectation | Actual OpenCode result | Evidence |
| :-- | :-- | :-- | :-- |
| `git -C /tmp push` | deny (via `git * push*`) | **deny** via `git * push*` | RT |
| `git -C /tmp reset --hard` | deny | **deny** via `git * reset --hard*` | MX |
| `git --no-pager push` | deny | **deny** via `git * push*` | MX |

Representation: the value is the whole command text, so `git * push*` catches these only
because a literal space-separated token sits between `git` and `push`.

### 4.4 Environment / wrappers

| Command | Generated policy expectation | Actual OpenCode result | Evidence |
| :-- | :-- | :-- | :-- |
| `env FOO=1 git push` | deny | **ASK → executed** (stub git ran) | RT |
| `FOO=1 git push` | deny | **ASK → executed** (stub git ran) | RT |
| `sudo git push` | deny | **ASK → executed** (stub sudo ran; real sudo never invoked) | RT |
| `sudo bench migrate` | deny | **ask** | MX |
| `command git push` | deny | **ask** | MX (shell builtin; not a `command` node's program) |
| `time git push` | deny | **ask** | MX |
| `nohup git push` | deny | **ask** | MX |

### 4.5 Shell wrappers

| Command | Generated policy expectation | Actual OpenCode result | Evidence |
| :-- | :-- | :-- | :-- |
| `bash -c 'git push'` | deny | **ASK → executed** (stub git ran inside real bash) | RT |
| `sh -c 'bench migrate'` | deny | **ask** | MX |

The quoted script is a `raw_string` argument, not a parsed command, so it contributes no
`command` node.

### 4.6 Compound commands — **each parsed command is checked independently**

| Command | Generated policy expectation | Actual OpenCode result | Evidence |
| :-- | :-- | :-- | :-- |
| `echo safe && git push` | deny | **deny** — two values evaluated: `"echo safe"` → ask, `"git push"` → deny | RT |
| `git status && git push` | deny | **deny** (`git push` segment) | RT (run 1, refused) |
| `cd /tmp && bench migrate` | deny | **deny** — only `"bench migrate"` evaluated; `cd` skipped by `_e` | RT |
| `echo safe; git push` | deny | **deny** | RT (run 1, refused) |
| `false \|\| git push` | deny | **deny** | RT (run 1, refused) |
| `git push \| cat` | deny | **deny** — `"git push"` evaluated; loop short-circuits on the deny so `cat` is never evaluated | RT |
| `git push > /dev/null` | deny | **deny** — value is `"git push > /dev/null"` (redirected_statement text) | RT |

**This is the most important result: OpenCode checks each parsed command, not the raw line
once.** Chaining, piping and `cd &&` are *not* bypasses. The repository's `fnmatch`
approximation, which tests the whole line as a single string, therefore *understates*
protection for compound commands and overstates it for wrapped ones.

### 4.7 Existing false-positive candidates — all three confirmed denied

| Command | Generated policy expectation | Actual OpenCode result | Evidence |
| :-- | :-- | :-- | :-- |
| `git stash push -m wip` | denied by `git * push*` (Slice 5 recorded this) | **deny** via `git * push*` | RT |
| `git checkout -b clean-branch` | denied by `git * clean*` (Slice 5 recorded this) | **deny** via `git * clean*` | RT |
| `git config rebase.autoStash true` | denied by `git * rebase*` (Slice 5 recorded this) | **deny** via `git * rebase*` | RT |

All three are real, not artefacts of the `fnmatch` approximation.

### 4.8 SEC-003 forms

| Command | Generated policy expectation | Actual OpenCode result | Evidence |
| :-- | :-- | :-- | :-- |
| `git add .` | deny | **deny** via `git add . *` (trailing-`" *"`-optional rule) | RT |
| `git add ./` | not caught | **ASK → executed** | RT |
| `git add *` | not caught | **ask** | MX (shell-globbed before OpenCode sees it in some cases) |
| `git add -A` | deny | **deny** via `git add -A*` | MX |
| `git add -Av` | deny | **deny** via `git add -A*` | MX |
| `git add -vA` | not caught | **ASK → executed** | RT |
| `git add -u` | not caught | **ASK → executed** | RT |
| `git add :/` | not caught | **ASK → executed** | RT |

### 4.9 Controls that must not be denied

| Command | Generated policy expectation | Actual OpenCode result | Evidence |
| :-- | :-- | :-- | :-- |
| `echo probe-baseline` | ask (`*`) | **ask → executed** | RT |
| `git stash list` | ask (safe, per Slice 5) | **ask → executed** | RT |
| `rm build/output.js` | ask (safe, per Slice 5) | **ask** | MX |
| `find . -name '*.pyc'` | ask (safe) | **ask** | MX |
| `git branch -d merged` | ask (safe) | **ask** | MX |

### 4.10 Slice 5 rules, confirmed live

| Command | Actual OpenCode result | Evidence |
| :-- | :-- | :-- |
| `find . -delete` | **deny** via `find * -delete*` | RT |
| `truncate -s 0 probe.txt` | **deny** via `truncate*` | RT |
| `git clean -n` | **deny** via `git clean*` (the deliberate Slice 5 decision) | RT |

---

## 5. Confirmed SEC-001 Status

### `SEC-001 CONFIRMED`

Confirmed on the installed version, at runtime, with stub execution as proof rather than
inference. Five commands the generated policy intends to deny were carried to execution:

```
git push          (from  bash -c 'git push')
sudo git push     (from  sudo git push)
git push          (from  env FOO=1 git push)
git push          (from  FOO=1 git push)
git push          (from  <tmp>/probe/bin/git push)
```

**Which forms bypass, and why.** The matched value is the `command` node's raw source
text, and every pattern is fully anchored (`^…$`). Anything that changes the head of that
text defeats every generated pattern, because all of them begin with a bare program name:

* **Path qualification** — `/abs/path/git push`. Confirmed at runtime with a stub path;
  confirmed at matcher level for `/usr/bin/git push`, `/…/env/bin/bench migrate`,
  `/usr/bin/mysql -u root`, `/bin/rm -rf .`.
* **Wrappers that keep the target inside one command node** — `sudo`, `env VAR=x`, a bare
  `VAR=x` assignment prefix, `nohup`, `time`, `command`. Confirmed at runtime for `sudo`,
  `env FOO=1`, `FOO=1`.
* **Shell-string wrappers** — `bash -c '…'`, `sh -c '…'`. The payload is a `raw_string`,
  never parsed into a `command` node. Confirmed at runtime.

**Which forms do NOT bypass** — this half of SEC-001 is *not* reproducible and the audit's
expectation was wrong here:

* **Chaining and piping** — `&&`, `||`, `;`, `|` are split into separate `command` nodes
  and each is matched. `echo safe && git push` is denied.
* **`cd /repo && bench migrate`** — `cd` is dropped from the pattern set, and
  `bench migrate` is matched on its own. Denied.
* **Redirection** — the redirected statement's full text is matched and the trailing `*`
  in the generated patterns absorbs the redirection. Denied.
* **`git -C <dir> <sub>` and `git --no-pager <sub>`** — caught by the `git * <sub>*` form.

---

## 6. Pattern Ordering

The slice's ordering question, driven through the extracted matcher with the exact V1
config shape the installed version accepts:

```
config:  { bash: { "*": "ask", "git *": "deny", "git status *": "allow" } }

ruleset (config key insertion order):
  0 "*"            -> ask
  1 "git *"        -> deny
  2 "git status *" -> allow

"git status --short"  -> allow   (decided by "git status *"; all matches: * , git * , git status *)
"git status"          -> allow   (the trailing " *" is optional)
"git push"            -> deny    (decided by "git *")
"ls"                  -> ask     (decided by "*")
```

Reversing the key order changes the answer, which proves ordering rather than specificity
decides:

```
config:  { bash: { "git status *": "allow", "git *": "deny", "*": "ask" } }
"git status --short"  -> ask
"git push"            -> ask
```

**`LAST MATCH WINS`** — `findLast` over the flattened rule list, whose order is JSON object
key insertion order, followed by session approvals. Not first-match, not most-specific.

This is safe for the dispatcher as written: `opencode_permissions()` inserts
`{"*": "ask"}` first and then every `deny`, so a dangerous command's last match is a
`deny`. It is also fragile in one specific way — **any future `allow` entry must be placed
after the denies it is meant to carve out of, and any `deny` must come after every broader
pattern it is meant to override.** A generator that emitted allows and denies in rule
order rather than in specificity order would silently invert.

---

## 7. Current Generated Policy

Measured from `load_boundaries()` + `opencode_permissions()` as the dispatcher calls them:

| | |
| :-- | :-- |
| Bash entries | **304** (1 base + 303 deny) |
| Serialised `permission` block | 17 493 bytes |
| Full `OPENCODE_CONFIG_CONTENT` (both levels) | 18 714 bytes |
| First / broadest rule | `"*": "ask"` — first key, so every later deny overrides it |
| Duplicate keys | none |
| Ordering behaviour | insertion order preserved through `json.dumps` → `Object.entries` → `findLast` |
| Overlapping entries | **52** deny entries are themselves matched by another deny entry of the same action (pure redundancy, no behavioural effect) |

Confirmed reaching the server: `GET /config` on a probe server started with the real
`OPENCODE_CONFIG_CONTENT` returned 304 `permission.bash` entries with `("*", "ask")` first,
and the same 304 entries under `agent.build.permission.bash`.

Commands matching multiple generated patterns:

```
git push                 2  ["*","git push*"]
rm -rf .                 3  ["*","rm -r*","rm -rf*"]
git add .                3  ["*","git add .","git add . *"]
git -C /x reset --hard   2  ["*","git * reset --hard*"]
bench --site x migrate   3  ["*","bench --site*","bench * migrate*"]
git stash push -m wip    2  ["*","git * push*"]
```

Not optimised, per the slice scope.

---

## 8. Confirmed Over-Matches

Safe commands that the **actual** OpenCode matcher denies because of generated patterns.
All three were predicted by Slice 5 and are now confirmed live rather than by
approximation:

| Safe command | Denied by | Why |
| :-- | :-- | :-- |
| `git stash push -m wip` | `git * push*` | The `git * <sub>*` form cannot require that `<sub>` is the subcommand; `stash` fills the `*` |
| `git checkout -b clean-branch` | `git * clean*` | A branch name containing `clean` after a space |
| `git config rebase.autoStash true` | `git * rebase*` | A config key containing `rebase` after a space |

Two further over-matches follow from the measured semantics and are worth stating even
though they were not exercised at runtime:

* **`git clean -n` / `git clean --dry-run`** are denied. This is the deliberate Slice 5
  decision, not an accident, and is confirmed live (`git clean*`).
* **`dd*`, `truncate*`, `shred*`** are bare program-prefix patterns, so any command whose
  name merely *starts* with one of them (`ddrescue`, `ddate`) is denied. Stated in the
  rule's own `intent` in Slice 5.

No safe command in the Slice 5 `not_examples` set was denied at runtime other than the
three above, which the data already records.

---

## 9. Implications for SEC-002 / SEC-003

Not fixed here. What the measurements imply for the shared-normalisation design:

**SEC-002 (wrappers).** The bypass is entirely in the *head* of a single `command` node's
text — `sudo`, `env VAR=x`, `VAR=x`, `nohup`, `time`, `command`, `bash -c '…'`. Because
OpenCode already splits chains for us, a normaliser does **not** need chain handling for
the delegated side; it needs exactly two operations: strip a leading path from the program
token, and peel a known wrapper prefix (including a `variable_assignment` prefix) to expose
the real program. `bash -c '<string>'` is different in kind: the payload never becomes a
`command` node, so no pattern over command text can reach it. Only denying the wrapper
programs themselves closes that one — which means the boundary data needs a decision about
`bash`/`sh`/`env`/`sudo` as *programs*, not a cleverer pattern.

**SEC-003 (equivalent staging forms).** `git add ./`, `git add -vA`, `git add -u` and
`git add :/` were all measured as `ask` → executed. Two distinct gaps: pathspec synonyms
(`.`, `./`, `:/`, `*`) which are a data question, and short-option clusters (`-vA` vs
`-Av`) which are a matcher question. The measured matcher offers no help for either —
`[`/`]` are escaped so character classes are unavailable, and `*` crosses spaces so
`-*A*`-style patterns over-match wildly. Cluster handling must therefore happen in the
*hook's* token layer and in the *pattern generator's* enumeration, not in a glob.

**Shared normalisation, generally.** The hook and the delegated policy see genuinely
different inputs — the hook sees the raw Bash-tool string and splits it itself; OpenCode
hands the delegated matcher one already-split command's source text. A shared normaliser
can therefore be shared at the level of *"given one command's text, what program and
arguments is it really"*, but the two engines must keep their own segment-splitting: the
hook needs its `SEPARATORS` regex, and the delegated side must not re-implement one because
tree-sitter already did it better.

---

## 10. Recommended Next Design

For the next slice, not implemented here:

1. **Normalise the head, not the line.** Add one function that takes a single command's
   text and returns `(program_basename, tokens)` after stripping a leading path and peeling
   `sudo` / `env VAR=x` / bare `VAR=x` / `nohup` / `time` / `command`. Drive both the hook's
   `program()`/`subcommand()` and the delegated pattern generator from it.
2. **For the delegated side, generate a path-and-wrapper-tolerant prefix.** Since the value
   is anchored source text, each rule needs its patterns emitted three ways: bare
   (`git push*`), path-qualified (`*/git push*`), and wrapper-prefixed
   (`* git push*` — noting this one also broadens over-matching, so it needs the
   over-match table from §8 extended in the same change).
3. **Decide `bash -c` / `sh -c` explicitly in the boundary data.** No pattern over command
   text can see inside the quoted payload. Either deny those programs for a delegated run,
   or accept and document the hole. This is a policy decision, not a matcher fix.
4. **Do not add chain handling to the delegated translation.** It is already correct.
5. **Re-anchor the `git * <sub>*` family.** The three confirmed over-matches all come from
   that one form. With normalisation in place it can be narrowed to the path/wrapper forms
   above and dropped as a general "anything between `git` and the subcommand" wildcard.
6. **Pin the ordering invariant in a test.** `findLast` means the generator's key order is
   load-bearing. A test that asserts `"*"` is emitted first, and that no `allow` is ever
   emitted before a `deny` it should override, costs little and protects a property nothing
   currently checks.
7. **Record the two out-of-model findings** from §3.1 in the README's limits: the
   `/session/{id}/shell` endpoint is unguarded, and an interactive "Allow always" outranks
   a config `deny`.

---

## Verification

```
$ git status --short
 M config/command-boundaries.json
 M hooks/guard.py
 M scripts/delegate
 M tests/test_parser.py
?? REVIEW_REPORT.md
?? OPENCODE_MATCHER_REPORT.md
```

The four modified files carry the uncommitted work of Slices 1–5; their mtimes are
14:15–14:19, before this slice began (~15:20). A recency sweep over the repository
confirms one new path and no touched source:

```
$ find . -newermt "2026-09-03 15:20:00" -not -path "./.git/*" -not -path "./.ruff_cache/*"
.
./.git
./OPENCODE_MATCHER_REPORT.md
```

**This slice created exactly one file: `OPENCODE_MATCHER_REPORT.md`.** `git diff` over
`scripts/delegate`, `hooks/guard.py`, `config/command-boundaries.json` and
`tests/test_parser.py` is byte-identical to its Slice 5 state. Nothing was committed.

Probe hygiene:

* All probe artefacts — stubs, isolated work directory, extracted WASM, extracted matcher,
  logs — live under the session scratchpad, never in the repository.
* Every executable a probe could reach (`git`, `bench`, `mysql`, `mariadb`, `rm`, `find`,
  `truncate`, `shred`, `dd`, `sudo`, `psql`, `redis-cli`) was a Python stub that appends
  argv to a log and exits 0. Verified inert before use: `rm -rf <dir>` against a real
  sentinel directory left it in place, and the sentinel still existed after every probe.
* No real `git push`, `bench`, database client, deletion, truncation or `sudo` ran. `/usr/bin`
  was never shadowed; the path-qualified case used an absolute path into the stub directory.
* `opencode serve` and both `opencode run` probes were terminated; `pgrep` for
  `opencode serve|run` and for the stub directory returns nothing, and
  `~/.local/state/opencode/locks/` is empty.
* No OpenCode install, upgrade or config file was modified; the policy was supplied only
  through `OPENCODE_CONFIG_CONTENT` in the probe processes' environment.
