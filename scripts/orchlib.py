"""Shared mechanics for scripts/delegate, scripts/orch and the edit guard in hooks/guard.py.

Five things live here, each small and standard-library only:

  runs       marking, finding and stopping delegated agent processes, so a second agent
             never starts while an earlier one may still be editing the tree
  snapshots  what a run actually changed in the working tree, measured, not reported
  failures   what went wrong with a CLI run, and what the orchestrator should do next
  models     which OpenCode and Codex model to use, checked against the CLI's own catalog
  review     whether a change needs an independent Codex review, from the real diff

Paths: user decisions (sites, model overrides) live under the config dir, machine state
(run workspaces, caches, metrics) under the state dir. Both are outside every repository.
FRAPPE_ORCHESTRATOR_CONFIG and FRAPPE_ORCHESTRATOR_STATE override them, which is how the
test suites keep everything in a scratch directory.
"""

import ast
import codecs
import fnmatch
import hashlib
import json
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import tempfile
import time
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTING = ROOT / "config" / "model-routing.json"
TEXT = "utf-8"


def config_dir():
    override = os.environ.get("FRAPPE_ORCHESTRATOR_CONFIG")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "frappe-orchestrator"


def state_dir():
    override = os.environ.get("FRAPPE_ORCHESTRATOR_STATE")
    if override:
        return Path(override)
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "frappe-orchestrator"


