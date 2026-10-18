#!/usr/bin/env python3
"""Agent lifecycle, failure classification and fallback safety in scripts/delegate.

    python3 tests/test_lifecycle.py

Every case runs the real dispatcher against a stub `opencode` or `codex` in a temporary
git repository, with all plugin state confined to a scratch directory. No real agent CLI,
no network, no provider usage.

The cases that matter most (audit BUG-01, incident H-1): a dispatcher stopped by SIGTERM,
SIGHUP or SIGINT - or killed outright with SIGKILL - must not leave an agent editing the
tree, and a second writer must not start while one is alive.
"""

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DELEGATE = ROOT / "scripts" / "delegate"
sys.path.insert(0, str(ROOT / "scripts"))
import orchlib  # noqa: E402

# A stub agent that edits a file every 0.1 s forever, and starts a grandchild that does
# the same - the shape of an OpenCode run with a shell tool call in flight.
EDITING_STUB = r"""#!/usr/bin/env python3
import os, subprocess, sys, time
target = os.path.join(os.environ["PWD"], "edited.txt")
subprocess.Popen([sys.executable, "-c", '''
import time, os
t = os.path.join(os.environ["PWD"], "grandchild.txt")
while True:
    open(t, "a").write("g"); time.sleep(0.1)
'''])
while True:
    with open(target, "a") as f:
        f.write("x\n")
    time.sleep(0.1)
"""


# The harder shape: besides an ordinary grandchild, one that cleared its environment (no
# run marker; findable only through the agent's process group) and one that left the
# group with setsid (findable only through the marker). Each records its pid.
ESCAPING_STUB = r"""#!/usr/bin/env python3
import os, subprocess, sys, time
here = os.environ["PWD"]
writer = (
    "import os, sys, time\n"
    "t = sys.argv[1]\n"
    "open(t + '.pid', 'w').write(str(os.getpid()))\n"
    "while True:\n"
    "    open(t, 'a').write('w'); time.sleep(0.05)\n"
)
subprocess.Popen([sys.executable, "-c", writer, os.path.join(here, "plain.txt")])
subprocess.Popen([sys.executable, "-c", writer, os.path.join(here, "no-marker.txt")],
                 env={"PATH": "/usr/bin:/bin"})
subprocess.Popen([sys.executable, "-c", writer, os.path.join(here, "own-session.txt")],
                 start_new_session=True)
main = os.path.join(here, "agent.txt")
open(main + ".pid", "w").write(str(os.getpid()))
while True:
    with open(main, "a") as f:
        f.write("x")
    time.sleep(0.05)
"""
ESCAPING_FILES = ("agent.txt", "plain.txt", "no-marker.txt", "own-session.txt")


def stub_script(body):
    return "#!/usr/bin/env python3\nimport sys\n" + body


