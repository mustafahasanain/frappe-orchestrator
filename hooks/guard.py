#!/usr/bin/env python3
"""PreToolUse guard: deny blanket staging, ask before pushes and live-site execution.

Reads a PreToolUse payload on stdin. Prints a JSON permission decision when a rule
matches, and prints nothing otherwise. Anything it does not recognise is allowed.
"""

import json
import re
import shlex
import sys

SEPARATORS = re.compile(r"&&|\|\||[;|&\n]")

# Options taking a separate argument, so the token after them is not the subcommand.
GIT_OPTS_WITH_ARG = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"}
BENCH_OPTS_WITH_ARG = {"--site", "-s"}

BLANKET_ADD = {".", "-A", "--all"}
SITE_SUBCOMMANDS = {"console", "mariadb", "execute", "run"}
DATABASE_CLIENTS = {"mysql", "mariadb"}
FRAPPE_CONNECTION = re.compile(r"frappe\.(init|connect|db|get_doc|get_all|get_list)\b")

PUSH_REASON = (
    "Pushing is never automatic. Confirm the target branch and remote with the user "
    "first, state what will be pushed, and continue only once they agree."
)

ADD_REASON = (
    "Do not stage with `git add .` or `git add -A` - it sweeps in unrelated work. Run "
    "`git status --porcelain` to see what changed, then stage only the files this task "
    "created or changed, by path."
)

SITE_REASON = (
    "This runs against a live site database or a running Frappe instance. Confirm with "
    "the user which single site to target before continuing, and do not repeat it across "
    "other sites. If you only need a DocType definition or other committed configuration, "
    "read that file in the working tree instead of querying a site."
)


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


def check(segment):
    """Return (decision, reason) if a rule matches this command segment, else None."""
    tokens = split_tokens(segment)
    name = program(tokens)

    if name == "git":
        sub = subcommand(tokens, GIT_OPTS_WITH_ARG)
        if sub == "push":
            return "ask", PUSH_REASON
        if sub == "add" and BLANKET_ADD.intersection(tokens):
            return "deny", ADD_REASON

    if name == "bench":
        if subcommand(tokens, BENCH_OPTS_WITH_ARG) in SITE_SUBCOMMANDS or "--site" in tokens:
            return "ask", SITE_REASON

    if name in DATABASE_CLIENTS:
        return "ask", SITE_REASON

    # Catches inline snippets too: python -c "...", heredoc bodies, bench execute payloads.
    if FRAPPE_CONNECTION.search(segment):
        return "ask", SITE_REASON

    return None


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


main()