def private(path):
    """Create `path` as a 0700 directory and return it."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding=TEXT))
    except (OSError, ValueError):
        return default


def write_json(path, data):
    """Atomic replace, so a reader never sees half a file."""
    path = Path(path)
    private(path.parent)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding=TEXT) as out:
            json.dump(data, out, indent=2, sort_keys=True)
            out.write("\n")
        os.replace(temporary, str(path))
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def load_routing():
    return json.loads(ROUTING.read_text(encoding=TEXT))


# --------------------------------------------------------------------------
# Runs
#
# Every delegated agent is started with three environment variables. The environment is
# inherited by everything the agent starts and survives reparenting and new sessions, so
# /proc/<pid>/environ finds an agent's whole tree even after its dispatcher is gone -
# which is exactly the orphan case (audit BUG-01) that a pid file alone cannot see.
#
# The registry under state/active/ is only the fast path: an empty directory means no
# scan is needed. An entry left behind by a dispatcher that was SIGKILLed is harmless -
# the next check scans, finds nothing alive, and removes it.
# --------------------------------------------------------------------------

ENV_RUN = "FRAPPE_ORCHESTRATOR_RUN"
ENV_CWD = "FRAPPE_ORCHESTRATOR_RUN_CWD"
ENV_MODE = "FRAPPE_ORCHESTRATOR_RUN_MODE"

# Modes whose agent writes to the working tree. Only these block another writer.
WRITER_MODES = frozenset({"implement", "test"})


def active_dir():
    return private(state_dir() / "active")


def register_run(run_id, info):
    write_json(active_dir() / ("%s.json" % run_id), info)


def unregister_run(run_id):
    try:
        (active_dir() / ("%s.json" % run_id)).unlink()
    except OSError:
        pass


def _environ(pid):
    try:
        raw = Path("/proc/%s/environ" % pid).read_bytes()
    except OSError:
        return None
    if ENV_RUN.encode() not in raw:
        return None
    env = {}
    for item in raw.split(b"\0"):
        key, sep, value = item.partition(b"=")
        if sep and key in (ENV_RUN.encode(), ENV_CWD.encode(), ENV_MODE.encode()):
            env[key.decode()] = value.decode(TEXT, "replace")
    return env


def _cmdline(pid):
    try:
        raw = Path("/proc/%s/cmdline" % pid).read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode(TEXT, "replace").strip()[:200]


def marked_processes(cwd=None, run_id=None, writers_only=False):
    """Live processes started by a delegated run, optionally narrowed. Linux /proc only."""
    found = []
    me = os.getpid()
    try:
        pids = [name for name in os.listdir("/proc") if name.isdigit()]
    except OSError:
        return found
    for pid in pids:
        if int(pid) == me:
            continue
        env = _environ(pid)
        if not env:
            continue
        if run_id and env.get(ENV_RUN) != run_id:
            continue
        if cwd and env.get(ENV_CWD) != cwd:
            continue
        if writers_only and env.get(ENV_MODE) not in WRITER_MODES:
            continue
        found.append({
            "pid": int(pid), "run": env.get(ENV_RUN), "cwd": env.get(ENV_CWD),
            "mode": env.get(ENV_MODE), "command": _cmdline(pid),
        })
    return found


def process_scan_available():
    """Whether marked_processes can see anything at all: /proc listable and readable."""
    try:
        return bool(os.listdir("/proc")) and Path("/proc/self/environ").read_bytes() is not None
    except OSError:
        return False


def active_writers(cwd=None):
    """Writer-mode agent processes still alive, cleaning stale registry entries.

    Cheap when nothing is registered: one listdir. Only a registered run, live or stale,
    costs a /proc scan.
    """
    try:
        entries = list(active_dir().glob("*.json"))
    except OSError:
        entries = []
    if not entries:
        return []
    alive = marked_processes(writers_only=True)
    live_runs = {proc["run"] for proc in alive}
    for entry in entries:
        info = read_json(entry, {}) or {}
        if entry.stem not in live_runs and not _pid_alive(info.get("dispatcher_pid", 0)):
            try:
                entry.unlink()
            except OSError:
                pass
    return [proc for proc in alive if cwd is None or proc["cwd"] == cwd]


def _pid_alive(pid):
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def stop_processes(procs, grace=2.0):
    """SIGTERM, then SIGKILL whatever is left. Returns the pids that survived both."""
    for proc in procs:
        try:
            os.kill(proc["pid"], signal.SIGTERM)
        except OSError:
            pass
    deadline = time.monotonic() + grace
    left = procs
    while left and time.monotonic() < deadline:
        time.sleep(0.1)
        left = [p for p in left if _environ(p["pid"]) is not None]
    for proc in left:
        try:
            os.kill(proc["pid"], signal.SIGKILL)
        except OSError:
            pass
    time.sleep(0.1)
    return [p["pid"] for p in left if _environ(p["pid"]) is not None]


def _set_parent_death_signal(sig):
    try:
        import ctypes
        ctypes.CDLL(None, use_errno=True).prctl(1, sig)   # PR_SET_PDEATHSIG
        return True
    except Exception:
        return False


def kill_run(run_id, groups=()):
    """SIGKILL every process of a run: its process groups, then anything carrying its
    marker, repeated until a scan finds nothing (a process may fork between scan and kill).
    Returns the pids still alive after the last round."""
    for pgid in groups:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except OSError:
            pass
    left = []
    for _ in range(20 if run_id else 0):   # no run id would match every run's processes
        left = marked_processes(run_id=run_id)
        if not left:
            return []
        for proc in left:
            try:
                os.kill(proc["pid"], signal.SIGKILL)
            except OSError:
                pass
        time.sleep(0.05)
    return [p["pid"] for p in left]


class _Stop(Exception):
    pass


def _raise_stop(*_):
    raise _Stop()


class Watchdog:
    """Stops a run when its dispatcher dies, however it dies.

    The dispatcher cannot handle SIGKILL, and a supervisor may kill its whole process
    group or every descendant at once - an earlier watchdog was a child in the
    dispatcher's group and died with it, leaving a grandchild editing (final
    verification, Q1). So this one is forked twice into its own session: not in the
    dispatcher's group, not its descendant. It learns of the dispatcher's death from a
    pipe only the dispatcher holds: EOF without "done" means the dispatcher is gone, and
    the watchdog SIGKILLs the agent's process groups and every process carrying the run
    marker. Linux/WSL; elsewhere `start` returns None and the signal handlers still apply.
    """

    def __init__(self, pid, fd):
        self.pid, self.fd = pid, fd

    @classmethod
    def start(cls, run_id, timeout=3.0):
        if os.name != "posix":
            return None
        cmd_r, cmd_w = os.pipe()
        ready_r, ready_w = os.pipe()
        try:
            pid = os.fork()
        except OSError:
            for fd in (cmd_r, cmd_w, ready_r, ready_w):
                os.close(fd)
            return None
        if pid == 0:   # intermediate: never returns into the dispatcher's code
            code = 1
            try:
                os.setsid()
                if os.fork() == 0:
                    code = cls._serve(run_id, cmd_r, ready_w)
                else:
                    code = 0
            finally:
                os._exit(code)
        os.close(cmd_r)
        os.close(ready_w)
        try:
            os.waitpid(pid, 0)
            ready = b""
            deadline = time.monotonic() + timeout
            while not ready.endswith(b"\n") and time.monotonic() < deadline:
                rlist, _, _ = select.select([ready_r], [], [], max(0.0, deadline - time.monotonic()))
                if not rlist:
                    break
                chunk = os.read(ready_r, 64)
                if not chunk:
                    break
                ready += chunk
        finally:
            os.close(ready_r)
        if not ready.startswith(b"ready "):
            os.close(cmd_w)
            return None
        return cls(int(ready.split()[1]), cmd_w)

    @staticmethod
    def _serve(run_id, cmd_r, ready_w):
        for sig in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
            # A signal aimed at the watchdog itself means the session is being torn down:
            # stop the run rather than leave it unwatched.
            signal.signal(sig, _raise_stop)
        null = os.open(os.devnull, os.O_RDWR)
        for fd in (0, 1, 2):   # never hold the dispatcher's stdout open for its reader
            os.dup2(null, fd)
        keep = {cmd_r, ready_w}
        for fd in range(3, 1024):
            if fd not in keep:
                try:
                    os.close(fd)
                except OSError:
                    pass
        os.write(ready_w, b"ready %d\n" % os.getpid())
        os.close(ready_w)
        groups, buf = set(), b""
        try:
            while True:
                chunk = os.read(cmd_r, 512)
                if not chunk:
                    break   # the dispatcher is gone without saying "done"
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line == b"done":
                        return 0
                    if line.startswith(b"group "):
                        groups.add(int(line.split()[1]))
        except _Stop:
            pass
        for sig in (signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
            signal.signal(sig, signal.SIG_IGN)
        kill_run(run_id, groups)
        return 0

    def _send(self, line):
        try:
            os.write(self.fd, line.encode() + b"\n")
        except OSError:
            pass

    def watch_group(self, pgid):
        self._send("group %d" % pgid)

    def done(self):
        """The dispatcher has cleaned up after itself; the watchdog exits without acting."""
        if self.fd is not None:
            self._send("done")
            os.close(self.fd)
            self.fd = None


# --------------------------------------------------------------------------
# Snapshots: what a run changed, measured from the working tree
# --------------------------------------------------------------------------

GIT_SECONDS = 30
HASH_LIMIT = 20 * 1024 * 1024


def git(cwd, *args, timeout=GIT_SECONDS):
    """stdout of one git command as text, or None if git could not answer."""
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "--no-pager"] + list(args), stdin=subprocess.DEVNULL,
            capture_output=True, timeout=timeout,
            env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.decode(TEXT, "replace")


def _fingerprint(path):
    try:
        info = os.stat(path)
    except OSError:
        return "missing"
    if info.st_size > HASH_LIMIT:
        return "size:%d:mtime:%d" % (info.st_size, info.st_mtime_ns)
    try:
        with open(path, "rb") as handle:
            return hashlib.sha1(handle.read()).hexdigest()
    except OSError:
        return "unreadable"


def tree_snapshot(cwd):
    """{path: "<status>:<content fingerprint>"} for every dirty or untracked file, or None.

    Clean files are absent, so a file that is absent before and present after is one the
    run changed, and a file present in both with a different value was changed again.
    """
    listing = git(cwd, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if listing is None:
        return None
    snapshot = {}
    items = listing.split("\0")
    i = 0
    while i < len(items):
        item = items[i]
        i += 1
        if len(item) < 4:
            continue
        code, path = item[:2], item[3:]
        if code[0] in "RC" or code[1] in "RC":
            # The rename source follows as its own entry; it is a change too (it is gone).
            if i < len(items) and items[i]:
                snapshot[items[i]] = "%s-source:missing" % code
            i += 1
        snapshot[path] = "%s:%s" % (code, _fingerprint(os.path.join(cwd, path)))
    return snapshot


def tree_changes(before, after):
    """(changed paths, changed paths that already had uncommitted changes before)."""
    if before is None or after is None:
        return None, None
    # A file that could not be read either time may have changed: count it.
    changed = sorted(p for p in set(before) | set(after)
                     if before.get(p) != after.get(p)
                     or str(after.get(p, "")).endswith(":unreadable"))
    mixed = sorted(p for p in changed if p in before)
    return changed, mixed


# --------------------------------------------------------------------------
# Failures
#
# Matched against the tail of the CLI's own stderr and stdout. A category is a hint with
# evidence attached - the excerpt goes with it - never a guess from silence: empty stdout
# on its own says nothing (audit BUG-03 was exactly that guess).
# --------------------------------------------------------------------------

FAILURE_PATTERNS = (
    ("auth", r"invalid credential|unauthori[sz]ed|\b401\b|not logged in|log ?in required|"
             r"please (run .*)?log ?in|authenticat\w* (failed|error|required)|"
             r"token (has )?expired|invalid api key|incorrect api key|\b403\b"),
    ("quota", r"usage limit|quota|insufficient[_ ]credit|credit balance|billing|"
              r"you'?ve hit your|plan limit|exceeded your"),
    ("rate_limit", r"rate.?limit|\b429\b|too many requests"),
    ("invalid_model", r"model\W.{0,80}(not (found|supported|available)|does not exist|"
                      r"is not supported)|unknown model|invalid model|model_not_found|"
                      r"modelnotfound|providermodelnotfound|no such model|"
                      r"not supported when using"),
    ("provider_unavailable", r"at capacity|overloaded|\b50[0234]\b|service unavailable|"
                             r"unexpected server error|unknownerror|econnrefused|"
                             r"enotfound|etimedout|econnreset|fetch failed|socket hang up|"
                             r"network (error|is unreachable)|connection (reset|refused)|"
                             r"temporar(il)?y unavailable|stream disconnected"),
    ("cli_startup", r"command not found|cannot execute|cannot find module|"
                    r"error while loading shared|syntaxerror: |unrecognized (option|argument)|"
                    r"unexpected argument|unknown (option|argument)"),
)
_COMPILED = [(name, re.compile(pattern, re.I)) for name, pattern in FAILURE_PATTERNS]

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
SECRET = re.compile(
    r"(sk-[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]{8,}|"
    r"(?i:(?:api[_-]?key|token|secret|password)\s*[=:]\s*)\S+|[A-Za-z0-9+/_-]{40,})"
)


def sanitize(text, limit=1500):
    """The tail of `text`, without terminal codes or anything shaped like a credential."""
    text = ANSI.sub("", text or "").strip()
    text = SECRET.sub("<redacted>", text)
    return text[-limit:]


def classify_failure(*texts):
    blob = "\n".join(sanitize(t, 6000) for t in texts if t)
    for name, pattern in _COMPILED:
        if pattern.search(blob):
            return name
    return "unknown"


# What the orchestrator does next, by role and category. "fallback_sonnet" is only a
# permission: delegate also requires the agent to be confirmed gone before it says so.
RECOVERY = {
    "implement": {
        "auth": "fallback_sonnet", "quota": "fallback_sonnet",
        "rate_limit": "fallback_sonnet", "invalid_model": "fallback_sonnet",
        "provider_unavailable": "fallback_sonnet", "cli_startup": "fallback_sonnet",
        "cli_missing": "fallback_sonnet", "timeout": "fallback_sonnet",
        "unknown": "fallback_sonnet", "interrupted": "stop", "busy": "wait_or_stop",
        "error": "fallback_sonnet",
    },
    "review": {
        "auth": "blocked_reauth", "quota": "blocked_quota", "rate_limit": "retry_once_later",
        "invalid_model": "blocked_fix_model", "provider_unavailable": "retry_once",
        "cli_startup": "blocked_fix_cli", "cli_missing": "blocked_fix_cli",
        "timeout": "retry_once", "unknown": "retry_once", "interrupted": "stop",
        "busy": "wait_or_stop", "error": "blocked_fix_cli",
    },
}

ADVICE = {
    "auth": "The CLI is not logged in or its login expired. The user must re-authenticate "
            "(`opencode auth login` / `codex login`); retrying will fail the same way.",
    "quota": "The account's usage limit is exhausted. Do not retry until it resets.",
    "rate_limit": "Rate limited. One later retry is reasonable; a loop is not.",
    "invalid_model": "The model id is not offered to this account or CLI version. Run "
                     "`orch models status` to see what is.",
    "provider_unavailable": "The provider failed or is at capacity. Not a code problem.",
    "cli_startup": "The CLI failed to start or rejected its arguments. See the excerpt.",
    "cli_missing": "The CLI is not installed or not on PATH.",
    "timeout": "The run hit its timeout and was terminated with its whole process tree.",
    "interrupted": "The run was cancelled by a signal to the dispatcher. It was terminated; "
                   "do not continue automatically.",
    "unknown": "The CLI exited with an error that matched no known cause. See the excerpt.",
    "busy": "Another delegated agent is still running in this repository.",
    "error": "The CLI could not be started.",
}


def recovery_for(role, category):
    table = RECOVERY["implement" if role in WRITER_MODES else "review"]
    return table.get(category, "stop")


# --------------------------------------------------------------------------
# Models
#
# Claude models are aliases (`opus`, `sonnet`) and need nothing here. OpenCode and Codex
# models are ids that come and go with providers and CLI versions, so the configured id
# is checked against the CLI's own catalog - cached for a day, never fetched over the
# network on the task path - before a run is spent on it.
# --------------------------------------------------------------------------

CATALOG_TTL = 24 * 3600


def user_models():
    return read_json(config_dir() / "models.json", {}) or {}


def _binary_key(name):
    path = shutil.which(name)
    if not path:
        return None
    try:
        real = os.path.realpath(path)
        return "%s:%d" % (real, os.stat(real).st_mtime_ns)
    except OSError:
        return None


CATALOG_SECONDS = 20

# Set by the dispatcher before it queries a catalog, so the query (and anything it starts)
# carries the run marker and the run's watchdog stops it if the dispatcher dies mid-query.
QUERY_MARKER = {}


def _kill_group(proc):
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        pass


def _query(argv):
    """stdout of a catalog query, or None.

    Bounded by a timeout; its whole process group is killed on the timeout and on any
    exception, including a stop signal to the caller; and it carries a parent-death signal,
    so even a SIGKILLed caller cannot leave it running. (An early version left four
    orphaned stub queries running for half an hour when a dispatcher was killed mid-check.)
    """
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, start_new_session=True,
                            cwd=str(private(state_dir())), env=dict(os.environ, **QUERY_MARKER),
                            preexec_fn=lambda: _set_parent_death_signal(signal.SIGKILL))
    try:
        out, _ = proc.communicate(timeout=CATALOG_SECONDS)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        return None
    except BaseException:
        _kill_group(proc)
        raise
    return out.decode(TEXT, "replace") if proc.returncode == 0 else None


def _list_catalog(agent, provider):
    if agent == "opencode":
        out = _query(["opencode", "models", provider])
        if out is None:
            return None
        ids = [line.strip() for line in out.splitlines()]
        return [i for i in ids if "/" in i and " " not in i] or None   # empty: no answer
    out = _query(["codex", "debug", "models"])
    if out is None:
        return None
    data = json.loads(out)
    models = data.get("models", data) if isinstance(data, dict) else data
    return [m["slug"] for m in models
            if isinstance(m, dict) and m.get("slug") and m.get("visibility") != "hide"] or None


def catalog(agent, provider="", refresh=False):
    """(model ids the CLI offers, age in seconds) or (None, None) when it cannot say.

    FRAPPE_ORCHESTRATOR_CATALOG=off disables the check (offline use, test stubs); every
    model then counts as "unknown" and runs, and the run itself reports a bad id.
    """
    if os.environ.get("FRAPPE_ORCHESTRATOR_CATALOG") == "off":
        return None, None
    key = _binary_key(agent)
    if key is None:
        return None, None
    cache_path = state_dir() / "catalog-cache.json"
    cache = read_json(cache_path, {}) or {}
    slot = "%s:%s" % (agent, provider)
    entry = cache.get(slot)
    now = time.time()
    if (not refresh and isinstance(entry, dict) and entry.get("binary") == key
            and now - entry.get("at", 0) < CATALOG_TTL and isinstance(entry.get("ids"), list)):
        return entry["ids"], now - entry["at"]
    try:
        ids = _list_catalog(agent, provider)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        ids = None
    if ids is None:
        return None, None
    cache[slot] = {"binary": key, "at": now, "ids": ids}
    try:
        write_json(cache_path, cache)
    except OSError:
        pass
    return ids, 0.0


def catalog_status(agent, model_id):
    """'present', 'absent' or 'unknown' (catalog unavailable)."""
    provider = model_id.split("/", 1)[0] if agent == "opencode" else ""
    ids, _age = catalog(agent, provider)
    if ids is None:
        return "unknown"
    return "present" if model_id in ids else "absent"


def opencode_model(routing):
    """(model id, source, notes) for the next OpenCode implementation.

    A promoted model from the user's config wins while the catalog still offers it. If it
    disappears, the run goes back to the stable model in the routing file and says so - the
    one switch this makes on its own, and only ever to the known-good default.
    """
    stable = routing["implementers"]["opencode"]["stable_model"]
    notes = []
    promoted = user_models().get("opencode_model")
    if promoted and promoted != stable:
        state = catalog_status("opencode", promoted)
        if state != "absent":
            return promoted, "promoted", notes
        notes.append("promoted model %s is no longer in the OpenCode catalog; using the "
                     "stable model %s" % (promoted, stable))
    return stable, "stable", notes


def codex_config_model():
    """The top-level `model` in ~/.codex/config.toml, or None. Reads only that one line."""
    home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    try:
        text = Path(home, "config.toml").read_text(encoding=TEXT)
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("["):
            break
        found = re.match(r'model\s*=\s*"([^"]+)"', stripped)
        if found:
            return found.group(1)
    return None


def codex_model(routing):
    """(model id or None, source). None means Codex's own default, which is unknown here."""
    pinned = user_models().get("codex_model") or routing["review"].get("codex_model")
    if pinned:
        return pinned, "pinned"
    configured = codex_config_model()
    return configured, "codex config.toml" if configured else "codex default"


