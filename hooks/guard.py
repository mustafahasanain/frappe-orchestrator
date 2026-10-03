#!/usr/bin/env python3
"""PreToolUse guard: deny blanket staging and bare agent runs, ask before pushes and
live-site execution, and let the routine end-of-task bench operations run unprompted.

Reads a PreToolUse payload on stdin. Prints a JSON permission decision when a rule
matches, and prints nothing otherwise. A payload carrying no Bash command is allowed -
there is nothing there to decide about. A failure *inside* this hook is not allowed
through. Once a command has been extracted, a fault in this hook blocks it: Claude Code
treats a crashed hook as a *non-blocking* error and runs the command anyway, so a
traceback here would authorise exactly what the hook failed to look at.

Site access is the one place the decision depends on more than the command. A command
whose site rules all reach one explicitly named site is allowed when that site ends in
`.local` - the plugin's development-site convention - or when the user approved a command
reaching that exact site earlier in the same Claude Code session. That approval is
recorded from the PostToolUse payload for the same tool call, which Claude Code sends only
once the command has run: an ask is not an approval, and the user may have said no.

The rules themselves are not here. They live in config/command-boundaries.json, which
scripts/delegate reads as well - the same boundaries have to hold whether Claude runs a
command through the Bash tool, where this hook sees it, or a delegated agent runs it in
its own process, where this hook sees nothing. Two hand-maintained copies of one rule set
is how those two layers came to disagree. This file owns the matching, not the rules.
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

BOUNDARIES = Path(__file__).resolve().parent.parent / "config" / "command-boundaries.json"

SEPARATORS = re.compile(r"&&|\|\||[;|&\n]")

# `2>&1` and friends. The `&` in them is not a separator, and splitting on it leaves a
# stray `1` segment that no rule covers - which is enough to cancel an allow.
FD_DUPLICATION = re.compile(r"\d*>&\d*-?")

# Segments that may sit beside an allowed operation without cancelling it: changing into
# the bench directory, and reading the operation's output. None of them acts on anything.
ALLOW_COMPANIONS = frozenset({"cd", "tail", "head", "grep"})

# Options taking a separate argument, so the token after them is not the subcommand.
# Matching mechanics, not rules: which token is the subcommand is a fact about each CLI's
# argument parser, and the dispatcher's glob patterns have no equivalent question to ask.
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

# What the agent is told when a rule fires, keyed by rule name. Instructions, not
# descriptions: each names the corrective action, in the hook's own voice. The data file
# carries each rule's intent, which is what a reader needs; this is what the blocked agent
# needs, which is a different text for a different audience. A rule with no entry here
# falls back to its intent rather than failing at runtime - and the test suite fails by
# name, so the gap is loud in the one place that can afford to be.
REASONS = {
    "push": (
        "Pushing is never automatic. Confirm the target branch and remote with the user "
        "first, state what will be pushed, and continue only once they agree."
    ),
    "commit": (
        "Commits need the user's approval. If you have not already shown the user the "
        "finished work and this exact message and file list, and had them approve it, stop "
        "and do that first. The message is one short `feat: <summary>` line with no "
        "Co-Authored-By or other attribution."
    ),
    "blanket-staging": (
        "Do not stage with `git add .` or `git add -A` - it sweeps in unrelated work. Run "
        "`git status --porcelain` to see what changed, then stage only the files this task "
        "created or changed, by path."
    ),
    "discard-tracked-changes": (
        "`git reset --hard` (and --merge/--keep) throws away every uncommitted change in "
        "the tree, not only the ones belonging to this task, and unstaged work has no "
        "reflog entry to recover from. Run `git status --porcelain` and confirm with the "
        "user what may be discarded. To move HEAD without touching file contents use "
        "`git reset --soft`; to unstage, `git reset <path>`."
    ),
    "discard-pathspec-changes": (
        "This overwrites working-tree files from the index or a commit, and unstaged "
        "content in those paths is not recoverable afterwards. Confirm with the user "
        "which files may be reverted, then revert them by path rather than with `.`. To "
        "see what would be lost first, run `git diff -- <path>`."
    ),
    "discard-worktree": (
        "`git restore` overwrites working-tree files and `git clean` deletes untracked "
        "files, which Git keeps no copy of. Confirm with the user which paths may be "
        "discarded and name them explicitly. To find out what is there without removing "
        "anything, run `git status --porcelain`."
    ),
    "drop-stash": (
        "This deletes stashed work permanently, and a stash is where interrupted work was "
        "put to keep it safe. Run `git stash list` and `git stash show -p` first, and "
        "confirm with the user before dropping anything. To use a stash without "
        "destroying it, `git stash apply` leaves the entry in place."
    ),
    "force-branch-ref": (
        "This deletes an unmerged branch or moves an existing branch onto another commit, "
        "abandoning commits nothing else points at. Confirm the branch and the target with "
        "the user first. `git branch -d` deletes only what is already merged, and Git "
        "refuses when it is not - use it instead of `-D` unless the loss is intended."
    ),
    "expire-recovery-refs": (
        "The reflog is what makes a bad reset or a bad rebase survivable, and this drops it "
        "along with the objects it keeps reachable. Do not run it to tidy up. If a "
        "repository genuinely needs pruning, that is the user's decision to make with the "
        "reflog in front of them."
    ),
    "rewrite-repository-history": (
        "This rewrites commits or writes a ref directly, with none of the checks a "
        "porcelain command applies. Confirm the operation and its scope with the user "
        "before continuing. To read the same data without changing it, use `git log`, "
        "`git rev-parse` or `git show-ref`."
    ),
    "recursive-delete": (
        "A recursive delete takes everything below the path, tracked or not, and Git holds "
        "no copy of untracked content. Confirm the path with the user, or delete the "
        "specific files this task is responsible for by name. To see what would go, list "
        "the tree first with `find <path> -maxdepth 2`."
    ),
    "mass-delete": (
        "`find ... -delete` removes every path the traversal matched, and a traversal "
        "usually reaches wider than intended. Run the same search without `-delete` first, "
        "read the list, and then remove what belongs to this task by name."
    ),
    "overwrite-file-contents": (
        "shred, truncate and dd overwrite bytes in place, with no staging step and nothing "
        "to restore an untracked file from. None of them is the tool for editing source: "
        "edit the file, or write the intended contents with a normal editor operation. If "
        "the byte-level operation really is what is wanted, the user should confirm the "
        "exact target path."
    ),
    "asset-build": (
        "Asset build: touches no site, so it runs without a prompt. Check the output for a "
        "build failure before treating the assets as rebuilt."
    ),
    "destructive-site-operation": (
        "This destroys or overwrites site data, resets credentials or sessions, or opens a "
        "raw database shell, and none of that is undone by running something else. It "
        "asks on every site, development sites included, and an earlier approval of the "
        "site does not cover it. Confirm the operation and the single target site with the "
        "user before continuing."
    ),
    "site-named": (
        "This runs against a live site database or a running Frappe instance. Confirm with "
        "the user which single site to target before continuing, and do not repeat it across "
        "other sites. If you only need a DocType definition or other committed configuration, "
        "read that file in the working tree instead of querying a site."
    ),
    "site-unnamed": (
        "This bench subcommand acts on a site, and no site is named on the command line. "
        "That does not make it site-free: bench resolves one from configuration instead - "
        "`default_site` in common_site_config.json, then currentsite.txt - so it will act on "
        "whichever site the bench was last pointed at, which nobody chose for this task. "
        "Name the site explicitly: `bench --site <site> <subcommand>`, using a site that the "
        "project's docs/ai-context/OPERATIONS.md or the user identifies as a development "
        "site."
    ),
    "database-client": (
        "This runs against a live database directly. Confirm with the user which single "
        "site or database to target before continuing. If you only need committed "
        "configuration, read that file in the working tree instead."
    ),
    "frappe-connection": (
        "This opens a connection to a live site. Confirm with the user which single site to "
        "target before continuing, and do not repeat it across other sites. If you only need "
        "a DocType definition or other committed configuration, read that file in the "
        "working tree instead of querying a site."
    ),
    "bare-agent-run": None,   # filled in below - both agent rules share one text
    "bare-agent-exec": None,
}

DELEGATE = os.path.join(os.environ.get("CLAUDE_PLUGIN_ROOT", ""), "scripts", "delegate")

AGENT_REASON = (
    "Coding agents run through the dispatcher, not directly. Use `" + DELEGATE + " "
    "--agent <opencode|codex> --mode <implement|review|test|onboard> --tier <TIER> "
    "--cwd <repository root> [--model \"<name from the routing file>\"]` with the "
    "brief on stdin. The "
    "dispatcher supplies the model and timeout from central routing, the permission "
    "policy that holds a delegated run inside the same boundaries enforced here, and "
    "the structured result contract. A bare invocation skips all three."
)
REASONS["bare-agent-run"] = AGENT_REASON
REASONS["bare-agent-exec"] = AGENT_REASON

# Last resort, and deliberately not a second copy of the rules: the programs any rule has
# ever been about. If the boundary data cannot be loaded there are no rules to apply, and
# silently enforcing nothing is the one failure mode this hook must not have. Asking on
# these programs turns a total, invisible lapse into a visible degraded one.
GUARDED_PROGRAMS = frozenset({
    "git", "bench", "mysql", "mariadb", "opencode", "codex",
    # The destructive filesystem programs. Listed for the same reason as the rest: with
    # the rule data unloadable there is nothing to narrow `rm` down to its recursive
    # forms, and asking on every `rm` for as long as the file is broken is the failure
    # this list exists to prefer.
    "rm", "find", "shred", "truncate", "dd",
})

# The match kinds this hook implements, and the fields each needs in order to be matched
# at all. Checked when the data is loaded, because "unreadable" and "unusable" amount to
# the same thing here: a rule set this file cannot match enforces nothing, and enforcing
# nothing while looking installed is the failure this hook must not have. Reading the file
# successfully was never the property that mattered.
MATCH_FIELDS = {
    "segment_text": {"lists": ("identifiers",)},
    "program": {"lists": ("programs",)},
    "program_option": {"names": ("program",), "lists": ("options",)},
    "program_subcommand": {"names": ("program",), "lists": ("subcommands",)},
}

# Not required by any kind, but matched against wherever they appear, so they are checked
# on the same terms as the required ones.
OPTIONAL_LISTS = ("any_argument", "unless_flags")

# What this hook can decide. `allow` is an explicit decision, not the absence of one: it
# skips Claude Code's own permission prompt, where printing nothing leaves that prompt in
# place. `null` is a decision too - the data stating that a rule is not the hook's to
# enforce - and is the only other value accepted.
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


def split_tokens(segment):
    try:
        return shlex.split(segment)
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


def rule_matches(rule, segment, tokens, name):
    """Does this command segment fall under this rule?"""
    match = rule["match"]
    kind = match.get("kind")

    if kind == "segment_text":
        # Runs on the raw segment, so it also catches python -c "..." payloads and
        # heredoc bodies, where there is no program name to look at.
        return bool(rule["_pattern"].search(segment))

    if kind == "program":
        return name in match.get("programs", ())

    if name != match.get("program"):
        return False

    if kind == "program_option":
        return any(option in tokens for option in match.get("options", ()))

    if kind == "program_subcommand":
        # An informational flag means the CLI prints text and exits, so there is nothing
        # to route anywhere. Whole tokens, never a substring of the segment: a brief is an
        # argument, so `codex exec "explain the --help output"` mentions the flag without
        # carrying it, and a substring test would exempt a real run for quoting a word.
        # Only rules that declare it get the exemption - `--help` is inert rather than
        # suppressing for an interpreter, which ignores the extra argument and runs the
        # snippet anyway.
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


def match_rule(segment):
    """The first rule this segment falls under, or None. Data order is precedence."""
    if RULES is None:
        return None
    tokens = split_tokens(segment)
    name = program(tokens)
    for rule in RULES:
        if rule_matches(rule, segment, tokens, name):
            return rule
    return None


def check(segment):
    """Return (decision, reason) if a rule matches this command segment, else None."""
    if RULES is None:
        # Degraded: no rules loaded. Ask on the programs the rules are about rather than
        # enforcing nothing at all.
        return ("ask", degraded_reason()) if program(
            split_tokens(segment)
        ) in GUARDED_PROGRAMS else None

    rule = match_rule(segment)
    if rule is None:
        return None
    return rule["hook"], REASONS.get(rule["name"]) or rule.get("intent", "")


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
# Site environments and per-session approval
#
# Which rules this applies to is data - `site_access` in the boundary file. What a site
# name means, and what this session has approved, is enforcement, and lives here.
# --------------------------------------------------------------------------

# A plain hostname: dot-separated labels of letters, digits and inner hyphens. Anything
# else - a variable, a glob, a brace list, a path - is not something this hook can say
# which site it means, so it reaches no site that could be relaxed.
SITE_NAME = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\Z"
)
DEVELOPMENT_SUFFIX = ".local"
SITE_OPTIONS = ("--site", "-s")

# Calls that choose which site a snippet is connected to. A literal first argument, or a
# literal `site=`, is a site this hook can name; any other form of these calls is a site it
# cannot, and the snippet then reaches no site that could be relaxed. `frappe.connect()`
# with no arguments reuses the site already chosen, so it names nothing new.
SITE_CALL = re.compile(r"\bfrappe\.(?:init_site|init|connect)\b")
SITE_CALL_LITERAL = re.compile(
    r"""frappe\.(?:init_site|init|connect)\(\s*(?:site\s*=\s*)?\\?(['"])([^'"\\\s]+)\\?\1\s*[,)]"""
)
SITE_REUSE = re.compile(r"frappe\.connect\(\s*\)")

# Command and process substitution run a command of their own wherever they sit - inside
# double quotes, inside an unquoted heredoc, inside an argument to `cd`. None of the
# matching here looks inside one, so no command carrying one is allowed by this hook.
SUBSTITUTION = re.compile(r"\$\(|`|<\(|>\(")

# A heredoc operator and its delimiter, as bash reads them. Only consulted on a line that
# has already been shown to hold no quoted `<`, no backslash and no unbalanced quote, so
# every match is a real operator rather than text that happens to look like one.
HEREDOC = re.compile(
    r"(?<!<)<<(?!<)(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2(?=[\s;&|<>()]|\Z)"
)

# Claude Code's session id is a UUID. Anything else - including the `served:` form, which
# can fall back to a shared placeholder - gets no stored approvals at all.
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
TOOL_USE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")

STALE_STATE_SECONDS = 7 * 24 * 3600
MAX_PENDING = 32

DEVELOPMENT_REASON = (
    "Routine access to %s, which ends in .local - this plugin's convention for a "
    "development site - so it runs without a prompt. Keep to the one site the task "
    "resolved, and stop for the user before a migration that may drop or transform data. "
    "Destructive site operations, any other site, and a command that does not name its "
    "site still ask."
)
SESSION_REASON = (
    "Routine access to %s, which the user approved earlier in this Claude Code session, "
    "so it runs without a prompt. That approval covers this exact site until the session "
    "ends. Destructive site operations, any other site, and a command that does not name "
    "its site still ask."
)
AWAITING_NOTE = (
    " If the user approves and the command runs, routine access to %s runs without a "
    "prompt for the rest of this Claude Code session; other sites still ask."
)

AMBIGUOUS = object()   # a bench command that names a site option, but not one usable site


def valid_site(site):
    """A single site name this hook can compare exactly. `all` is every site, not one."""
    return (
        isinstance(site, str)
        and len(site) <= 253
        and site.lower() != "all"
        and bool(SITE_NAME.match(site))
    )


def is_development_site(site):
    """A site whose name ends in `.local`. The plugin's convention; nothing else counts."""
    return valid_site(site) and site.lower().endswith(DEVELOPMENT_SUFFIX)


def bench_site(tokens):
    """The one site a bench command names, None if it names none, AMBIGUOUS otherwise.

    Every spelling of the option anywhere in the command counts, so a second `--site`, a
    missing value, or a value that is not a plain site name leaves nothing to relax.
    """
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
    """The literal sites Frappe snippets in this command connect to, or None.

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


def command_site(command, segments):
    """The one site this whole command reaches, or None.

    Every bench command in it counts, relaxed by a rule or not, and every site a snippet
    connects to. A second site, an unreadable one, or none at all gives None.
    """
    sites = set()
    for segment in segments:
        tokens = split_tokens(segment)
        if program(tokens) == "bench":
            named = bench_site(tokens)
            if named is AMBIGUOUS:
                return None
            if named:
                sites.add(named)
    from_snippets = snippet_sites(command)
    if from_snippets is None:
        return None
    sites |= from_snippets
    if len(sites) != 1:
        return None
    site = sites.pop()
    return site if valid_site(site) else None


def reaches(segment, site):
    """Does this site-access segment reach exactly `site`?

    A bench segment has to name it itself - an unnamed bench command reaches whichever
    site configuration picks. A snippet segment reaches the command's site, which
    command_site() has already reduced to one.
    """
    tokens = split_tokens(segment)
    if program(tokens) == "bench":
        return bench_site(tokens) == site
    return True


def heredocs(line, first):
    """[(owner, delimiter, strip_tabs)] for the heredocs a line opens, in order.

    `owner` indexes the segment the operator sits in, the line's segments being numbered
    from `first`. A line this cannot read with certainty opens none, so its following lines
    stay ordinary command segments.
    """
    if "<<" not in line or "\\" in line:
        return []
    lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        words = list(lexer)
    except ValueError:
        return []
    # A `<` inside a word was quoted: text that looks like an operator and is not one.
    if any("<" in word and not set(word) <= set("();<>|&") for word in words):
        return []
    opened = []
    for offset, part in enumerate(p for p in SEPARATORS.split(line) if p.strip()):
        for found in HEREDOC.finditer(part):
            opened.append((first + offset, found.group(3), found.group(1) == "-"))
    return opened


def split_segments(command):
    """(segments, owners): the command's segments, and for each the index of the segment
    whose heredoc it is the body of, or None.

    A heredoc body is still split and matched like any other text, so a rule still sees
    it. What it is not is a command of its own: it is input to the segment that opened it.
    """
    segments, owners = [], []
    lines = FD_DUPLICATION.sub(" ", command).split("\n")
    i = 0
    while i < len(lines):
        first = len(segments)
        for part in SEPARATORS.split(lines[i]):
            if part.strip():
                segments.append(part)
                owners.append(None)
        opened = heredocs(lines[i], first)
        i += 1
        for owner, delimiter, strip_tabs in opened:
            while i < len(lines):
                text = lines[i]
                i += 1
                if (text.lstrip("\t") if strip_tabs else text) == delimiter:
                    break
                for part in SEPARATORS.split(text):
                    if part.strip():
                        segments.append(part)
                        owners.append(owner)
    return segments, owners


def assess(command, approved=None):
    """((decision, reason) or None, awaiting) for a whole command.

    deny outranks ask outranks allow, whichever segment each came from: the command is
    submitted as one unit, so the strongest decision any part of it earns is the decision
    for all of it. Among equals the first segment wins.

    An ask from a `site_access` rule becomes an allow when every such ask in the command
    reaches the one site the whole command reaches, and that site is a development site
    or `approved(site)` says the user approved it this session. Any other rule's decision
    is untouched, so a destructive operation still asks and a deny still denies.

    `awaiting` is the protected site an ask is waiting on - the site a PostToolUse for
    this call may record as approved. None for every other outcome.

    An allow covers the whole command only when every other segment is either allowed too,
    one of ALLOW_COMPANIONS, or the body of an allowed segment's heredoc, and the command
    carries no substitution. Anything else is left to Claude Code's own permission check:
    an allow for `bench build` must not wave through whatever was chained after it.
    """
    segments, owners = split_segments(command)
    matches = [check(segment) for segment in segments]
    awaiting = None

    site_asks = [
        i for i, m in enumerate(matches)
        if m and m[0] == "ask" and (match_rule(segments[i]) or {}).get("site_access")
    ]
    if site_asks:
        site = command_site(command, segments)
        if site is not None and all(reaches(segments[i], site) for i in site_asks):
            if is_development_site(site):
                granted = DEVELOPMENT_REASON % site
            elif approved is not None and approved(site):
                granted = SESSION_REASON % site
            else:
                granted, awaiting = None, site
            if granted:
                for i in site_asks:
                    matches[i] = ("allow", granted)

    decided = [m for m in matches if m]
    if not decided:
        return None, None
    for decision in DECISION_STRENGTH:
        strongest = next((m for m in decided if m[0] == decision), None)
        if strongest is None:
            continue
        if decision == "allow" and (SUBSTITUTION.search(command) or any(
            m is None
            and program(split_tokens(segment)) not in ALLOW_COMPANIONS
            and (owner is None or matches[owner] is None)
            for m, segment, owner in zip(matches, segments, owners)
        )):
            return None, None
        if decision == "ask" and awaiting:
            return (decision, strongest[1] + AWAITING_NOTE % awaiting), awaiting
        return strongest, None
    return decided[0], None


def decide(command):
    """(decision, reason) for a whole command, or None when no rule covers it.

    The decision with no session behind it: development sites are relaxed, and every
    other site asks. See assess().
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
    output: the command has already run, and nothing here can change that.
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


def main():
    """Read one payload, emit one decision, or block. Raises only SystemExit."""
    payload = read_payload()
    if payload.get("hook_event_name") == "PostToolUse":
        record_approval(payload)
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
        # hook has just established that it cannot say whether a boundary applies. Not an
        # allow, and not an ask either: asking hands that question to someone with
        # strictly less information than the code that failed to answer it, and an
        # approved-anyway command is the same outcome as never having checked.
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
        # A decision was reached and could not be delivered. For an ask or a deny that is
        # indistinguishable, at the far end, from no decision at all - so it blocks rather
        # than returning, which is what this used to do.
        detail = "the decision could not be written - %s: %s" % (type(exc).__name__, exc)
        fail_closed(detail[:400])


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise   # fail_closed's blocking status, on its way out
    except BaseException as exc:
        # main() is written to raise nothing else. Kept because the cost of being wrong is
        # an uncaught traceback, which exits 1, which Claude Code reports as a
        # non-blocking error before running the command. BaseException rather than
        # Exception for the same reason: a hook killed mid-evaluation has not evaluated
        # anything, and exit 130 is as non-blocking as exit 1.
        fail_closed(("%s: %s" % (type(exc).__name__, exc))[:400])
