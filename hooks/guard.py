#!/usr/bin/env python3
"""PreToolUse guard: deny blanket staging and bare agent runs, ask before pushes and
live-site execution.

Reads a PreToolUse payload on stdin. Prints a JSON permission decision when a rule
matches, and prints nothing otherwise. A payload carrying no Bash command is allowed -
there is nothing there to decide about. A failure *inside* this hook is not allowed
through. Once a command has been extracted, a fault in this hook blocks it: Claude Code
treats a crashed hook as a *non-blocking* error and runs the command anyway, so a
traceback here would authorise exactly what the hook failed to look at.

The rules themselves are not here. They live in config/command-boundaries.json, which
scripts/delegate reads as well - the same boundaries have to hold whether Claude runs a
command through the Bash tool, where this hook sees it, or a delegated agent runs it in
its own process, where this hook sees nothing. Two hand-maintained copies of one rule set
is how those two layers came to disagree. This file owns the matching, not the rules.
"""

import json
import os
import re
import shlex
import sys
from pathlib import Path

BOUNDARIES = Path(__file__).resolve().parent.parent / "config" / "command-boundaries.json"

SEPARATORS = re.compile(r"&&|\|\||[;|&\n]")

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
    "blanket-staging": (
        "Do not stage with `git add .` or `git add -A` - it sweeps in unrelated work. Run "
        "`git status --porcelain` to see what changed, then stage only the files this task "
        "created or changed, by path."
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
GUARDED_PROGRAMS = frozenset({"git", "bench", "mysql", "mariadb", "opencode", "codex"})

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

# What this hook can decide. `null` is a decision too - the data stating that a rule is
# not the hook's to enforce - and is the only other value accepted.
HOOK_DECISIONS = frozenset({"ask", "deny"})


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
        return "%s: hook decision %r is not ask, deny or null" % (name, decision)
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


def read_command():
    """The Bash command in a PreToolUse payload, or None. Never raises.

    None means there is nothing here to decide about: no payload, no `tool_input`, no
    `command`, or a `command` that is not a usable string. That case passes through, which
    is this hook's existing protocol for input it does not recognise.

    It is deliberately not the same as "deciding failed". Every failure this function
    swallows happened before a command was in hand, so there is nothing it could have
    authorised. A failure with a command in hand is main()'s to handle, and is not an
    allow.
    """
    try:
        payload = json.load(sys.stdin)
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(payload, dict):
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    return command


def decide(command):
    """(decision, reason) for a whole command, or None when no rule covers it.

    A deny outranks an ask whichever segment each came from: the command is submitted as
    one unit, so the strongest decision any part of it earns is the decision for all of
    it. Among equals the first segment wins.
    """
    matches = [m for m in (check(segment) for segment in SEPARATORS.split(command)) if m]
    if not matches:
        return None
    return next((m for m in matches if m[0] == "deny"), matches[0])


def main():
    """Read one payload, emit one decision, or block. Raises only SystemExit."""
    command = read_command()
    if command is None:
        return

    try:
        outcome = decide(command)
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
