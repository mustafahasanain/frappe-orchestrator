#!/usr/bin/env python3
"""PreToolUse guard: deny blanket staging and bare agent runs, ask before pushes and
live-site execution.

Reads a PreToolUse payload on stdin. Prints a JSON permission decision when a rule
matches, and prints nothing otherwise. Anything it does not recognise is allowed.

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
# ever been about. If the boundary data cannot be read there are no rules to apply, and
# silently enforcing nothing is the one failure mode this hook must not have. Asking on
# these programs turns a total, invisible lapse into a visible degraded one.
GUARDED_PROGRAMS = frozenset({"git", "bench", "mysql", "mariadb", "opencode", "codex"})

UNREADABLE_REASON = (
    "The command boundaries could not be read from %s, so none of them are being "
    "enforced right now, and this command is one they cover. Check that file before "
    "continuing - a hook that cannot read its rules is not protecting anything."
) % BOUNDARIES


def load_rules():
    """Rules this hook enforces, in precedence order. None if the data is unusable."""
    try:
        rules = json.loads(BOUNDARIES.read_text())["rules"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    usable = []
    for rule in rules:
        if not isinstance(rule, dict) or not rule.get("hook"):
            continue
        match = rule.get("match") or {}
        if match.get("kind") == "segment_text":
            # Word-bounded so `frappe.db` does not fire on `frappe.database`. Built here
            # rather than stored as a regex: the data says which identifiers matter, and
            # this is the one engine that expresses that as a pattern.
            idents = match.get("identifiers") or []
            rule = dict(rule, _pattern=re.compile(
                "(?:%s)\\b" % "|".join(re.escape(i) for i in idents)
            ))
        usable.append(rule)
    return usable


RULES = load_rules()


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
        return ("ask", UNREADABLE_REASON) if program(
            split_tokens(segment)
        ) in GUARDED_PROGRAMS else None

    rule = match_rule(segment)
    if rule is None:
        return None
    return rule["hook"], REASONS.get(rule["name"]) or rule.get("intent", "")


def main():
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return

    command = (payload.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return

    matches = [m for m in (check(s) for s in SEPARATORS.split(command)) if m]
    if not matches:
        return

    decision, reason = next((m for m in matches if m[0] == "deny"), matches[0])
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


if __name__ == "__main__":
    main()