def record_outcome(agent, model_id, status, category, seconds):
    """Operational availability: what actually happened the last times a model ran."""
    if not model_id:
        return
    path = state_dir() / "model-health.json"
    try:
        health = read_json(path, {}) or {}
        entry = health.setdefault("%s:%s" % (agent, model_id), {
            "completed": 0, "failed": 0, "last_failure": None, "last_success": None})
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        if status == "completed":
            entry["completed"] += 1
            entry["last_success"] = now
        else:
            entry["failed"] += 1
            entry["last_failure"] = {"at": now, "status": status, "category": category}
        entry["last_seconds"] = round(seconds or 0, 1)
        write_json(path, health)
    except (OSError, ValueError, TypeError, AttributeError):
        pass


def append_metric(record):
    try:
        path = private(state_dir()) / "metrics.jsonl"
        with open(path, "a", encoding=TEXT) as out:
            out.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        pass


# --------------------------------------------------------------------------
# Review gate
#
# Codex review is the slow half of a task (median ~135 s in the audit), so it runs when
# the change carries real risk, not because a change happened. The decision is made from
# the actual diff against data in the routing file's `review` block, so it is the same
# every time and can be tested. The orchestrator may always ask for more review than the
# gate requires; it may not skip a review the gate marks required.
# --------------------------------------------------------------------------