class Env:
    def __init__(self, tmp):
        self.tmp = Path(tmp)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.state = self.tmp / "state"
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(self.repo)] + args, check=True)
        (self.repo / "app.py").write_text("print('hi')\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "app.py"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "init"], check=True)
        self.env = dict(os.environ, PATH="%s:/usr/bin:/bin" % self.bin,
                        FRAPPE_ORCHESTRATOR_STATE=str(self.state),
                        FRAPPE_ORCHESTRATOR_CONFIG=str(self.tmp / "config"),
                        CODEX_HOME=str(self.tmp / "codex"))

    def stub(self, name, body):
        # Every stub answers the catalog query the dispatcher makes before a run, so the
        # stub model counts as offered; the body only runs for the real invocation.
        lines = body.split("\n", 1)
        catalog = ("import sys as _s\nif _s.argv[1:2] == ['models'] or _s.argv[1:3] == "
                   "['debug', 'models']:\n    print('stub/model'); _s.exit(0)\n")
        if "stub/other" in body:
            catalog = ""
        path = self.bin / name
        path.write_text(lines[0] + "\n" + catalog + lines[1])
        path.chmod(0o755)

    def argv(self, agent="opencode", mode="implement", timeout=30):
        argv = [sys.executable, str(DELEGATE), "--agent", agent, "--mode", mode,
                "--tier", "SMALL", "--cwd", str(self.repo), "--timeout", str(timeout)]
        if agent == "opencode":
            argv += ["--model", "stub/model"]
        return argv

    def run(self, **kw):
        proc = subprocess.run(self.argv(**kw), input="do the task", capture_output=True,
                              text=True, env=self.env, timeout=120)
        return json.loads(proc.stdout), proc

    def start(self, **kw):
        proc = subprocess.Popen(self.argv(**kw), stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=self.env)
        proc.stdin.write("do the task")
        proc.stdin.close()
        proc.stdin = None   # so communicate() does not flush a closed pipe
        return proc

    def agents(self):
        return orchlib.marked_processes(cwd=str(self.repo.resolve()))


def wait_for(predicate, seconds=10.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return False


def stops_editing(env, path, seconds=1.0):
    """True if `path` stops growing (the editor is really gone)."""
    if not path.exists():
        return True
    size = path.stat().st_size
    time.sleep(seconds)
    return path.stat().st_size == size


def quiet_after(paths, seconds=3.0, window=0.5, since=None):
    """Seconds from `since` (wall clock, default now) to the last write to any of `paths`,
    once `window` seconds pass with no write; None if writes went on past `seconds`."""
    since = since if since is not None else time.time()

    def last_write():
        return max([p.stat().st_mtime for p in paths if p.exists()] or [since])

    deadline = time.time() + seconds + window
    while time.time() < deadline:
        latest = last_write()
        if time.time() - latest >= window:
            return round(max(0.0, latest - since), 3)
        time.sleep(0.02)
    return None


def alive(pid):
    try:
        status = Path("/proc/%d/status" % pid).read_text()
    except OSError:
        return False
    return "State:\tZ" not in status


def recorded_pids(repo):
    pids = {}
    for name in ESCAPING_FILES:
        try:
            pids[name] = int((repo / (name + ".pid")).read_text())
        except (OSError, ValueError):
            pass
    return pids


def watchdogs(env):
    """Live processes forked from this environment's dispatcher (the watchdog keeps the
    dispatcher's command line and environment)."""
    found = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = Path("/proc/%s/cmdline" % pid).read_bytes()
            environ = Path("/proc/%s/environ" % pid).read_bytes()
        except OSError:
            continue
        if str(DELEGATE).encode() in cmd and str(env.state).encode() in environ \
                and alive(int(pid)):
            found.append(int(pid))
    return found


def descendants(pid):
    children = {}
    for entry in os.listdir("/proc"):
        if entry.isdigit():
            try:
                stat = Path("/proc/%s/stat" % entry).read_text()
                ppid = int(stat.rsplit(")", 1)[1].split()[1])
            except (OSError, IndexError, ValueError):
                continue
            children.setdefault(ppid, []).append(int(entry))
    found, todo = [], [pid]
    while todo:
        for child in children.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


def guard_blocks_edit(env):
    """What a Sonnet fallback meets next: the edit guard, which blocks edits while a
    delegated writer is alive in the repository."""
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "cwd": str(env.repo),
               "tool_input": {"file_path": str(env.repo / "app.py")}}
    proc = subprocess.run([sys.executable, str(ROOT / "hooks" / "guard.py")],
                          input=json.dumps(payload), capture_output=True, text=True,
                          env=env.env, timeout=30)
    return '"deny"' in proc.stdout or proc.returncode == 2


def start_detached(env):
    """The dispatcher in its own process group, so the test can kill that group."""
    proc = subprocess.Popen(env.argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env.env,
                            start_new_session=True)
    proc.stdin.write("do the task")
    proc.stdin.close()
    proc.stdin = None
    return proc


def check_uncatchable_stop(how):
    """The dispatcher dies without running a line of cleanup. `how` is "pid" (SIGKILL to
    the dispatcher), "group" (SIGKILL to its whole process group - which killed the old
    watchdog with it and left a grandchild editing) or "tree" (SIGKILL to it and every
    descendant at once, as a supervisor's tree-kill would). Every writer - including one
    without the marker and one in its own session - must stop on its own, with no second
    run and no `orch stop`."""
    label = "SIGKILL (%s)" % how
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", ESCAPING_STUB)
        proc = start_detached(env)
        if not wait_for(lambda: len(recorded_pids(env.repo)) == len(ESCAPING_FILES)):
            os.killpg(proc.pid, signal.SIGKILL)
            return ["%s: the stub never started all its writers" % label]
        pids = recorded_pids(env.repo)
        killed_at = time.time()
        if how == "pid":
            os.kill(proc.pid, signal.SIGKILL)
        elif how == "group":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            for pid in [proc.pid] + descendants(proc.pid):
                try:
                    os.kill(pid, signal.SIGKILL)
                except OSError:
                    pass
        wait_for(lambda: not any(alive(pid) for pid in pids.values()), 3.0)
        dead_ms = (time.time() - killed_at) * 1000
        proc.communicate()
        quiet = quiet_after([env.repo / name for name in ESCAPING_FILES], since=killed_at)
        if quiet is None:
            problems.append("%s: files were still being written 3s after the kill" % label)
        survivors = {name: pid for name, pid in pids.items() if alive(pid)}
        if survivors:
            problems.append("%s: writers survived: %s" % (label, survivors))
            for pid in survivors.values():
                os.kill(pid, signal.SIGKILL)
        if env.agents():
            problems.append("%s: marked processes survived: %s" % (label, env.agents()))
            orchlib.stop_processes(env.agents())
        if not wait_for(lambda: not watchdogs(env), 3):
            problems.append("%s: the watchdog did not exit" % label)
        if guard_blocks_edit(env):
            problems.append("%s: an edit after the kill is still blocked" % label)
        print("  %-18s every writer dead %.0f ms after the kill" % (label, dead_ms))
    return problems


def check_signal_stops_agent(sig, stub=EDITING_STUB):
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", stub)
        proc = env.start()
        escaping = stub is ESCAPING_STUB
        started = ((lambda: len(recorded_pids(env.repo)) == len(ESCAPING_FILES)) if escaping
                   else (lambda: (env.repo / "grandchild.txt").exists()))
        if not wait_for(started):
            proc.kill()
            return ["%s: the stub never started" % sig.name]
        os.kill(proc.pid, sig)
        try:
            out, _err = proc.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()
            return ["%s: the dispatcher did not return after the signal" % sig.name]
        try:
            result = json.loads(out)
        except ValueError:
            return ["%s: no JSON result after the signal (stdout %r)" % (sig.name, out[:200])]
        if result.get("status") != "interrupted":
            problems.append("%s: status %r, wanted interrupted" % (sig.name, result.get("status")))
        if not (Path(result["workspace"]) / "result.json").exists():
            problems.append("%s: result.json was not written" % sig.name)
        if env.agents():
            problems.append("%s: agent processes survived: %s" % (sig.name, env.agents()))
            orchlib.stop_processes(env.agents())
        names = ESCAPING_FILES if escaping else ("edited.txt", "grandchild.txt")
        for name in names:
            if not stops_editing(env, env.repo / name):
                problems.append("%s: %s is still being edited" % (sig.name, name))
        survivors = [pid for pid in recorded_pids(env.repo).values() if alive(pid)]
        if survivors:
            problems.append("%s: writers survived: %s" % (sig.name, survivors))
            for pid in survivors:
                os.kill(pid, signal.SIGKILL)
        if not escaping and set(result.get("files_changed") or []) != set(names):
            problems.append("%s: partial changes reported as %r"
                            % (sig.name, result.get("files_changed")))
        if not result.get("agent_terminated"):
            problems.append("%s: agent_terminated %r" % (sig.name, result.get("agent_terminated")))
        if guard_blocks_edit(env):
            problems.append("%s: an edit after the cancellation is still blocked" % sig.name)
        if not wait_for(lambda: not watchdogs(env), 3):
            problems.append("%s: the watchdog outlived the dispatcher" % sig.name)
        if result.get("recovery") != "stop":
            problems.append("%s: a cancelled run must not suggest %r"
                            % (sig.name, result.get("recovery")))
        if (result.get("fallback") or {}).get("allowed"):
            problems.append("%s: fallback allowed after a cancellation" % sig.name)
        if list((env.state / "active").glob("*.json")):
            problems.append("%s: the run registry entry was left behind" % sig.name)
    return problems


def check_sigkill_stops_agent():
    """SIGKILL cannot be caught. PR_SET_PDEATHSIG takes the agent down with the dispatcher;
    a grandchild may outlive it, but it still carries the run marker, so the next writer
    refuses to start and `orch stop` finds it."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", EDITING_STUB)
        proc = env.start()
        if not wait_for(lambda: (env.repo / "grandchild.txt").exists()):
            proc.kill()
            return ["SIGKILL: the stub never started"]
        proc.kill()
        proc.wait()
        for name in ("edited.txt", "grandchild.txt"):
            if not stops_editing(env, env.repo / name, seconds=2.0):
                problems.append("SIGKILL: %s kept changing after the dispatcher died" % name)
        survivors = env.agents()
        if survivors:
            problems.append("SIGKILL: the watchdog left %s alive" % survivors)
        # A process that escaped the group and the marker scan is not something a test can
        # build safely; what is checked is that a survivor, if any, blocks a second writer.
        if survivors:
            # The grandchild: findable, and it blocks a second writer.
            result, _ = env.run()
            if result.get("status") != "busy":
                problems.append("SIGKILL: a second writer started beside a surviving "
                                "process (status %r)" % result.get("status"))
            elif (result.get("fallback") or {}).get("allowed"):
                problems.append("SIGKILL: busy result allowed a fallback")
            orchlib.stop_processes(survivors)
            if env.agents():
                problems.append("SIGKILL: stop_processes left %s" % env.agents())
    return problems


def check_timeout_kills_tree():
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", ESCAPING_STUB)
        result, _ = env.run(timeout=3)
        if result.get("status") != "timeout":
            problems.append("timeout (escaping writers): status %r" % result.get("status"))
        if quiet_after([env.repo / name for name in ESCAPING_FILES]) is None:
            problems.append("timeout: files still being written after the result")
        survivors = [pid for pid in recorded_pids(env.repo).values() if alive(pid)]
        if survivors:
            problems.append("timeout: writers survived: %s" % survivors)
            for pid in survivors:
                os.kill(pid, signal.SIGKILL)
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", EDITING_STUB)
        result, _ = env.run(timeout=2)
        if result.get("status") != "timeout":
            problems.append("timeout: status %r" % result.get("status"))
        if env.agents():
            problems.append("timeout: survivors %s" % env.agents())
            orchlib.stop_processes(env.agents())
        if not stops_editing(env, env.repo / "grandchild.txt"):
            problems.append("timeout: grandchild still editing")
        fallback = result.get("fallback") or {}
        if not fallback.get("allowed") or fallback.get("to") != "sonnet":
            problems.append("timeout: a contained timeout should allow the Sonnet fallback, "
                            "got %r" % fallback)
        if sorted(fallback.get("partial_changes") or []) != ["edited.txt", "grandchild.txt"]:
            problems.append("timeout: partial changes %r" % fallback.get("partial_changes"))
    return problems


# (name, stub stderr, exit code, expected category, expected implement recovery)
FAILURES = [
    ("missing model", "Error: ProviderModelNotFoundError: model kimi-k2.6 not found", 1,
     "invalid_model", "fallback_sonnet"),
    ("expired login", "Error: Invalid credential. Please run opencode auth login", 1,
     "auth", "fallback_sonnet"),
    ("server error", "UnknownError: Unexpected server error", 1,
     "provider_unavailable", "fallback_sonnet"),
    ("usage limit", "You've hit your usage limit. Try again later.", 1,
     "quota", "fallback_sonnet"),
    ("rate limit", "429 Too Many Requests", 1, "rate_limit", "fallback_sonnet"),
    ("capacity", "Selected model is at capacity. Please try a different model.", 1,
     "provider_unavailable", "fallback_sonnet"),
    ("silent", "", 3, "unknown", "fallback_sonnet"),
]


def check_failure_classification():
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        for name, stderr, code, category, recovery in FAILURES:
            env.stub("opencode", stub_script(
                "sys.stderr.write(%r)\nsys.exit(%d)\n" % (stderr, code)))
            result, _ = env.run()
            if result.get("status") != "failed":
                problems.append("%s: status %r" % (name, result.get("status")))
            if result.get("error_category") != category:
                problems.append("%s: category %r, wanted %r"
                                % (name, result.get("error_category"), category))
            if result.get("recovery") != recovery:
                problems.append("%s: recovery %r" % (name, result.get("recovery")))
            if "usage_error" in json.dumps(result) or "--variant" in (result.get("error") or ""):
                problems.append("%s: the old --variant misdiagnosis is back" % name)
            if stderr and stderr[:20] not in (result.get("error") or ""):
                problems.append("%s: error does not carry the CLI's stderr" % name)
            if not (result.get("fallback") or {}).get("allowed"):
                problems.append("%s: fallback not allowed: %r" % (name, result.get("fallback")))
            if not Path(result.get("stderr_path", "/nonexistent")).exists():
                problems.append("%s: stderr_path missing" % name)
        # The same failures in a review are BLOCKED with a reason, never a fake verdict.
        for name, stderr, code, category, _ in FAILURES[:5]:
            env.stub("codex", stub_script(
                "sys.stdin.read()\nsys.stderr.write(%r)\nsys.exit(%d)\n" % (stderr, code)))
            result, _ = env.run(agent="codex", mode="review")
            if result.get("verdict") != "BLOCKED" or result.get("review_status") != "blocked":
                problems.append("review %s: verdict %r / %r" % (
                    name, result.get("verdict"), result.get("review_status")))
            if result.get("blocker_reason") != category:
                problems.append("review %s: blocker_reason %r" % (name, result.get("blocker_reason")))
            if category == "quota" and result.get("recovery") != "blocked_quota":
                problems.append("review quota: recovery %r" % result.get("recovery"))
    return problems


def check_secrets_redacted():
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", stub_script(
            "sys.stderr.write('401 Unauthorized api_key=sk-abcdefghijklmnop1234 "
            "Bearer abcdefghijklmnopqrstuvwxyz')\nsys.exit(1)\n"))
        result, _ = env.run()
        text = json.dumps(result)
        if "sk-abcdefghijklmnop1234" in text or "abcdefghijklmnopqrstuvwxyz" in text:
            problems.append("a credential reached the result")
    return problems


def check_mixed_changes_block_fallback():
    """A failed run that touched a file the user had already changed needs the user."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        (env.repo / "app.py").write_text("print('user edit')\n")
        env.stub("opencode", stub_script(
            "import os\nopen(os.path.join(os.environ['PWD'], 'app.py'), 'a').write('x')\n"
            "sys.stderr.write('Unexpected server error')\nsys.exit(1)\n"))
        result, _ = env.run()
        if result.get("mixed_files") != ["app.py"]:
            problems.append("mixed files %r" % result.get("mixed_files"))
        if (result.get("fallback") or {}).get("allowed"):
            problems.append("fallback allowed over the user's own uncommitted changes")
    return problems


def check_completed_run_reports_gate():
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", stub_script(
            "import os\nopen(os.path.join(os.environ['PWD'], 'style.css'), 'w')"
            ".write('a { color: red }\\n')\n"
            "print('```json\\n{\"status\": \"completed\", \"summary\": \"done\", "
            "\"touched_files\": [\"style.css\"]}\\n```')\n"))
        result, _ = env.run()
        if result.get("status") != "completed" or result.get("files_changed") != ["style.css"]:
            problems.append("completed run: %r %r" % (result.get("status"),
                                                      result.get("files_changed")))
        gate = result.get("review_gate") or {}
        if gate.get("review") != "not_required":
            problems.append("a one-line CSS change on SMALL should not need Codex: %r" % gate)
        if "fallback" in result:
            problems.append("a completed run carries a fallback block")
        if env.agents():
            problems.append("completed run left processes: %s" % env.agents())
    return problems


