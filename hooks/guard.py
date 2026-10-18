#!/usr/bin/env python3
"""PreToolUse guard: deny blanket staging and bare agent runs, ask before pushes, commits,
destructive operations and access to sites nobody authorised, and let routine work run.

Bash payloads: the command is lexed the way a shell reads it - separators inside quotes
are text, a heredoc body is input to the program that opened it, and only bodies that
reach a shell or an interpreter are matched as code (audit BUG-05: briefs, grep
patterns and file-writing heredocs used to raise prompts). Wrappers are peeled (`env`,
`sudo`, `nohup`, `timeout`, `xargs`, `bash -c`, `eval`, `$(...)`), so they no longer
hide a command from a rule. Prints a JSON permission decision when a rule matches, and
nothing otherwise.

Edit/Write payloads: denied while a delegated agent is still writing in the same
repository (two writers on one tree is how H-1 happened), and asked for when they change
this plugin's own site or model configuration.

Sites: a site runs without a prompt only when the user listed it as a development site
(`orch sites allow <site>` -> sites.json), or approved a command reaching it earlier in
this Claude Code session. A `.local` suffix no longer counts: some `.local` sites hold
restored client data. Sites listed as protected ask every time.

A failure *inside* this hook is not allowed through: once a command has been extracted, a
fault blocks it. Claude Code treats a crashed hook as a non-blocking error and runs the
command anyway, so a traceback here would authorise exactly what was not looked at.

The rules are in config/command-boundaries.json, which scripts/delegate reads as well.
"""

import contextlib
import json
import os
import re
import shlex
import stat
import sys
import tempfile
import time
from pathlib import Path

try:
    import fcntl
except ImportError:   # not on Windows; state updates there go unlocked
    fcntl = None

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
BOUNDARIES = PLUGIN_ROOT / "config" / "command-boundaries.json"
SCRIPTS = PLUGIN_ROOT / "scripts"

# `2>&1` and friends. The `&` in them is not a separator.
FD_DUPLICATION = re.compile(r"\d*>&\d*-?")

# Segments that may sit beside an allowed operation without cancelling it: changing into
# the bench directory, and reading the operation's output. None of them acts on anything.
ALLOW_COMPANIONS = frozenset({"cd", "tail", "head", "grep", "true", "echo"})

# Programs that execute what they are given as code: their heredoc bodies and their
# `-c` arguments are commands, not text.
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh", "fish"})
PYTHON = re.compile(r"(?:python[0-9.]*|pypy3?|ipython)\Z")

# Leading words that run the rest of the line as a command. Peeled before matching, so
# `env X=1 git push`, `sudo git push` and `nohup git push` are `git push` (SEC-002).
WRAPPERS = {
    "env": None, "sudo": {"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U"},
    "nohup": set(), "time": set(), "command": set(), "exec": set(), "nice": {"-n"},
    "ionice": {"-c", "-n"}, "stdbuf": set(), "timeout": {"-s", "-k", "--signal",
                                                         "--kill-after"},
    "xargs": {"-I", "-n", "-P", "-d", "-L", "-s", "-E", "-a", "--max-args",
              "--max-procs", "--delimiter", "--arg-file", "-i"},
}
ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")