# File kinds. Line rules read the files whose text runs; templates get their own rules
# (below); prose, styles, images, translations and data are judged by path, plus any
# trigger that opts in with `code_only: false`. Anything else is a file the gate does not
# understand, and a change it does not understand is not one it can call low-risk.
CODE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx", ".vue", ".sql", ".mjs", ".cjs",
                 ".sh", ".bash", ".zsh")
TEMPLATE_SUFFIXES = (".html", ".htm", ".jinja", ".jinja2", ".j2")
PATH_ONLY_SUFFIXES = (".json", ".md", ".rst", ".txt", ".csv", ".css", ".scss", ".sass",
                      ".less", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
                      ".bmp", ".woff", ".woff2", ".ttf", ".otf", ".eot", ".po", ".pot",
                      ".mo", ".map", ".toml", ".cfg", ".ini", ".yml", ".yaml", ".lock",
                      ".xml", ".pdf")
PATH_ONLY_NAMES = (".gitignore", ".gitattributes", ".editorconfig", ".flake8", ".eslintrc",
                   ".eslintignore", ".prettierrc", ".prettierignore", ".nvmrc",
                   ".python-version", ".stylelintrc", ".browserslistrc", ".npmignore",
                   "MANIFEST.in")
PATH_ONLY_STEMS = ("LICENSE", "LICENCE", "README", "CHANGELOG", "CONTRIBUTING", "AUTHORS")
CONTEXT_LIMIT = 2 * 1024 * 1024
GATE_LEVELS = ("mandatory", "risk", "advisory")
TRIGGER_FIELDS = {"name": str, "level": str, "paths": list, "lines": list,
                  "added_lines": list, "removed_lines": list, "require_both": bool,
                  "code_only": bool, "note": str}
TIER_FIELDS = ("effort", "expected_max_files", "expected_max_lines")


def file_kind(path):
    name = path.rsplit("/", 1)[-1]
    lower = name.lower()
    if lower.endswith(CODE_SUFFIXES):
        return "code"
    if lower.endswith(TEMPLATE_SUFFIXES):
        return "template"
    if lower.endswith(PATH_ONLY_SUFFIXES) or name in PATH_ONLY_NAMES:
        return "path"
    if name.split(".")[0].upper() in PATH_ONLY_STEMS:
        return "path"
    return "unknown"