def check_invalid_model_fails_fast():
    """A model the catalog does not offer is refused before a run is spent on it."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", stub_script(
            "if sys.argv[1:2] == ['models']:\n    print('stub/other')\n    sys.exit(0)\n"
            "open('/dev/null','w')\nsys.exit(99)\n"))
        started = time.monotonic()
        result, _ = env.run()
        if result.get("status") != "invalid_model":
            problems.append("status %r" % result.get("status"))
        if result.get("exit_code") is not None:
            problems.append("the agent was started anyway")
        if not (result.get("fallback") or {}).get("allowed"):
            problems.append("invalid model should allow fallback: %r" % result.get("fallback"))
        if time.monotonic() - started > 10:
            problems.append("invalid model took %.1fs" % (time.monotonic() - started))
    return problems


def check_busy_refuses_second_writer():
    """A live writer in the repository - here a stand-in carrying the run marker, as an
    orphan from any earlier dispatcher would - stops a new implementation before it
    starts, and a read-only review is not blocked by it."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", stub_script("open('/tmp/should-not-run', 'w')\n"))
        marker = dict(env.env, **{orchlib.ENV_RUN: "orphan1", orchlib.ENV_MODE: "implement",
                                  orchlib.ENV_CWD: str(env.repo.resolve())})
        orphan = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                  env=marker)
        try:
            result, _ = env.run()
            if result.get("status") != "busy":
                problems.append("busy: status %r" % result.get("status"))
            if [p["pid"] for p in result.get("active_agents") or []] != [orphan.pid]:
                problems.append("busy: active agents %r" % result.get("active_agents"))
            if (result.get("fallback") or {}).get("allowed"):
                problems.append("busy: fallback allowed while a writer is alive")
            if result.get("exit_code") is not None:
                problems.append("busy: the agent was started")
            env.stub("codex", stub_script(
                "sys.stdin.read()\nprint('```json\\n{\"verdict\": \"PASS\", "
                "\"findings\": []}\\n```')\n"))
            review, _ = env.run(agent="codex", mode="review")
            if review.get("status") != "completed":
                problems.append("busy: a read-only review was blocked: %r" % review.get("status"))
        finally:
            orphan.kill()
            orphan.wait()
    return problems