# Options taking a separate argument, so the token after them is not the subcommand.
OPTS_WITH_ARG = {
    "git": {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"},
    "bench": {"--site", "-s"},
    "opencode": {
        "-m", "--model", "--agent", "--variant", "--prompt", "-s", "--session",
        "--log-level", "--port", "--hostname", "--mdns-domain", "--format", "--dir",
        "--command", "-f", "--file", "--title", "--attach", "-u", "--username",
        "-p", "--password", "--replay-limit",
    },
    "codex": {
        "-m", "--model", "-C", "--cd", "-s", "--sandbox", "-p", "--profile",
        "-c", "--config", "-a", "--ask-for-approval", "--color", "--add-dir",
        "-o", "--output-last-message", "--output-schema", "-i", "--image",
    },
}

# What the agent is told when a rule fires, keyed by rule name. For an ask, the user
# sees it in the prompt; for a deny, the agent reads it instead of running the command.
REASONS = {
    "push": (
        "Pushing is never automatic. Confirm the target branch and remote with the user "
        "first, state what will be pushed, and continue only once they agree."
    ),
    "commit": (
        "Commit approval. This prompt is the approval: the message and the staged files "
        "are in the command. Approve to commit, or deny and say what to change. The "
        "message is one short `feat: <summary>` line with no attribution."
    ),
    "blanket-staging": (
        "Do not stage with `git add .`, `-A`, `-u` or `:/` - it sweeps in unrelated work. "
        "Run `git status --porcelain` to see what changed, then stage only the files this "
        "task created or changed, by path."
    ),
    "discard-tracked-changes": (
        "`git reset --hard` (and --merge/--keep) throws away every uncommitted change in "
        "the tree, not only the ones belonging to this task, and unstaged work has no "
        "reflog entry to recover from. Confirm with the user what may be discarded. To "
        "move HEAD without touching files use `git reset --soft`; to unstage, "
        "`git reset <path>`."
    ),
    "discard-pathspec-changes": (
        "This overwrites working-tree files from the index or a commit, and unstaged "
        "content in those paths is not recoverable afterwards. Confirm with the user "
        "which files may be reverted, then revert them by path rather than with `.`."
    ),
    "discard-worktree": (
        "`git restore` overwrites working-tree files and `git clean` deletes untracked "
        "files, which Git keeps no copy of. Confirm with the user which paths may be "
        "discarded and name them explicitly."
    ),
    "drop-stash": (
        "This deletes stashed work permanently. Run `git stash list` and "
        "`git stash show -p` first, and confirm with the user before dropping anything."
    ),
    "force-branch-ref": (
        "This deletes an unmerged branch or moves an existing branch onto another commit. "
        "Confirm the branch and the target with the user first; `git branch -d` deletes "
        "only what is already merged."
    ),
    "expire-recovery-refs": (
        "The reflog is what makes a bad reset or rebase survivable, and this drops it. Do "
        "not run it to tidy up; it is the user's decision."
    ),
    "rewrite-repository-history": (
        "This rewrites commits or writes a ref directly. Confirm the operation and its "
        "scope with the user before continuing."
    ),
    "recursive-delete": (
        "A recursive delete takes everything below the path, tracked or not. Confirm the "
        "path with the user, or delete the specific files this task is responsible for."
    ),
    "mass-delete": (
        "`find ... -delete` (or `-exec rm`) removes every path the traversal matched. Run "
        "the search without it first, then remove what belongs to this task by name."
    ),
    "overwrite-file-contents": (
        "shred, truncate and dd overwrite bytes in place with nothing to restore from. "
        "Edit the file normally, or have the user confirm the exact target."
    ),
    "asset-build": (
        "Asset build: touches no site, so it runs without a prompt. Check the output for a "
        "build failure before treating the assets as rebuilt."
    ),
    "destructive-site-operation": (
        "This destroys or overwrites site data, resets credentials or sessions, or opens a "
        "raw database shell. It asks on every site, development sites included. Confirm "
        "the operation and the single target site with the user. A read-only "
        "`bench --site <site> mariadb -e \"SELECT ...\"` does not need this."
    ),
    "bench-environment-change": (
        "This changes the bench itself - apps, sites, branches, or the services setup - "
        "and is not part of implementing a change. Confirm it with the user first."
    ),
    "site-named": (
        "This runs against a site that is not listed as a development site. Confirm with "
        "the user which single site to target. If you only need a DocType definition or "
        "other committed configuration, read that file in the working tree instead."
    ),
    "site-unnamed": (
        "This bench subcommand acts on a site, and no site is named, so bench picks one "
        "from `default_site` / currentsite.txt. Name it: `bench --site <site> <subcommand>`, "
        "using the development site from OPERATIONS.md or `orch sites list`."
    ),
    "remote-execution": (
        "This opens a shell or copies files on another machine, where nothing the hook "
        "checks applies. Remote and production operations belong to the user's own "
        "deployment tooling; confirm with the user before continuing."
    ),
    "database-client": (
        "This runs against a live database directly. Confirm with the user which single "
        "site or database to target before continuing."
    ),
    "frappe-connection": (
        "This opens a connection to a site that is not listed as a development site, or "
        "whose site cannot be read from the command. Confirm the single site with the user."
    ),
    "bare-agent-run": None,   # filled in below - the agent rules share one text
    "bare-agent-exec": None,
    "bare-agent-print": None,
}

DELEGATE = str(SCRIPTS / "delegate")

AGENT_REASON = (
    "Coding agents run through the dispatcher, not directly. Use `" + DELEGATE + " "
    "--agent <opencode|codex|claude> --mode <implement|review|test|onboard|deliberate> "
    "--tier <TIER> --cwd <repository root>` with the brief on stdin; for Debate Mode, run "
    "`scripts/debate`, which calls it. The dispatcher supplies the verified model, the "
    "timeout, process-tree containment, the delegated permission policy and the result "
    "contract. A bare invocation skips all of them."
)
REASONS["bare-agent-run"] = AGENT_REASON
REASONS["bare-agent-exec"] = AGENT_REASON
REASONS["bare-agent-print"] = AGENT_REASON

# This plugin's own scripts run without a prompt: they are the workflow, and each one
# already validates what it is given. These subcommands change what later runs without
# a prompt, or spend provider usage, so they ask.
PLUGIN_SCRIPTS = frozenset({"delegate", "debate", "orch"})
PLUGIN_ASK = {
    ("sites", "allow"): "This lets every routine command reach the site with no prompt, "
                        "for every future session. Approve only for a site with no real "
                        "client data.",
    ("sites", "remove"): "This changes which sites need a prompt.",
    ("models", "promote"): "This changes the OpenCode model every delegated "
                           "implementation uses.",
    ("models", "codex"): "This pins the model every Codex review uses.",
    ("models", "verify"): "This runs a real OpenCode task on the candidate model and "
                          "spends provider usage.",
    ("models", "reset"): "This changes which models run.",
    ("claude-default", "--apply"): "This writes \"model\": \"opus\" to "
                                   "~/.claude/settings.json (a backup is kept).",
}

# Last resort, and deliberately not a second copy of the rules: the programs any rule has
# ever been about. If the boundary data cannot be loaded there are no rules to apply, and
# silently enforcing nothing is the one failure mode this hook must not have.
GUARDED_PROGRAMS = frozenset({
    "git", "bench", "mysql", "mariadb", "opencode", "codex", "claude",
    "rm", "find", "shred", "truncate", "dd",
})

# The match kinds this hook implements, and the fields each needs in order to be matched.
MATCH_FIELDS = {
    "segment_text": {"lists": ("identifiers",)},
    "program": {"lists": ("programs",)},
    "program_option": {"names": ("program",), "lists": ("options",)},
    "program_subcommand": {"names": ("program",), "lists": ("subcommands",)},
}
OPTIONAL_LISTS = ("any_argument", "unless_flags")

# `allow` skips Claude Code's own prompt; printing nothing leaves that prompt in place.
HOOK_DECISIONS = frozenset({"ask", "deny", "allow"})

# Strongest first. One command is one unit, so the strongest decision any segment earns
# is the decision for all of it - an allowed migrate chained to a push still asks.
DECISION_STRENGTH = ("deny", "ask", "allow")

def _string_list(value):
    """A non-empty list of non-empty strings, the only shape these fields can match on."""
    return (
        isinstance(value, list)
        and bool(value)
        and all(isinstance(item, str) and item for item in value)
    )


def rule_fault(rule, index):
    """Why this rule cannot be enforced as written, or None if it can be."""
    if not isinstance(rule, dict):
        return "rule %d is a %s, not an object" % (index, type(rule).__name__)
    name = rule.get("name")
    if not isinstance(name, str) or not name:
        return "rule %d has no name" % index
    decision = rule.get("hook")
    if decision is not None and decision not in HOOK_DECISIONS:
        return "%s: hook decision %r is not ask, deny, allow or null" % (name, decision)
    # Only an ask can be relaxed by the site it reaches. Flagging a deny, or an allow,
    # would read as a policy while doing nothing - or, misread later, something else.
    site_access = rule.get("site_access", False)
    if not isinstance(site_access, bool):
        return "%s: site_access is %r, not true or false" % (name, site_access)
    if site_access and decision != "ask":
        return "%s: site_access is set on a rule the hook does not ask on" % name
    match = rule.get("match")
    if not isinstance(match, dict):
        return "%s: match is not an object" % name
    fields = MATCH_FIELDS.get(match.get("kind"))
    if fields is None:
        return "%s: match kind %r is not one this hook implements" % (
            name, match.get("kind")
        )
    for field in fields.get("names", ()):
        value = match.get(field)
        if not isinstance(value, str) or not value:
            return "%s: match.%s is %r, not a program name" % (name, field, value)
    for field in fields.get("lists", ()):
        if not _string_list(match.get(field)):
            return "%s: match.%s is not a non-empty list of strings" % (name, field)
    for field in OPTIONAL_LISTS:
        if field in match and not _string_list(match[field]):
            return "%s: match.%s is not a non-empty list of strings" % (name, field)
    return None


def load_rules():
    """(rules this hook enforces, in precedence order, None), or (None, why it cannot).

    One faulty entry invalidates the whole set rather than being skipped, because rule
    order is precedence: a rule this hook cannot match is not merely inert, the next rule
    matches in its place and decides something else. Skipping it would silently move a
    command from one rule's decision to another's.

    A rule the data itself excludes - `hook: null`, meaning it is not this hook's to
    enforce - is a different thing, and is still dropped. That exclusion is stated in the
    data and is the answer, not a gap in it.
    """
    try:
        data = json.loads(BOUNDARIES.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError) as exc:
        return None, "%s could not be read (%s: %s)" % (
            BOUNDARIES, type(exc).__name__, exc
        )
    if not isinstance(data, dict):
        return None, "%s holds a %s, not an object" % (BOUNDARIES, type(data).__name__)
    rules = data.get("rules")
    if not isinstance(rules, list):
        return None, "%s has no rules list (found %s)" % (
            BOUNDARIES, type(rules).__name__
        )
    if not rules:
        return None, "%s declares no rules at all" % BOUNDARIES
    usable = []
    for index, rule in enumerate(rules):
        fault = rule_fault(rule, index)
        if fault is not None:
            return None, "%s cannot be enforced as written - %s" % (BOUNDARIES, fault)
        if not rule.get("hook"):
            continue
        match = rule["match"]
        if match["kind"] == "segment_text":
            # Word-bounded so `frappe.db` does not fire on `frappe.database`. Built here
            # rather than stored as a regex: the data says which identifiers matter, and
            # this is the one engine that expresses that as a pattern.
            try:
                pattern = re.compile(
                    "(?:%s)\\b" % "|".join(re.escape(i) for i in match["identifiers"])
                )
            except re.error as exc:
                return None, "%s cannot be enforced as written - %s: identifiers do " \
                             "not compile (%s)" % (BOUNDARIES, rule["name"], exc)
            rule = dict(rule, _pattern=pattern)
        usable.append(rule)
    if not usable:
        return None, "no rule in %s declares a decision for this hook" % BOUNDARIES
    return usable, None


RULES, RULES_FAULT = load_rules()


def degraded_reason():
    """What a caller is told when the rules could not be loaded at all.

    Built when it is needed rather than at import, so it always reports the fault this
    process actually hit.
    """
    return (
        "The command boundaries are not being enforced right now, and this command is "
        "one they cover. %s. Until that file loads, nothing in this hook is guarding the "
        "push, staging, live-site or agent-CLI boundaries - so treat this command as "
        "unreviewed, and fix the file before continuing. A hook that cannot load its "
        "rules is not protecting anything."
    ) % (RULES_FAULT or "The reason was not recorded")

RULES_BY_NAME = {rule["name"]: rule for rule in RULES or []}


def split_tokens(segment):
    try:
        return shlex.split(segment, comments=False)
    except ValueError:  # unbalanced quotes - fall back to a plain split
        return segment.split()


def program(tokens):
    """Program name with any leading path stripped, or None for an empty segment."""
    return tokens[0].rsplit("/", 1)[-1] if tokens else None


def subcommand(tokens, opts_with_arg):
    """First non-option token after the program name, or None."""
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token in opts_with_arg:
            i += 2
        elif token.startswith("-"):
            i += 1
        else:
            return token
    return None


GROUPING = frozenset({"(", ")", "{", "}", "!", "if", "then", "else", "elif", "fi", "do",
                      "done", "while", "until", "for", "in", "esac", ";;"})


def normalize(tokens):
    """The tokens of the command that actually runs: grouping and wrappers peeled off.

    `( cd x && git push )`, `env A=1 git push`, `sudo -u u git push`, `timeout 30 git push`,
    `xargs git push`, `env -S 'git push'` and a `case` arm `a) git push` all come back as
    `git push ...`, so a wrapper is never a way around a rule.
    """
    tokens = list(tokens)
    for _ in range(8):
        while tokens and tokens[0] in GROUPING:
            tokens = tokens[1:]
        if tokens and tokens[0] == "case":
            arm = next((i for i, t in enumerate(tokens) if t.endswith(")")), None)
            tokens = tokens[arm + 1:] if arm is not None else []
            continue
        if len(tokens) > 1 and tokens[0].endswith(")") and not tokens[0].startswith("("):
            tokens = tokens[1:]   # a case arm pattern: `a)`, `*)`
            continue
        break
    if tokens and tokens[0][:1] in "({":
        tokens[0] = tokens[0].lstrip("({")
    while tokens and tokens[-1] in (")", "}", ";;"):
        tokens = tokens[:-1]
    for _ in range(8):
        if not tokens:
            break
        if ENV_ASSIGNMENT.match(tokens[0]):
            tokens = tokens[1:]
            continue
        name = program(tokens)
        if name not in WRAPPERS:
            break
        options = WRAPPERS[name] or set()
        i, split = 1, None
        while i < len(tokens):
            token = tokens[i]
            if name == "env" and ENV_ASSIGNMENT.match(token):
                i += 1
            elif name == "env" and token in ("-S", "--split-string") and i + 1 < len(tokens):
                split = split_tokens(tokens[i + 1])
                i += 2
                break
            elif name == "env" and token.startswith(("-S", "--split-string=")):
                split = split_tokens(token.split("=", 1)[1] if "=" in token else token[2:])
                i += 1
                break
            elif token == "--":
                i += 1
                break
            elif token.startswith("-"):
                i += 2 if token in options or (name == "env" and token in ("-u", "-C"))\
                    else 1
            else:
                break
        if name == "timeout" and split is None and i < len(tokens):
            i += 1   # the duration
        tokens = (split or []) + tokens[i:]
    return tokens


class Segment:
    """One unit the hook decides about.

    kind "command" is a command line; "code" is program text an interpreter runs (a
    python heredoc, `python -c`), matched only by segment_text rules; "body" is a heredoc
    body not yet classified. `owner` is the Segment whose input it is.
    """

    __slots__ = ("text", "kind", "owner", "tokens", "name", "has_heredoc")

    def __init__(self, text, kind="command", owner=None):
        self.text, self.kind, self.owner = text, kind, owner
        self.has_heredoc = False
        # $'...' is ANSI-C quoting: `$'git' push` runs git.
        self.tokens = normalize(split_tokens(ANSI_C_QUOTE.sub("'", text))) \
            if kind == "command" else []
        self.name = program(self.tokens)


HEREDOC_OP = re.compile(r"<<(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
ANSI_C_QUOTE = re.compile(r"\$'")

# Command and process substitution: a command inside another, wherever it sits.
SUBSTITUTION = re.compile(r"\$\(|`|<\(|>\(")


def _substitution(text, i):
    """(inner text, end index) of the substitution starting at text[i].

    Parentheses inside quotes do not count: `$(echo ")"; git push)` ends at the last `)`.
    """
    if text[i] == "`":
        end = text.find("`", i + 1)
        end = len(text) if end < 0 else end
        return text[i + 1:end], min(end + 1, len(text))
    depth, j, quote = 0, i + 1, None
    while j < len(text):
        c = text[j]
        if quote:
            if c == "\\" and quote == '"':
                j += 1
            elif c == quote:
                quote = None
        elif c == "\\":
            j += 1
        elif c in "'\"":
            quote = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return text[i + 2:j], j + 1
        j += 1
    return text[i + 2:], len(text)


def _substitutions_in(text, depth):
    """Commands inside `$(...)` and backticks anywhere in `text` (an unquoted heredoc body,
    which bash expands before the program reads it)."""
    found, i = [], 0
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "`" or text.startswith("$(", i):
            inner, end = _substitution(text, i)
            found += _lex(inner, depth + 1) if depth < 4 else [Segment(inner)]
            i = end
            continue
        i += 1
    return found


def _lex(command, depth=0):
    """[Segment] in order: commands, heredoc bodies after their owners, then the commands
    found inside substitutions. Quotes are honoured - a `;` or `|` inside quotes is text -
    a comment runs to the end of its line, and a backslash-newline joins two lines, as in
    bash. A body's `owner` is the Segment object that opened it. Linear in the input."""
    text = FD_DUPLICATION.sub(" ", command.replace("\\\n", ""))
    out, extra, buf, pending = [], [], [], []
    quote = None
    word_start = True   # the next character would begin a word (so `#` starts a comment)
    arith = 0           # inside a bare `(( ... ))`, where `<<` is a shift, not a heredoc
    i, n = 0, len(text)

    def flush():
        chunk = "".join(buf)
        buf.clear()
        if chunk.strip():
            segment = Segment(chunk)
            out.append(segment)
            for entry in pending:
                if entry["owner"] is None:
                    entry["owner"] = segment

    while i < n:
        c = text[i]
        if quote == "'":
            buf.append(c)
            if c == "'":
                quote = None
            i += 1
            continue
        if c == "\\" and i + 1 < n:
            buf.append(text[i:i + 2])
            i += 2
            word_start = False
            continue
        if c == "`" or text.startswith("$(", i) or (
                quote is None and (text.startswith("<(", i) or text.startswith(">(", i))):
            inner, end = _substitution(text, i)
            extra += _lex(inner, depth + 1) if depth < 4 else [Segment(inner)]
            buf.append(text[i:end])
            i = end
            word_start = False
            continue
        if quote == '"':
            buf.append(c)
            if c == '"':
                quote = None
            i += 1
            continue
        if c in "'\"":
            quote = c
            buf.append(c)
            i += 1
            word_start = False
            continue
        if text.startswith("((", i):
            arith += 1
            buf.append("((")
            i += 2
            word_start = False
            continue
        if arith and text.startswith("))", i):
            arith -= 1
            buf.append("))")
            i += 2
            continue
        if not arith and text.startswith("<<", i) and not text.startswith("<<<", i):
            found = HEREDOC_OP.match(text, i)
            if found:
                pending.append({"delimiter": found.group(3), "strip": found.group(1) == "-",
                                "expands": not found.group(2), "owner": None})
                buf.append(found.group(0))
                i = found.end()
                word_start = False
                continue
        if c == "#" and word_start:
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if c == "&" and text.startswith("&>", i):
            buf.append("&>")
            i += 2
            word_start = True
            continue
        if c in ";&|\n":
            flush()
            i += 1
            word_start = True
            if c == "\n" and pending:
                i = _bodies(text, i, pending, out, extra, depth)
                pending = []
            continue
        buf.append(c)
        word_start = c in " \t()"
        i += 1
    flush()
    return out + extra


def _bodies(text, i, pending, out, extra, depth):
    """Consume the heredoc bodies opened on the line just ended. Returns the new index.
    An unquoted delimiter means bash expands `$(...)` in the body: those are commands."""
    for entry in pending:
        lines = []
        while i < len(text):
            end = text.find("\n", i)
            end = len(text) if end < 0 else end
            line = text[i:end]
            i = end + 1
            if (line.lstrip("\t") if entry["strip"] else line) == entry["delimiter"]:
                break
            lines.append(line)
        body = "\n".join(lines)
        if entry["expands"]:
            extra += _substitutions_in(body, depth)
        if entry["owner"] is not None:
            entry["owner"].has_heredoc = True
            out.append(Segment(body, kind="body", owner=entry["owner"]))
    return i


def _inner(segment):
    """Command strings a segment runs as code of its own: `bash -c`, `eval`, `find -exec`,
    and the program text of `python -c`."""
    tokens, name = segment.tokens, segment.name
    if name in SHELLS:
        for i, token in enumerate(tokens[1:-1], 1):
            if re.match(r"-[A-Za-z]*c[A-Za-z]*\Z", token):
                rest = tokens[i + 1:]
                if rest and rest[0] == "--":
                    rest = rest[1:]
                return [(rest[0], "command")] if rest else []
    if name == "eval" and len(tokens) > 1:
        return [(" ".join(tokens[1:]), "command")]
    if name == "find":
        found, i = [], 1
        while i < len(tokens):
            if tokens[i] in ("-exec", "-execdir", "-ok", "-okdir"):
                j = i + 1
                while j < len(tokens) and tokens[j] not in (";", "+", "\\;"):
                    j += 1
                found.append((" ".join(tokens[i + 1:j]), "command"))
                i = j
            i += 1
        return found
    if name and PYTHON.match(name) and "-c" in tokens:
        index = tokens.index("-c")
        if index + 1 < len(tokens):
            return [(tokens[index + 1], "code")]
    return []


MAX_EXPANSIONS = 32


def _reads_stdin(segment):
    """A bare python interpreter: it runs whatever arrives on stdin."""
    if segment.kind != "command" or not (segment.name and PYTHON.match(segment.name)):
        return False
    if segment.has_heredoc:
        return False   # the heredoc body is classified on its own
    args = segment.tokens[1:]
    if any(a in ("-c", "-m") for a in args):
        return False
    positional = [a for a in args if not a.startswith("-") or a == "-"]
    return not positional or positional[0] == "-"


def lex_command(command):
    """Every Segment of a command, with inner commands expanded and heredoc bodies
    classified by who reads them.

    A body is a command list only when a shell is in the command (`bash <<EOF`,
    `cat <<EOF | sh`), program text when Python or bench reads it (`python - <<EOF`,
    `bench --site s console <<EOF`), and otherwise data - a brief for the dispatcher, a
    file being written, a commit message - which no rule looks at.
    """
    segments = _lex(command)
    index, expansions = 0, 0
    while index < len(segments):
        segment = segments[index]
        index += 1
        if segment.kind != "command" or expansions >= MAX_EXPANSIONS:
            continue
        for text, kind in _inner(segment):
            expansions += 1
            segments += [Segment(text, "code", segment)] if kind == "code" else _lex(text, 1)
    names = {s.name for s in segments if s.kind == "command"}
    shell = bool(names & SHELLS)
    python = any(n and (PYTHON.match(n) or n == "bench") for n in names)
    if any(_reads_stdin(s) for s in segments):
        # `echo '...' | python3`: what flows into it is program text.
        segments += [Segment(s.text, "code", s) for s in segments
                     if s.kind == "command" and not _reads_stdin(s)]
    result = []
    for segment in segments:
        if segment.kind != "body":
            result.append(segment)
        elif shell:
            result += _lex(segment.text, 1)
        elif python:
            result.append(Segment(segment.text, "code", segment.owner))
    return result


# A plain hostname: dot-separated labels of letters, digits and inner hyphens. Anything
# else - a variable, a glob, a brace list, a path - is not something this hook can say
# which site it means.
SITE_NAME = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\Z"
)
SITE_OPTIONS = ("--site", "-s")

# Calls that choose which site a snippet is connected to.
SITE_CALL = re.compile(r"\bfrappe\.(?:init_site|init|connect)\b")
SITE_CALL_LITERAL = re.compile(
    r"""frappe\.(?:init_site|init|connect)\(\s*(?:site\s*=\s*)?\\?(['"])([^'"\\\s]+)\\?\1\s*[,)]"""
)
SITE_REUSE = re.compile(r"frappe\.connect\(\s*\)")

AMBIGUOUS = object()   # a bench command that names a site option, but not one usable site

# Statements a read-only `mariadb -e` may contain. Anything else, or any of the words in
# SQL_WRITES anywhere outside a string literal, keeps the destructive-operation ask.
SQL_READS = frozenset({"select", "show", "describe", "desc", "explain", "with"})
SQL_WRITES = re.compile(
    r"\b(insert|update|delete|replace|drop|alter|create|truncate|grant|revoke|rename|"
    r"call|handler|load|lock|unlock|set|use|into|outfile|dumpfile|sleep|benchmark|"
    r"load_file|flush|kill|shutdown|install|uninstall|prepare|execute|do)\b", re.I)


def readonly_sql(sql):
    # MariaDB executes /*! ... */ comments, the client runs `\!` and `system` commands, and
    # `--` starts a comment only before whitespace: none of those is treated as harmless.
    if "/*!" in sql or "\\" in sql or re.search(r"\b(system|source|pager|tee)\b", sql, re.I):
        return False
    stripped = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`", "''", sql)
    stripped = re.sub(r"--(?=\s|$)[^\n]*|#[^\n]*|/\*.*?\*/", " ", stripped, flags=re.S)
    statements = [s.strip() for s in stripped.split(";") if s.strip()]
    if not statements or SQL_WRITES.search(stripped):
        return False
    return all(s.split(None, 1)[0].lower() in SQL_READS for s in statements)


def readonly_mariadb(segment):
    """`bench --site <s> mariadb|db-console -e "<read-only SQL>"`, fed nothing else."""
    tokens = segment.tokens
    if segment.name != "bench" or segment.has_heredoc or "<" in tokens:
        return False
    if subcommand(tokens, OPTS_WITH_ARG["bench"]) not in ("mariadb", "db-console"):
        return False
    statements = []
    for i, token in enumerate(tokens):
        if token in ("-e", "--execute") and i + 1 < len(tokens):
            statements.append(tokens[i + 1])
        elif token.startswith(("--execute=", "-e")) and token not in ("-e", "--execute"):
            statements.append(token.split("=", 1)[1] if "=" in token else token[2:])
    # Exactly one: the client runs the last -e it is given, not the first.
    return len(statements) == 1 and readonly_sql(statements[0])


# Program text that does more than read a site: writes or deletes files, runs commands,
# reaches the network, or changes site data. The site allowlist authorises routine
# *inspection*; code like this is left to Claude Code's own permission check instead of
# being allowed by the hook.
CODE_EFFECTS = re.compile(
    r"\bos\.(system|popen|remove|unlink|rmdir|removedirs|rename|replace|kill|exec\w*|"
    r"spawn\w*|chmod|chown|truncate)\b|\bsubprocess\b|\bshutil\.|\bPopen\b|\bpty\.|"
    r"\bsocket\b|\bctypes\b|__import__|\bimportlib\b|\b(exec|eval|compile)\s*\(|"
    r"\bopen\s*\([^)]*['\"][wax]|\.write_(text|bytes)\s*\(|\.(unlink|rmdir|rename)\s*\(|"
    r"\brequests\.|\burllib\b|\bhttp\.client\b|"
    r"\bfrappe\.db\.(delete|truncate|commit|set_value|set_single_value|bulk_insert|"
    r"multisql|sql_ddl)\b|\bdelete_doc\b|\brename_doc\b|\bdb_set\s*\(|"
    r"\.(save|insert|submit|cancel|delete|db_update)\s*\(|\bfrappe\.(set_user|enqueue)\b")
SQL_IN_CODE_WRITES = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|replace|create|grant)\b", re.I)


def code_has_effects(segment):
    """Program text (or a python command line) that would do more than inspect."""
    if segment.kind == "code" or (segment.name and PYTHON.match(segment.name)):
        text = segment.text
        if CODE_EFFECTS.search(text):
            return True
        return "frappe.db.sql" in text and bool(SQL_IN_CODE_WRITES.search(text))
    return False


# An output redirect: `> file`, `>> file`, `2> file`, `&> file`, `>| file`.
REDIRECT = re.compile(r"(?:^|[\s;])(?:\d*|&)>>?\|?\s*([^\s;&|]+)")
QUOTED = re.compile(r"'[^']*'|\"(?:[^\"\\]|\\.)*\"")


def writes_file(segment):
    """A command segment that redirects output into a file. Text inside quotes does not
    count; `/dev/null` and fd duplication do not count."""
    if segment.kind != "command":
        return False
    text = QUOTED.sub("''", segment.text)
    return any(target not in ("/dev/null", "/dev/stdout", "/dev/stderr")
               for target in REDIRECT.findall(text))


def plugin_script(segment):
    """(script name, its arguments) when the segment runs one of this plugin's scripts."""
    tokens = list(segment.tokens)
    if tokens and PYTHON.match(program(tokens) or "") and len(tokens) > 1:
        tokens = tokens[1:]
    if not tokens or program(tokens) not in PLUGIN_SCRIPTS:
        return None
    path = os.path.expandvars(os.path.expanduser(tokens[0]))
    try:
        if Path(path).resolve().parent != SCRIPTS.resolve():
            return None
    except OSError:
        return None
    return program(tokens), tokens[1:]


def plugin_decision(script):
    name, args = script
    positional = [a for a in args if not a.startswith("-")]
    if name == "orch":
        # Any option to claude-default counts as --apply: argparse would accept `--app`.
        key = tuple(positional[:2]) if positional[:1] != ["claude-default"] else (
            "claude-default", "--apply" if any(a.startswith("-") for a in args) else "")
        reason = PLUGIN_ASK.get(key)
        if reason:
            return "ask", reason
    return "allow", "frappe-orchestrator's own %s; it runs without a prompt." % name


def rule_matches(rule, segment):
    """Does this segment fall under this rule?"""
    match = rule["match"]
    kind = match.get("kind")
    tokens, name = segment.tokens, segment.name

    if kind == "segment_text":
        # Only where the text is code something will run: program text of an
        # interpreter, or the command line of python/bench itself. A grep pattern, an
        # echo, a brief and a file-writing heredoc are text (audit BUG-05).
        if segment.kind == "code" or (name and (PYTHON.match(name) or name == "bench")):
            return bool(rule["_pattern"].search(segment.text))
        return False
    if segment.kind != "command":
        return False

    if kind == "program":
        return name in match.get("programs", ())

    if name != match.get("program"):
        return False

    if kind == "program_option":
        return any(option in tokens for option in match.get("options", ()))

    if kind == "program_subcommand":
        # An informational flag means the CLI prints text and exits. Whole tokens only.
        unless = match.get("unless_flags")
        if unless and set(unless).intersection(tokens):
            return False
        if subcommand(tokens, OPTS_WITH_ARG.get(name, frozenset())) not in match.get(
            "subcommands", ()
        ):
            return False
        arguments = match.get("any_argument")
        return not arguments or bool(set(arguments).intersection(tokens))

    return False   # a kind this hook does not implement; the suite fails by rule name


def _as_segment(segment):
    return segment if isinstance(segment, Segment) else Segment(segment)


def match_rule(segment):
    """The first rule this segment falls under, or None. Data order is precedence."""
    if RULES is None:
        return None
    segment = _as_segment(segment)
    if segment.kind == "command" and readonly_mariadb(segment):
        return RULES_BY_NAME.get("site-named")
    for rule in RULES:
        if rule_matches(rule, segment):
            return rule
    return None


def evaluate(segment):
    """(decision, reason, rule or None) for one segment, or None when nothing applies."""
    segment = _as_segment(segment)
    if RULES is None:
        # Degraded: no rules loaded. Ask on the programs the rules are about.
        if segment.name in GUARDED_PROGRAMS:
            return "ask", degraded_reason(), None
        return None
    if segment.kind == "command":
        script = plugin_script(segment)
        if script:
            decision, reason = plugin_decision(script)
            return decision, reason, None
    rule = match_rule(segment)
    if rule is None:
        return None
    return rule["hook"], REASONS.get(rule["name"]) or rule.get("intent", ""), rule


def check(segment):
    """Return (decision, reason) if a rule matches this command segment, else None."""
    found = evaluate(segment)
    return found[:2] if found else None


INTERNAL_FAILURE_REASON = (
    "Blocked by an internal failure in the enforcement hook, not by a rule: it faulted "
    "while deciding whether this command crosses a command boundary, so it never "
    "established whether one applies (%s). Blocked rather than put to the user, because "
    "a prompt would ask for approval of a command nobody has evaluated. Report the fault "
    "- while the hook is faulting, no boundary is being enforced for any command - and "
    "do not work around it by rephrasing the command."
)

# Claude Code's blocking exit status for a PreToolUse hook. Any other non-zero status is
# a *non-blocking* error there: the command runs.
BLOCKED_EXIT = 2


def emit(decision, reason):
    """Write the one permission decision this hook is allowed to produce.

    The only place this JSON shape is written. A second copy is how the field names drift
    apart from what Claude Code parses.
    """
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": decision,
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )


def fail_closed(detail):
    """Block the command this hook failed to evaluate. Does not return.

    Both signalling layers, deliberately, because this runs precisely when something in
    the hook is already not working: `deny` is the decision Claude Code acts on, and exit
    2 blocks on its own with stderr fed back, which covers the case where the JSON never
    arrived - a half-written stdout, a closed pipe, a decision that could not be parsed.
    Either alone is enough while the hook is healthy, which is not the situation here.
    """
    reason = INTERNAL_FAILURE_REASON % detail
    try:
        emit("deny", reason)
        sys.stdout.flush()
    except Exception:
        pass   # not a silent failure: the exit status below blocks without stdout
    try:
        print(reason, file=sys.stderr)
    except Exception:
        pass   # same - stderr is the diagnostic, not the mechanism
    raise SystemExit(BLOCKED_EXIT)


def read_payload():
    """The hook payload on stdin as a dict, or an empty dict. Never raises."""
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError, RecursionError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_command(payload):
    """The Bash command in a hook payload, or None. Never raises.

    None means there is nothing here to decide about: no payload, no `tool_input`, no
    `command`, or a `command` that is not a usable string. That case passes through, which
    is this hook's existing protocol for input it does not recognise.

    It is deliberately not the same as "deciding failed". Every failure this function
    swallows happened before a command was in hand, so there is nothing it could have
    authorised. A failure with a command in hand is main()'s to handle, and is not an
    allow.
    """
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    return command


# --------------------------------------------------------------------------
# Sites and per-session approval
#
# Which rules this applies to is data - `site_access` in the boundary file. Which sites
# run without a prompt is the user's list, in sites.json under the plugin's config dir
# (`orch sites`). What this session approved is session state.
# --------------------------------------------------------------------------

# Claude Code's session id is a UUID. Anything else gets no stored approvals at all.
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
TOOL_USE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")

STALE_STATE_SECONDS = 7 * 24 * 3600
MAX_PENDING = 32

DEVELOPMENT_REASON = (
    "Routine access to %s, listed as a development site in the frappe-orchestrator "
    "sites list, so it runs without a prompt. Keep to the sites the task needs, and stop "
    "for the user before a migration that may drop or transform data. Destructive site "
    "operations and unlisted sites still ask."
)
SESSION_REASON = (
    "Routine access to %s, which the user approved earlier in this Claude Code session, "
    "so it runs without a prompt until the session ends. Destructive site operations and "
    "other sites still ask."
)
AWAITING_NOTE = (
    " If the user approves and the command runs, routine access to %s runs without a "
    "prompt for the rest of this Claude Code session. To stop being asked in every "
    "session, the user can list it with `orch sites allow %s` - only for a site with no "
    "real client data."
)
PROTECTED_NOTE = (
    " %s is listed as protected, so this asks every time and is never remembered."
)


def config_dir():
    override = os.environ.get("FRAPPE_ORCHESTRATOR_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "frappe-orchestrator"


def site_lists():
    """(development sites, protected sites) from sites.json. Unreadable reads as empty -
    the safe direction, since an unlisted site asks."""
    try:
        data = json.loads((config_dir() / "sites.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset(), frozenset()
    if not isinstance(data, dict):
        return frozenset(), frozenset()

    def names(key):
        value = data.get(key)
        return frozenset(s for s in value if valid_site(s)) if isinstance(value, list) \
            else frozenset()

    return names("development"), names("protected")


def valid_site(site):
    """A single site name this hook can compare exactly. `all` is every site, not one."""
    return (
        isinstance(site, str)
        and len(site) <= 253
        and site.lower() != "all"
        and bool(SITE_NAME.match(site))
    )


def is_development_site(site):
    """Listed by the user as a development site, and not also listed as protected."""
    development, protected = site_lists()
    # Exact, not case-folded: a Frappe site is a directory name, and on Linux `DEMO.x` is
    # not `demo.x`.
    return valid_site(site) and site in development and site not in protected


def bench_site(tokens):
    """The one site a bench command names, None if it names none, AMBIGUOUS otherwise."""
    named = []
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token in SITE_OPTIONS:
            named.append(tokens[i + 1] if i + 1 < len(tokens) else None)
            i += 2
            continue
        if token.startswith("--site="):
            named.append(token[len("--site="):])
        i += 1
    if not named:
        return None
    if len(named) != 1 or not valid_site(named[0]):
        return AMBIGUOUS
    return named[0]


def snippet_sites(command):
    """The literal sites Frappe snippets in this text connect to, or None.

    None when any site-choosing call is not in a form whose site can be read off the text.
    An empty set when there are no such calls at all.
    """
    sites = set()
    for call in SITE_CALL.finditer(command):
        literal = SITE_CALL_LITERAL.match(command, call.start())
        if literal:
            sites.add(literal.group(2))
        elif not SITE_REUSE.match(command, call.start()):
            return None
    return sites


def segment_sites(segment, segments):
    """The sites one site-access segment reaches: a non-empty set, or None if unreadable.

    A bench command reaches the one site it names. A heredoc fed to `bench --site s
    console` reaches s. Anything else reaches the literal sites its snippets connect to,
    or, with none of its own, the one site the rest of the command names - the
    `bench --site s execute ...; python -c "frappe.connect()"` shape.
    """
    if segment.kind == "command" and segment.name == "bench":
        named = bench_site(segment.tokens)
        return {named} if named and named is not AMBIGUOUS else None
    owner = segment.owner
    own = snippet_sites(segment.text)
    if own is None:
        return None
    if owner is not None and owner.kind == "command" and owner.name == "bench":
        # A console heredoc reaches the bench's site and anything it connects to itself.
        named = segment_sites(owner, segments)
        return named | own if named and all(valid_site(s) for s in own) else None
    if own:
        return own if all(valid_site(s) for s in own) else None
    named = set()
    for other in segments:
        if other.kind == "command" and other.name == "bench":
            site = bench_site(other.tokens)
            if site is AMBIGUOUS:
                return None
            if site:
                named.add(site)
        elif other is not segment:
            more = snippet_sites(other.text)
            if more is None:
                return None
            named |= more
    return named if len(named) == 1 and all(valid_site(s) for s in named) else None


def assess(command, approved=None):
    """((decision, reason) or None, awaiting) for a whole command.

    deny outranks ask outranks allow, whichever segment each came from: the command is
    submitted as one unit.

    Site asks (`site_access` rules) become allows when every site they reach is listed as
    a development site or was approved this session, and none is listed as protected.
    `awaiting` is the one unlisted site an ask is waiting on - the site a PostToolUse for
    this call may record as approved. None for every other outcome, and always None for
    a protected site, which is never remembered.

    An allow covers the whole command only when every other segment is allowed too, a
    harmless companion (cd, tail, grep, ...), or input to an allowed segment, and no
    substitution is present. Anything else is left to Claude Code's own permission check.
    """
    segments = lex_command(command)
    found = [evaluate(segment) for segment in segments]
    awaiting, protected_hit = None, None

    site_asks = [i for i, f in enumerate(found)
                 if f and f[0] == "ask" and f[2] and f[2].get("site_access")]
    if site_asks:
        reached = [segment_sites(segments[i], segments) for i in site_asks]
        if all(reached):
            sites = set().union(*reached)
            development, protected = site_lists()
            pending = sorted(s for s in sites if s in protected or not (
                s in development or (approved is not None and approved(s))))
            if not pending:
                listed = sorted(sites & development)
                reason = (DEVELOPMENT_REASON if listed == sorted(sites) else SESSION_REASON) \
                    % ", ".join(sorted(sites))
                for i in site_asks:
                    # Code that writes, deletes, shells out or changes site data is not
                    # routine inspection: no allow from the hook, Claude Code decides.
                    found[i] = None if code_has_effects(segments[i]) \
                        else ("allow", reason, found[i][2])
            elif len(pending) == 1 and pending[0] not in protected:
                awaiting = pending[0]
            else:
                protected_hit = next((s for s in pending if s in protected), None)

    decided = [f for f in found if f]
    if not decided:
        return None, None
    by_segment = {id(s): f for s, f in zip(segments, found)}
    for decision in DECISION_STRENGTH:
        strongest = next((f for f in decided if f[0] == decision), None)
        if strongest is None:
            continue
        if decision == "allow" and (SUBSTITUTION.search(command) or any(
            writes_file(segment) or code_has_effects(segment) for segment in segments
        ) or any(
            f is None
            and not (segment.kind == "command" and segment.name in ALLOW_COMPANIONS)
            and not (segment.owner is not None
                     and (by_segment.get(id(segment.owner)) or ("",))[0] == "allow")
            for f, segment in zip(found, segments)
        )):
            return None, None
        reason = strongest[1]
        if decision == "ask" and awaiting:
            return ("ask", reason + AWAITING_NOTE % (awaiting, awaiting)), awaiting
        if decision == "ask" and protected_hit:
            return ("ask", reason + PROTECTED_NOTE % protected_hit), None
        return (decision, reason), None
    return decided[0][:2], None


def decide(command):
    """(decision, reason) for a whole command, or None when no rule covers it.

    The decision with no session behind it: listed development sites are relaxed, and
    every other site asks. See assess().
    """
    return assess(command)[0]


def state_dir():
    """This user's private directory of session state, or None if it cannot be trusted.

    Under the OS temp directory, never the repository. The directory name carries the uid
    where there is one, because a shared /tmp would otherwise let another user create it
    first - and a directory someone else can write is one they can write approvals into.
    """
    uid = getattr(os, "getuid", None)
    root = Path(tempfile.gettempdir()) / (
        "frappe-orchestrator-%d" % uid() if uid else "frappe-orchestrator"
    )
    try:
        root.mkdir(mode=0o700, exist_ok=True)
        info = os.lstat(root)
        if not stat.S_ISDIR(info.st_mode):
            return None
        if uid and (info.st_uid != uid() or info.st_mode & 0o077):
            return None
        sessions = root / "sessions"
        sessions.mkdir(mode=0o700, exist_ok=True)
        if not stat.S_ISDIR(os.lstat(sessions).st_mode):
            return None
        return sessions
    except OSError:
        return None


def state_file(session_id):
    """Where this session's state lives, or None when it has none it could keep."""
    if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
        return None
    sessions = state_dir()
    return sessions / ("%s.json" % session_id) if sessions else None


def read_state(path, session_id):
    """{"approved": set, "pending": dict}. Anything unreadable or malformed reads as empty.

    Empty is the safe direction: no approval means the next access asks.
    """
    empty = {"approved": set(), "pending": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return empty
    if not isinstance(data, dict) or data.get("session_id") != session_id:
        return empty
    approved, pending = data.get("approved_sites"), data.get("pending")
    if not isinstance(approved, list) or not all(valid_site(s) for s in approved):
        return empty
    if not isinstance(pending, dict) or not all(
        isinstance(k, str) and valid_site(v) for k, v in pending.items()
    ):
        return empty
    return {"approved": set(approved), "pending": dict(pending)}


@contextlib.contextmanager
def state_lock(sessions):
    """Serialise read-modify-write of session state where the platform allows it.

    Without the lock, parallel tool calls can drop each other's entries. That only ever
    loses an approval - the site asks again - so a platform without flock goes unlocked.
    """
    if fcntl is None:
        yield
        return
    with open(str(sessions / ".lock"), "a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def update_state(session_id, change):
    """Apply `change(state)` to this session's state and save it if it returns True.

    Never raises: losing session state costs a prompt, never an allow.
    """
    try:
        path = state_file(session_id)
        if path is None:
            return
        with state_lock(path.parent):
            created = not path.exists()
            state = read_state(path, session_id)
            if not change(state):
                return
            pending = list(state["pending"].items())[-MAX_PENDING:]
            body = json.dumps({
                "session_id": session_id,
                "approved_sites": sorted(state["approved"]),
                "pending": dict(pending),
            })
            handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
            try:
                with os.fdopen(handle, "w", encoding="utf-8") as out:
                    out.write(body)
                os.replace(temporary, str(path))
            except BaseException:
                with contextlib.suppress(OSError):
                    os.unlink(temporary)
                raise
        if created:
            sweep_stale_state(path.parent)
    except Exception:
        pass


def sweep_stale_state(sessions):
    """Remove session files untouched for a week. Run once per new session, not per call."""
    cutoff = time.time() - STALE_STATE_SECONDS
    try:
        for path in sessions.glob("*.json"):
            with contextlib.suppress(OSError):
                if path.stat().st_mtime < cutoff:
                    path.unlink()
    except OSError:
        pass


def session_approvals(session_id):
    """approved(site) for this session, reading its state at most once. Never raises."""
    cache = []

    def approved(site):
        try:
            if not cache:
                path = state_file(session_id)
                cache.append(read_state(path, session_id)["approved"] if path else set())
            return site in cache[0]
        except Exception:
            return False

    return approved


def await_approval(payload, site):
    """Note that this tool call asked about `site`. A note, never an approval."""
    tool_use_id = payload.get("tool_use_id")
    if not isinstance(tool_use_id, str) or not TOOL_USE_ID.match(tool_use_id):
        return

    def note(state):
        state["pending"].pop(tool_use_id, None)
        state["pending"][tool_use_id] = site
        return True

    update_state(payload.get("session_id"), note)



def record_approval(payload):
    """PostToolUse: the command ran, so the site its ask was waiting on is now approved.

    Only a pending note for this exact tool call, naming the site this exact command
    reaches, is promoted. A call the user rejected never runs, never gets a PostToolUse,
    and leaves its note pending - which approves nothing. Never raises and never writes
    output.
    """
    try:
        command = read_command(payload)
        tool_use_id = payload.get("tool_use_id")
        if command is None or not isinstance(tool_use_id, str):
            return
        _outcome, awaiting = assess(command)
        if awaiting is None:
            return

        def promote(state):
            if tool_use_id not in state["pending"]:
                return False
            if state["pending"].pop(tool_use_id) == awaiting:
                state["approved"].add(awaiting)
            return True

        update_state(payload.get("session_id"), promote)
    except Exception:
        pass


# --------------------------------------------------------------------------
# File edits
# --------------------------------------------------------------------------

EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})

CONFIG_EDIT_REASON = (
    "This edits frappe-orchestrator's own configuration (%s), which decides which sites "
    "run without a prompt and which models run. Approve only if you asked for it."
)
ACTIVE_WRITER_REASON = (
    "A delegated %s run (pid %s) is still active in %s, and editing the same tree now "
    "would race it. Wait for its result, or stop it with `%s stop --cwd %s` and then "
    "inspect `git status` before continuing."
)


def _within(path, root):
    root = root.rstrip(os.sep)
    return path == root or path.startswith(root + os.sep)


def edit_decision(payload):
    """(decision, reason) for an Edit/Write call, or None to leave it to Claude Code."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not isinstance(path, str) or not path.strip():
        return None
    base = payload.get("cwd") if isinstance(payload.get("cwd"), str) else os.getcwd()
    target = os.path.realpath(os.path.join(base, os.path.expanduser(path)))

    config = os.path.realpath(str(config_dir()))
    if _within(target, config):
        return "ask", CONFIG_EDIT_REASON % target

    # Only consulted when the registry of delegated runs is non-empty, so an ordinary edit
    # costs one directory listing. A fault here is reported, not turned into a block: it
    # cannot authorise anything, and blocking every edit everywhere is worse.
    try:
        sys.path.insert(0, str(SCRIPTS))
        import orchlib
        writers = orchlib.active_writers()
    except Exception as exc:   # pragma: no cover - reported, never silent
        print("frappe-orchestrator: active-run check failed: %s" % exc, file=sys.stderr)
        return None
    for proc in writers:
        if proc.get("cwd") and _within(target, proc["cwd"]):
            return "deny", ACTIVE_WRITER_REASON % (
                proc.get("mode"), proc.get("pid"), proc["cwd"], SCRIPTS / "orch", proc["cwd"])
    return None


def main():
    """Read one payload, emit one decision, or block. Raises only SystemExit."""
    payload = read_payload()
    if payload.get("hook_event_name") == "PostToolUse":
        record_approval(payload)
        return

    if payload.get("tool_name") in EDIT_TOOLS:
        try:
            outcome = edit_decision(payload)
        except Exception as exc:
            fail_closed(("%s: %s" % (type(exc).__name__, exc))[:400])
            return
        if outcome:
            emit(*outcome)
        return

    command = read_command(payload)
    if command is None:
        return

    try:
        outcome, awaiting = assess(
            command, session_approvals(payload.get("session_id"))
        )
    except Exception as exc:
        # A command is in hand and is about to run unless this hook stops it, and the
        # hook cannot say whether a boundary applies. Not an allow, and not an ask either.
        detail = ("%s: %s" % (type(exc).__name__, exc))[:400]
        fail_closed(detail)
        return   # unreachable; kept so a future edit to fail_closed cannot fall through

    if outcome is None:
        return

    if awaiting:
        await_approval(payload, awaiting)

    try:
        emit(*outcome)
    except Exception as exc:
        detail = "the decision could not be written - %s: %s" % (type(exc).__name__, exc)
        fail_closed(detail[:400])


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise   # fail_closed's blocking status, on its way out
    except BaseException as exc:
        # main() is written to raise nothing else. An uncaught traceback exits 1, which
        # Claude Code treats as non-blocking before running the command.
        fail_closed(("%s: %s" % (type(exc).__name__, exc))[:400])