def validate_review_policy(routing, tier=None):
    """Problems with the routing file's `review` block, as sentences; [] if it is usable.

    A misspelt level or key would otherwise make a trigger match nothing, and a gate that
    matches nothing says "not_required"."""
    policy = routing.get("review") if isinstance(routing, dict) else None
    if not isinstance(policy, dict):
        return ["the routing file has no review block"]
    problems = []
    tiers = policy.get("tiers")
    if not isinstance(tiers, dict):
        problems.append("review.tiers is missing")
    else:
        for name in ("FAST", "SMALL", "NORMAL", "DIFFICULT"):
            entry = tiers.get(name)
            if not isinstance(entry, dict):
                problems.append("review.tiers.%s is missing" % name)
                continue
            for key in TIER_FIELDS:
                value = entry.get(key)
                ok = isinstance(value, str) if key == "effort" else (
                    isinstance(value, int) and not isinstance(value, bool))
                if not ok:
                    problems.append("review.tiers.%s.%s is %r" % (name, key, value))
        if tier is not None and tier not in tiers:
            problems.append("tier %r has no review policy" % tier)
    triggers = policy.get("triggers")
    if not isinstance(triggers, list) or not triggers:
        return problems + ["review.triggers is missing or empty"]
    seen = set()
    for index, trigger in enumerate(triggers):
        if not isinstance(trigger, dict):
            problems.append("review trigger %d is not an object" % index)
            continue
        name = trigger.get("name")
        label = "review trigger %r" % name if isinstance(name, str) else "review trigger %d" % index
        if not isinstance(name, str) or not name:
            problems.append("%s has no name" % label)
        elif name in seen:
            problems.append("%s is defined twice" % label)
        seen.add(name)
        if trigger.get("level") not in GATE_LEVELS:
            problems.append("%s has level %r, not one of %s"
                            % (label, trigger.get("level"), ", ".join(GATE_LEVELS)))
        for key, value in trigger.items():
            if key.startswith("_"):
                continue   # compiled-pattern caches
            if key not in TRIGGER_FIELDS:
                problems.append("%s has unknown key %r" % (label, key))
            elif not isinstance(value, TRIGGER_FIELDS[key]):
                problems.append("%s: %s must be a %s" % (label, key, TRIGGER_FIELDS[key].__name__))
        rules = [k for k in ("lines", "added_lines", "removed_lines") if trigger.get(k)]
        for key in ["paths"] + rules:
            for pattern in trigger.get(key) or [] if isinstance(trigger.get(key), list) else []:
                if not isinstance(pattern, str) or not pattern:
                    problems.append("%s: %s holds %r" % (label, key, pattern))
                elif key != "paths":
                    try:
                        re.compile(pattern)
                    except re.error as exc:
                        problems.append("%s: %s pattern %r does not compile: %s"
                                        % (label, key, pattern, exc))
        if not trigger.get("paths") and not rules:
            problems.append("%s has no paths and no line patterns" % label)
        if trigger.get("require_both") and not (trigger.get("paths") and rules):
            problems.append("%s sets require_both without both paths and line patterns" % label)
    return problems


def head(cwd):
    out = git(cwd, "rev-parse", "--verify", "-q", "HEAD")
    return out.strip() if out else None


def committed_files(cwd, before, after):
    """Paths that differ between two commits; [] if they are the same, None if unknown."""
    if before == after:
        return []
    if not before or not after:
        return None
    out = git(cwd, "-c", "core.quotePath=false", "diff", "--name-only", "--no-renames",
              "--no-relative", "-z", before, after)
    return None if out is None else sorted(p for p in out.split("\0") if p)


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _diff_path(text, prefix):
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        text = codecs.escape_decode(text[1:-1].encode(TEXT))[0].decode(TEXT, "replace")
    if text == "/dev/null":
        return None
    return text[len(prefix):] if text.startswith(prefix) else text


def _header_path(rest):
    """The path in `diff --git a/P b/P`. With --no-renames both sides name the same file."""
    if rest.startswith('"'):
        end = rest.find('" ', 1)
        return _diff_path(rest[:end + 1], "a/") if end > 0 else None
    half = (len(rest) - 1) // 2
    left, right = rest[:half], rest[half + 1:]
    if left.startswith("a/") and right.startswith("b/") and left[2:] == right[2:]:
        return left[2:]
    return None


def _entry():
    return {"added": [], "removed": [], "touched": set(), "binary": False,
            "deleted": False, "new": False}


def _meaningful(line):
    text = line.strip()
    return bool(text) and not text.startswith("#")


def parse_diff(text):
    """{path: change} from a unified diff (-U0, --no-renames).

    A change holds its added and removed lines, `touched` - the line numbers in the new file
    that a non-blank, non-comment change landed on or next to - and flags. Every file in a
    `diff --git` header is recorded, including binary, mode-only and empty ones, which
    carry no +++ line: a file the parser skipped would be a file the gate never judged.
    """
    files, current, header = {}, None, False
    hunk = None   # [first new line, count, meaningful removal seen]

    def close_hunk():
        if current is not None and hunk and hunk[2]:
            start, count = hunk[0], max(hunk[1], 1)
            current["touched"].update(range(start, start + count + 1))

    for line in text.splitlines():
        if line.startswith("diff --git "):
            close_hunk()
            hunk, header = None, True
            path = _header_path(line[len("diff --git "):])
            current = files.setdefault(path, _entry()) if path else None
            continue
        if header and not line.startswith("@@"):
            # File headers come only before the first hunk: a removed line reading "-- x"
            # is content, not a header.
            if line.startswith("+++ "):
                path = _diff_path(line[4:], "b/")
                if path is None:
                    if current is not None:
                        current["deleted"] = True
                else:
                    current = files.setdefault(path, current or _entry())
            elif line.startswith("--- "):
                path = _diff_path(line[4:], "a/")
                if path is None:
                    if current is not None:
                        current["new"] = True
                elif current is None:
                    current = files.setdefault(path, _entry())
            elif line.startswith("Binary files ") and current is not None:
                current["binary"] = True
            elif line.startswith("deleted file mode") and current is not None:
                current["deleted"] = True
            elif line.startswith("new file mode") and current is not None:
                current["new"] = True
            continue
        if line.startswith("@@"):
            close_hunk()
            header = False
            match = _HUNK.match(line)
            hunk = [int(match.group(1)), int(match.group(2) or "1"), False] if match else None
            next_line = hunk[0] if hunk else 0
            continue
        if current is None:
            continue
        if line.startswith("+"):
            current["added"].append(line[1:])
            if _meaningful(line[1:]):
                current["touched"].add(next_line)
            next_line += 1
        elif line.startswith("-"):
            current["removed"].append(line[1:])
            if hunk and _meaningful(line[1:]):
                hunk[2] = True
    close_hunk()
    return files