HANGING_CATALOG = r"""#!/usr/bin/env python3
import os, subprocess, sys, time
if sys.argv[1:2] == ["models"]:
    subprocess.Popen([sys.executable, "-c", "import os, time\nwhile True:\n"
                      "    open(os.environ['HANG_MARK'] + '-child', 'a').write('c')\n"
                      "    time.sleep(0.1)\n"], start_new_session=True)
    while True:
        open(os.environ["HANG_MARK"], "a").write("q")
        time.sleep(0.1)
sys.exit(0)
"""


def processes_running(marker):
    found = []
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                if marker.encode() in Path("/proc/%s/cmdline" % pid).read_bytes():
                    found.append(int(pid))
            except OSError:
                pass
    return found


def check_stop_during_catalog_query():
    """A dispatcher stopped before the agent starts - here while it waits on the model
    catalog - must not orphan the query. This is the case that left four stub queries
    running for half an hour during development."""
    problems = []
    for sig, group in ((signal.SIGTERM, False), (signal.SIGKILL, False),
                       (signal.SIGKILL, True)):
        label = "%s%s" % (sig.name, " to the dispatcher's group" if group else "")
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            (env.bin / "opencode").write_text(HANGING_CATALOG)
            (env.bin / "opencode").chmod(0o755)
            mark = Path(tmp) / "query-alive"
            child = Path(str(mark) + "-child")
            env.env["HANG_MARK"] = str(mark)
            proc = start_detached(env)
            if not wait_for(lambda: mark.exists() and child.exists()):
                os.killpg(proc.pid, signal.SIGKILL)
                problems.append("%s: the catalog query never started" % label)
                continue
            if group:
                os.killpg(proc.pid, sig)
            else:
                os.kill(proc.pid, sig)
            out, _ = proc.communicate(timeout=30)
            if sig == signal.SIGTERM:
                try:
                    result = json.loads(out)
                except ValueError:
                    result = {}
                if result.get("status") != "interrupted":
                    problems.append("SIGTERM during the catalog query: status %r"
                                    % result.get("status"))
                if result.get("exit_code") is not None:
                    problems.append("SIGTERM during the catalog query: the agent started")
            if not wait_for(lambda: not processes_running(str(env.bin)), 5):
                survivors = processes_running(str(env.bin))
                problems.append("%s during the catalog query orphaned %s" % (label, survivors))
                for pid in survivors:
                    os.kill(pid, signal.SIGKILL)
            if quiet_after([mark, child]) is None:
                problems.append("%s during the catalog query: a child of the query kept "
                                "running" % label)
    return problems