def _read_bytes(top, path, limit):
    """(bytes, None) or (None, why not)."""
    full = os.path.join(top, path)
    try:
        info = os.lstat(full)
    except OSError:
        return None, "could not be read"
    if stat.S_ISLNK(info.st_mode):
        return None, "is a symbolic link; its target was not inspected"
    if not stat.S_ISREG(info.st_mode):
        return None, "is not a regular file"
    if info.st_size > limit:
        return None, "is larger than %d MB; not inspected" % (limit // (1024 * 1024))
    try:
        with open(full, "rb") as handle:
            return handle.read(limit + 1), None
    except OSError:
        return None, "could not be read"


def _collect(top, base, files):
    """(changes, gaps) for the diff against `base` plus untracked files, or None if git
    could not answer. `gaps` is [(path, why)] for files whose content was not inspected.
    `files` narrows to those paths; an empty list means nothing changed."""
    if files is not None and not files:
        return {}, []
    args = ["--literal-pathspecs", "-c", "core.quotePath=false", "diff", "--no-color",
            "--no-ext-diff", "--no-renames", "--no-relative", "--src-prefix=a/",
            "--dst-prefix=b/", "-U0", base]
    if files is not None:
        args += ["--"] + list(files)
    tracked = git(top, *args)
    if tracked is None:
        return None
    untracked = git(top, "-c", "core.quotePath=false", "ls-files", "--others",
                    "--exclude-standard", "-z")
    if untracked is None:
        return None
    changes, gaps = parse_diff(tracked), []
    wanted = set(files) if files is not None else None
    for path in [p for p in untracked.split("\0") if p]:
        if wanted is not None and path not in wanted:
            continue
        entry = changes.setdefault(path, _entry())
        entry["new"] = True
        data, why = _read_bytes(top, path, CONTEXT_LIMIT)
        if why:
            gaps.append((path, why))
        elif b"\0" in data[:8192]:
            entry["binary"] = True
        else:
            entry["added"] = data.decode(TEXT, "replace").splitlines()
            entry["touched"] = {n for n, line in enumerate(entry["added"], 1) if _meaningful(line)}
    return changes, gaps


def _compiled(trigger, key):
    cache = "_" + key
    if cache not in trigger:
        trigger[cache] = [re.compile(p, re.I) for p in trigger.get(key, [])]
    return trigger[cache]


def _matches_trigger(trigger, path, change):
    """Evidence (a line, or the path) that `trigger` applies to this file's change, or None.

    `lines` match added or removed lines, `added_lines` / `removed_lines` only one side -
    so "a field was removed or retyped" and "a field was added" can carry different weight.
    Line patterns apply to code files only unless the trigger sets `code_only: false`.
    """
    globs = trigger.get("paths") or []
    path_hit = any(fnmatch.fnmatch(path, g) for g in globs)
    sides = (("lines", change["added"] + change["removed"]),
             ("added_lines", change["added"]), ("removed_lines", change["removed"]))
    has_line_rules = any(trigger.get(key) for key, _ in sides)
    line_hit = None
    if has_line_rules and (file_kind(path) == "code" or not trigger.get("code_only", True)):
        for key, lines in sides:
            patterns = _compiled(trigger, key)
            line_hit = next((ln for ln in lines for p in patterns if p.search(ln)), None)
            if line_hit:
                break
    if globs and has_line_rules and trigger.get("require_both"):
        return line_hit if path_hit and line_hit else None
    return line_hit or ("(path) %s" % path if path_hit else None)


# --------------------------------------------------------------------------
# Frappe context rules
#
# A diff line alone does not say whether it sits inside a whitelisted endpoint, a public
# web page or a permission check, so for Python files the changed line numbers are mapped
# onto the functions of the new file, and a changed function is judged by its whole body.
# Targeted on purpose: only endpoints, page controllers and access-control functions are
# looked at, and an endpoint that touches no data stays advisory.
# --------------------------------------------------------------------------

ENDPOINT_EFFECTS = (
    ("reads records", re.compile(
        r"frappe\.(get_all|get_list|get_doc|get_cached_doc|get_last_doc|get_single|"
        r"get_value|get_cached_value|get_meta|get_single_value)\s*\(|frappe\.db\.\w+|"
        r"frappe\.qb\b|\.as_dict\s*\(|\.(get_list|get_all|get_value)\s*\(")),
    ("writes records", re.compile(
        r"\.(save|insert|submit|cancel|delete|db_set|db_insert|db_update|run_method)\s*\(|"
        r"frappe\.(new_doc|delete_doc|rename_doc|copy_doc)\s*\(")),
    ("touches permissions", re.compile(
        r"ignore_permissions|ignore_user_permissions|frappe\.set_user|flags\.ignore_|"
        r"only_for|has_permission|check_permission|frappe\.session\b")),
    ("runs dynamic code, files or processes", re.compile(
        r"\b(eval|exec|safe_eval|getattr|setattr|__import__)\s*\(|"
        r"frappe\.(get_attr|call|get_hooks)\s*\(|\bsubprocess\b|"
        r"\bos\.(system|popen|remove|unlink|rmdir|rename)\b|\bshutil\.|\bopen\s*\(|"
        r"get_site_path|get_files_path")),
    ("shapes the HTTP response", re.compile(
        r"frappe\.(local\.)?response\b|respond_as_web_page|frappe\.redirect|send_file|"
        r"download_file|frappe\.sendmail")),
)
ACCESS_FUNCTION = re.compile(
    r"perm|authori[sz]|authenticat|log_?in|log_?out|query_conditions|"
    r"(^|_)(roles?|owner|guest|session|access|allowed|can)(_|$)", re.I)
# Public by default: www pages, web forms and page templates run for any visitor.
WEB_CONTROLLERS = ("www/*.py", "*/www/*.py", "*/templates/pages/*.py", "*/web_form/*/*.py")
TEMPLATE_DATA = re.compile(
    r"frappe\.(get_all|get_list|get_doc|get_cached_doc|get_value|get_single|db|call|"
    r"session|form_dict)\b|ignore_permissions")
TEMPLATE_RAW = re.compile(r"\|\s*safe\b|autoescape\s+false", re.I)
TEMPLATE_EXPRESSION = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}")
TRANSLATION_ONLY = re.compile(r"^\s*_\(\s*(['\"]).*\1\s*\)\s*$")


def _decorator(node):
    """(dotted name, allows guests) of one decorator."""
    target = node.func if isinstance(node, ast.Call) else node
    parts = []
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    guest = isinstance(node, ast.Call) and any(
        kw.arg == "allow_guest" and not (isinstance(kw.value, ast.Constant)
                                         and kw.value.value is False)
        for kw in node.keywords)
    return ".".join(reversed(parts)), guest


def _effects(text):
    return [label for label, pattern in ENDPOINT_EFFECTS if pattern.search(text)]