def check_snapshot_renames():
    """A rename is two changes: the new path and the old one, which is gone."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        repo = str(env.repo)
        before = orchlib.tree_snapshot(repo)
        subprocess.run(["git", "-C", repo, "mv", "app.py", "main.py"], check=True)
        changed, _ = orchlib.tree_changes(before, orchlib.tree_snapshot(repo))
        if sorted(changed or []) != ["app.py", "main.py"]:
            problems.append("staged rename reported as %r" % changed)
        subprocess.run(["git", "-C", repo, "commit", "-qm", "mv"], check=True)
        before = orchlib.tree_snapshot(repo)
        os.rename(os.path.join(repo, "main.py"), os.path.join(repo, "moved.py"))
        subprocess.run(["git", "-C", repo, "add", "-N", "moved.py"], check=True)
        snapshot = orchlib.tree_snapshot(repo)
        if any(not os.path.basename(p) in ("main.py", "moved.py") for p in snapshot):
            problems.append("worktree rename produced a garbage entry: %r" % snapshot)
    return problems


def check_classification_ignores_agent_words():
    """A review that discusses a 403 is not an authentication failure."""
    problems = []
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("codex", stub_script(
            "sys.stdin.read()\nprint('the endpoint returns 403 when billing is off; "
            "a 500 follows')\nsys.stderr.write('stream disconnected before completion')\n"
            "sys.exit(1)\n"))
        result, _ = env.run(agent="codex", mode="review")
        if result.get("error_category") != "provider_unavailable":
            problems.append("classified %r from the agent's own words"
                            % result.get("error_category"))
    return problems


def load_delegate():
    import importlib.machinery
    import importlib.util
    loader = importlib.machinery.SourceFileLoader("delegate_under_test", str(DELEGATE))
    module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(module)
    return module


# Runs the real dispatcher with one orchlib function replaced, for states a stub cannot
# produce (here: /proc that cannot be scanned).
PATCHED_DISPATCHER = r"""
import importlib.machinery, importlib.util, sys
path = sys.argv.pop(1)
loader = importlib.machinery.SourceFileLoader("delegate_patched", path)
module = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
loader.exec_module(module)
module.orchlib.process_scan_available = lambda: False
sys.argv[0] = path
module.main()
"""


def check_uncertain_lifecycle_blocks_fallback():
    """When the dispatcher cannot confirm that every process of a failed run is gone, no
    automatic Sonnet fallback may start beside a writer that might still be alive."""
    problems = []
    delegate = load_delegate()
    clean = delegate.fallback_decision("timeout", "fallback_sonnet", [], [], [], [])
    if not clean["allowed"]:
        problems.append("a contained timeout blocked the fallback: %r" % clean)
    for doubts, moved, label in ((["the cleanup could not confirm every process stopped"],
                                  False, "unconfirmed cleanup"),
                                 ([], True, "HEAD moved")):
        decision = delegate.fallback_decision("timeout", "fallback_sonnet", [], [], [], [],
                                              doubts, moved)
        if decision["allowed"]:
            problems.append("%s still allowed the fallback" % label)
    with tempfile.TemporaryDirectory() as tmp:
        env = Env(tmp)
        env.stub("opencode", EDITING_STUB)
        argv = env.argv(timeout=2)
        argv[1:2] = ["-c", PATCHED_DISPATCHER, str(DELEGATE)]
        proc = subprocess.run(argv, input="do the task", capture_output=True, text=True,
                              env=env.env, timeout=120)
        try:
            result = json.loads(proc.stdout)
        except ValueError:
            return problems + ["patched dispatcher gave no result: %s" % proc.stderr[-300:]]
        fallback = result.get("fallback") or {}
        if result.get("status") != "timeout" or fallback.get("allowed"):
            problems.append("unscannable /proc: status %r, fallback %r"
                            % (result.get("status"), fallback))
        elif not any("/proc" in b for b in fallback.get("blockers") or []):
            problems.append("unscannable /proc: blockers %r" % fallback.get("blockers"))
        if env.agents():
            orchlib.stop_processes(env.agents())
    return problems


def check_gate_always_reported():
    """An implementation that ran always carries an explicit gate result: for an empty
    change, a commit made during the run, and a working tree the dispatcher could no
    longer read."""
    problems = []
    report = ("print('```json\\n{\"status\": \"completed\", \"summary\": \"done\", "
              "\"touched_files\": []}\\n```')\n")
    cases = [
        ("no change", "", "not_required", "complete"),
        ("commit during the run",
         "import os, subprocess\nhere = os.environ['PWD']\n"
         "open(os.path.join(here, 'app.py'), 'w').write("
         "\"import frappe\\nfrappe.db.sql('DELETE FROM `tabNote`')\\n\")\n"
         "subprocess.run(['git', '-C', here, 'commit', '-qam', 'agent'], check=True)\n",
         "required", "complete"),
        ("unreadable working tree",
         "import os\nhere = os.environ['PWD']\nopen(os.path.join(here, 'new.py'), 'w')"
         ".write('x = 1\\n')\nos.rename(os.path.join(here, '.git'), os.path.join(here, "
         "'.git-gone'))\n",
         "required", "incomplete"),
    ]
    for name, body, review, status in cases:
        with tempfile.TemporaryDirectory() as tmp:
            env = Env(tmp)
            env.stub("opencode", stub_script(body + report))
            result, proc = env.run()
            gate = result.get("review_gate")
            if not gate:
                problems.append("%s: no review_gate in the result (%s)" % (name, proc.stderr[-200:]))
                continue
            if gate.get("review") != review or gate.get("gate_status") != status:
                problems.append("%s: gate %r/%r, wanted %s/%s: %s" % (
                    name, gate.get("review"), gate.get("gate_status"), review, status,
                    gate.get("reasons")))
            if name == "commit during the run":
                if "app.py" not in (result.get("files_changed") or []):
                    problems.append("committed file missing from files_changed: %r"
                                    % result.get("files_changed"))
                if "head_moved" not in result:
                    problems.append("HEAD movement not reported")
                if "data-integrity-or-destructive" not in {t["name"] for t in gate["triggers"]}:
                    problems.append("the committed destructive change was not assessed: %r"
                                    % gate["triggers"])
    return problems


def main():
    failures = []
    failures += check_snapshot_renames()
    failures += check_classification_ignores_agent_words()
    failures += check_stop_during_catalog_query()
    failures += check_busy_refuses_second_writer()
    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        failures += check_signal_stops_agent(sig)
        failures += check_signal_stops_agent(sig, ESCAPING_STUB)
    failures += check_sigkill_stops_agent()
    for how in ("pid", "group", "tree"):
        failures += check_uncatchable_stop(how)
    failures += check_timeout_kills_tree()
    failures += check_uncertain_lifecycle_blocks_fallback()
    failures += check_failure_classification()
    failures += check_secrets_redacted()
    failures += check_mixed_changes_block_fallback()
    failures += check_completed_run_reports_gate()
    failures += check_gate_always_reported()
    failures += check_invalid_model_fails_fast()
    print("3 stop signals x 2 agent shapes, SIGKILL to the dispatcher / its group / its "
          "tree, stops during the catalog query, timeout, uncertain cleanup, %d failure "
          "categories, redaction, mixed changes, gate reporting, invalid model checked"
          % len(FAILURES))
    if failures:
        print("\nFAILED (%d):" % len(failures))
        for line in failures:
            print("  - %s" % line)
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