def _python_context(top, path, change):
    """([(trigger, level, evidence)], gap or None) for one changed Python file."""
    if change["deleted"] or not change["touched"]:
        return [], None
    data, why = _read_bytes(top, path, CONTEXT_LIMIT)
    if why:
        return [], why
    source = data.decode(TEXT, "replace")
    web = any(fnmatch.fnmatch(path, g) for g in WEB_CONTROLLERS)
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        if web or "whitelist" in source or ACCESS_FUNCTION.search(source):
            return [], "does not parse as Python, so its endpoints could not be checked"
        return [], None
    lines = source.splitlines()
    touched, found, inside = change["touched"], [], set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = min([d.lineno for d in node.decorator_list] + [node.lineno])
        end = getattr(node, "end_lineno", None) or node.lineno
        inside.update(range(start, end + 1))
        hit = sorted(n for n in touched if start <= n <= end)
        if not hit:
            continue
        decorators = [_decorator(d) for d in node.decorator_list]
        whitelisted = any(name.split(".")[-1] == "whitelist" for name, _ in decorators)
        guest = any(g for name, g in decorators if name.split(".")[-1] == "whitelist")
        where = "%s:%d %s()" % (path, hit[0], node.name)
        if ACCESS_FUNCTION.search(node.name):
            found.append(("access-control-logic", "mandatory", "%s changed" % where))
        if not (whitelisted or web):
            continue
        kind = "whitelisted endpoint" if whitelisted else "public web page code"
        effects = (["allows guests"] if guest else []) + _effects(
            "\n".join(lines[start - 1:end]))
        if effects:
            found.append(("sensitive-endpoint", "mandatory",
                          "%s %s: %s" % (kind, where, ", ".join(effects))))
        else:
            found.append(("api-surface", "advisory",
                          "%s %s changed; it reads and writes nothing" % (kind, where)))
    if web:
        outside = [n for n in touched if n not in inside]
        module = "\n".join(line for n, line in enumerate(lines, 1) if n not in inside)
        if outside and _effects(module):
            found.append(("sensitive-endpoint", "mandatory", "public web page code %s:%d: %s"
                          % (path, outside[0], ", ".join(_effects(module)))))
    return found, None


def _renders(line):
    for match in TEMPLATE_EXPRESSION.finditer(line):
        body = match.group(1) if match.group(1) is not None else match.group(2)
        if not TRANSLATION_ONLY.match(body):
            return True
    return False


def _template_context(top, path, change):
    """Template rules: data access or unescaped output in the change itself, or a changed
    expression in a template that queries data. Markup and text edits pass."""
    lines = change["added"] + change["removed"]
    found = []
    raw = next((ln for ln in lines if TEMPLATE_RAW.search(ln)), None)
    if raw:
        found.append(("template-unescaped-output", "mandatory", raw))
    data = next((ln for ln in lines if TEMPLATE_DATA.search(ln)), None)
    if data:
        found.append(("sensitive-template", "mandatory", data))
        return found, None
    rendered = next((ln for ln in lines if _renders(ln)), None)
    if rendered is None or change["deleted"]:
        return found, None
    content, why = _read_bytes(top, path, CONTEXT_LIMIT)
    if why:
        return found, why
    if TEMPLATE_DATA.search(content.decode(TEXT, "replace")):
        found.append(("sensitive-template", "mandatory",
                      "changed output in a template that queries data: %s" % rendered))
    return found, None


def _evaluate(top, policy, changes, gaps):
    """(triggers, unevaluated) for a set of changes. One trigger entry per name."""
    triggers, names = [], set()

    def add(name, level, path, evidence):
        if name not in names:
            names.add(name)
            triggers.append({"name": name, "level": level, "file": path,
                             "evidence": evidence.strip()[:160]})

    for trigger in policy["triggers"]:
        for path, change in sorted(changes.items()):
            hit = _matches_trigger(trigger, path, change)
            if hit:
                add(trigger["name"], trigger["level"], path, hit)
                break
    mandatory = [t for t in policy["triggers"] if t["level"] == "mandatory"]
    unevaluated = [{"file": path, "why": why} for path, why in gaps]
    gap_files = {path for path, _ in gaps}
    for path, change in sorted(changes.items()):
        kind = file_kind(path)
        covered = any(_matches_trigger(t, path, change) for t in mandatory)
        if kind == "unknown" or (change["binary"] and kind in ("code", "template")):
            if path not in gap_files and not covered:
                unevaluated.append({"file": path, "why": "binary content" if change["binary"]
                                    else "a file type the gate does not assess"})
            continue
        found, why = [], None
        if kind == "code" and path.endswith(".py"):
            found, why = _python_context(top, path, change)
        elif kind == "template":
            found, why = _template_context(top, path, change)
        for name, level, evidence in found:
            add(name, level, path, evidence)
        if why and path not in gap_files:
            unevaluated.append({"file": path, "why": why})
    return triggers, unevaluated


def _invalid_files(top, changes):
    """Changed .py and .json files that do not parse: a correctness failure the orchestrator
    sends back to the implementer, found here so a FAST task needs no separate check."""
    bad = []
    for path, change in sorted(changes.items()):
        lower = path.lower()
        if change["deleted"] or change["binary"] or not lower.endswith((".py", ".json")):
            continue
        data, why = _read_bytes(top, path, CONTEXT_LIMIT)
        if why:
            continue   # already reported as not assessed where it matters
        text = data.decode(TEXT, "replace")
        try:
            if lower.endswith(".py"):
                with warnings.catch_warnings():   # e.g. invalid escapes: not our finding
                    warnings.simplefilter("ignore")
                    compile(text, path, "exec", dont_inherit=True)   # parses; runs nothing
            else:
                json.loads(text)
        except (SyntaxError, ValueError) as exc:
            bad.append({"file": path, "error": str(exc)[:200]})
    return bad


def gate_failure(tier, why, status="error"):
    """A gate result for when the gate itself could not run: review required."""
    return {"review": "required", "gate_status": status, "tier": tier, "reasons": [why],
            "advisories": [], "triggers": [], "unevaluated": [], "invalid_files": [],
            "effort": "high",
            "files": [], "lines_changed": None, "code_lines_changed": None,
            "reclassify": None}


def review_gate(cwd, tier, routing, files=None, base="HEAD", files_claimed=False,
                tests_failed=False, fix_rounds=0, user_requested=False):
    """Whether this change needs an independent review, and why. Never raises.

    `gate_status` is "complete" only when every changed file was assessed; "incomplete"
    or "error" always come with `review: required`. `files` narrows the gate to the
    files a run was measured to change. `files_claimed` marks a list someone supplied
    (`orch gate --files`): the whole diff is still assessed, and a risk found outside the
    list requires a review, since the list may be incomplete.
    """
    try:
        problems = validate_review_policy(routing, tier)
        if problems:
            return gate_failure(tier, "the review configuration is invalid: %s"
                                % "; ".join(problems[:5]))
        return _review_gate(cwd, tier, routing, files, base, files_claimed, tests_failed,
                            fix_rounds, user_requested)
    except Exception as exc:   # noqa: BLE001 - a gate that crashed has assessed nothing
        return gate_failure(tier, "the review gate failed: %s: %s" % (type(exc).__name__, exc))


def _review_gate(cwd, tier, routing, files, base, files_claimed, tests_failed, fix_rounds,
                 user_requested):
    policy = routing["review"]
    tier_policy = policy["tiers"][tier]
    top = git(cwd, "rev-parse", "--show-toplevel")
    if top is None:
        return gate_failure(tier, "git could not read the repository at %s" % cwd,
                            "incomplete")
    top = top.strip()
    claim = None
    if files is not None:
        files = [os.path.normpath(f) for f in files]
        if files_claimed:
            claim, files = set(files), None
    collected = _collect(top, base, files)
    if collected is None:
        return gate_failure(tier, "the diff against %s could not be read, so risk could not "
                            "be assessed" % base, "incomplete")
    changes, gaps = collected
    outside, outside_gaps = {}, []
    if claim is not None:
        outside = {p: c for p, c in changes.items() if p not in claim}
        outside_gaps = [g for g in gaps if g[0] not in claim]
        changes = {p: c for p, c in changes.items() if p in claim}
        gaps = [g for g in gaps if g[0] in claim]

    triggers, unevaluated = _evaluate(top, policy, changes, gaps)
    code_lines = sum(len(c["added"]) + len(c["removed"]) for p, c in changes.items()
                     if file_kind(p) == "code")
    total_lines = sum(len(c["added"]) + len(c["removed"]) for c in changes.values())

    reasons, advisories = [], []
    mandatory = [t for t in triggers if t["level"] == "mandatory"]
    risk = [t for t in triggers if t["level"] == "risk"]
    advisories += ["advisory: %s (%s)" % (t["name"], t["file"])
                   for t in triggers if t["level"] == "advisory"]
    if user_requested:
        reasons.append("the user asked for a review")
    if tests_failed:
        reasons.append("tests failed unexpectedly during the task")
    if fix_rounds >= 2:
        reasons.append("the implementation needed %d corrections" % fix_rounds)
    reasons += ["mandatory: %s (%s)" % (t["name"], t["file"]) for t in mandatory]
    reasons += ["not assessed: %s (%s)" % (u["file"], u["why"]) for u in unevaluated]
    over = (len(changes) > tier_policy["expected_max_files"]
            or total_lines > tier_policy["expected_max_lines"])
    if over:
        note = "the diff (%d files, %d lines) exceeds what a %s task expects" % (
            len(changes), total_lines, tier)
        (reasons if tier in ("SMALL", "NORMAL") else advisories).append(note)
    if tier in ("NORMAL", "DIFFICULT") and risk:
        reasons += ["risk: %s (%s)" % (t["name"], t["file"]) for t in risk]
    elif risk:
        advisories += ["risk: %s (%s)" % (t["name"], t["file"]) for t in risk]
    if tier == "DIFFICULT" and code_lines >= tier_policy.get("significant_code_lines", 10):
        reasons.append("a significant code change on a DIFFICULT task")
    if outside or outside_gaps:
        out_triggers, out_unevaluated = _evaluate(top, policy, outside, outside_gaps)
        for t in out_triggers:
            line = "outside the given files: %s %s (%s) - the file list may be incomplete" % (
                t["level"], t["name"], t["file"])
            # The same tier rule as inside the list: risk forces review on NORMAL/DIFFICULT.
            forces = t["level"] == "mandatory" or (
                t["level"] == "risk" and tier in ("NORMAL", "DIFFICULT"))
            (reasons if forces else advisories).append(line)
        advisories += ["outside the given files, not assessed: %s (%s)" % (u["file"], u["why"])
                       for u in out_unevaluated]
        advisories.append("changed but not in the given files: %s" % ", ".join(sorted(outside)))
    if claim is not None:
        missing = sorted(claim - set(changes))
        if missing:
            advisories.append("given but unchanged against %s: %s" % (base, ", ".join(missing)))
    if not changes and not outside and not gaps:
        advisories.append("no change in the diff")

    effort = policy["tiers"]["DIFFICULT"]["effort"] if mandatory else tier_policy["effort"]
    return {
        "review": "required" if reasons else "not_required",
        "gate_status": "incomplete" if unevaluated else "complete",
        "tier": tier,
        "base": base,
        "reasons": reasons,
        "advisories": advisories,
        "triggers": triggers,
        "unevaluated": unevaluated,
        "invalid_files": _invalid_files(top, changes),
        "effort": effort,
        "files": sorted(changes),
        "lines_changed": total_lines,
        "code_lines_changed": code_lines,
        "reclassify": "%s looks larger than its tier" % tier if over and tier == "FAST" else None,
    }


def _mark_incomplete(gate, why):
    if gate.get("gate_status") != "error":
        gate["gate_status"] = "incomplete"
    gate["reasons"].insert(0, why)
    gate["review"] = "required"
    return gate


def implementation_gate(cwd, tier, routing, changed, head_before, head_after):
    """The gate for a delegated implementation, from what the dispatcher measured: the
    files the run changed in the working tree, plus anything it committed."""
    if changed is None:
        return _mark_incomplete(review_gate(cwd, tier, routing),
                                "the working-tree snapshot failed, so what the run changed "
                                "is unknown; the whole diff was assessed instead")
    if head_before is None or head_after is None:
        return _mark_incomplete(review_gate(cwd, tier, routing, files=changed),
                                "HEAD could not be read before and after the run, so commits "
                                "made during it cannot be ruled out")
    files, base, moved = set(changed), "HEAD", None
    if head_before != head_after:
        committed = committed_files(cwd, head_before, head_after)
        if committed is None:
            return _mark_incomplete(review_gate(cwd, tier, routing, files=changed),
                                    "HEAD moved during the run and the commits could not "
                                    "be read")
        files |= set(committed)
        base = head_before
        moved = "HEAD moved during the run (%s -> %s); assessed against the starting commit" % (
            head_before[:12], head_after[:12])
    gate = review_gate(cwd, tier, routing, files=sorted(files), base=base)
    if moved and gate.get("gate_status") != "error":
        gate["reasons"].append(moved)
        gate["review"] = "required"
    return gate


# --------------------------------------------------------------------------
# Sites
# --------------------------------------------------------------------------


def sites_file():
    return config_dir() / "sites.json"


def load_sites():
    data = read_json(sites_file(), {}) or {}
    return {
        "development": sorted(set(data.get("development") or [])),
        "protected": sorted(set(data.get("protected") or [])),
    }

