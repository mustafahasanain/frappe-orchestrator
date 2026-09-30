#!/usr/bin/env python3
"""Tests for the development report script.

    python3 tests/test_dev_report.py

What earns coverage here is what would put a wrong fact in a report without anyone
noticing: a commit from the wrong day, a rename counted as a delete and an add, lock-file
churn reported as work, and content that cites a commit which does not exist. A broken
layout is caught by looking at the PDF; these are not.

The collector runs against a throwaway repository whose commit times are set explicitly,
so the day boundary is tested in the machine's own timezone, the one the script uses.
Rendering is exercised end to end only when Chrome and poppler are installed.

No framework and nothing to install: standard library only.
"""

import datetime as dt
import importlib.machinery
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "dev-report"


def load_script():
    """Import scripts/dev-report, which has no .py extension, without running it."""
    loader = importlib.machinery.SourceFileLoader("dev_report", str(SCRIPT))
    spec = importlib.util.spec_from_loader("dev_report", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


r = load_script()
DAY = dt.date(2026, 3, 10)


def local_stamp(day, hour, minute):
    """A git date string for a local wall-clock time, with the local offset."""
    epoch = time.mktime((day.year, day.month, day.day, hour, minute, 0, 0, 0, -1))
    return "@%d %s" % (epoch, dt.datetime.fromtimestamp(epoch).astimezone().strftime("%z"))


def run(cmd, cwd, env=None):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, check=True)


def commit(repo, message, stamp):
    env = dict(os.environ, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    run(["git", "add", "--", "."], repo)  # a throwaway repo; the guard rule is for real ones
    run(["git", "commit", "-q", "-m", message], repo, env)


def build_repo(repo):
    run(["git", "init", "-q", "-b", "main"], repo)
    run(["git", "config", "user.name", "Test"], repo)
    run(["git", "config", "user.email", "test@example.com"], repo)
    (repo / "app").mkdir()

    (repo / "app" / "old_name.py").write_text("x = 1\n" * 20)
    commit(repo, "feat: yesterday, one minute before midnight",
           local_stamp(DAY - dt.timedelta(days=1), 23, 59))

    (repo / "app" / "old_name.py").rename(repo / "app" / "new_name.py")
    (repo / "package-lock.json").write_text("{}\n" * 500)
    commit(repo, "refactor: rename at midnight", local_stamp(DAY, 0, 0))

    run(["git", "checkout", "-q", "-b", "side"], repo)
    (repo / "app" / "side.py").write_text("y = 2\n")
    commit(repo, "feat: on a side branch", local_stamp(DAY, 12, 0))
    run(["git", "checkout", "-q", "main"], repo)
    (repo / "README.md").write_text("hello\n")
    commit(repo, "docs: on main", local_stamp(DAY, 13, 0))
    env = dict(os.environ, GIT_AUTHOR_DATE=local_stamp(DAY, 14, 0),
               GIT_COMMITTER_DATE=local_stamp(DAY, 14, 0))
    run(["git", "merge", "-q", "--no-ff", "-m", "merge side", "side"], repo, env)

    (repo / "app" / "late.py").write_text("z = 3\n")
    commit(repo, "feat: the next day at midnight", local_stamp(DAY + dt.timedelta(days=1), 0, 0))
    (repo / "dirty.txt").write_text("uncommitted\n")


def collect(repo, *extra, day=DAY):
    proc = subprocess.run([str(SCRIPT), "collect", "--date", day.isoformat(), *extra],
                          cwd=repo, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def check_collect(failures):
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        build_repo(repo)

        code, facts = collect(repo)
        subjects = [c["subject"] for c in facts["commits"]]
        want = ["refactor: rename at midnight", "feat: on a side branch", "docs: on main"]
        if code != 0 or subjects != want:
            failures.append("collect: got %r (exit %d), wanted %r" % (subjects, code, want))
        if facts["merge_commits_skipped"] != 1:
            failures.append("collect: merge commit not skipped and counted")
        if facts["uncommitted"]["untracked"] != 1:
            failures.append("collect: the uncommitted file was not reported")

        rename = next((c for c in facts["commits"] if c["subject"].startswith("refactor")), None)
        files = {f["path"]: f for f in rename["files"]} if rename else {}
        moved = files.get("app/new_name.py")
        if not moved or moved["status"] != "R" or moved["old_path"] != "app/old_name.py":
            failures.append("collect: the rename was not recorded as one: %r" % files)
        if not files.get("package-lock.json", {}).get("noise"):
            failures.append("collect: package-lock.json not marked as noise")
        if rename and rename["added"] != 0:
            failures.append("collect: lock-file lines counted as work (%d)" % rename["added"])
        if facts["noise_files"] != ["package-lock.json"]:
            failures.append("collect: noise_files is %r" % facts["noise_files"])

        _, head = collect(repo, "--head-only")
        if "feat: on a side branch" not in [c["subject"] for c in head["commits"]]:
            failures.append("collect --head-only: lost the commit merged into HEAD")

        code, empty = collect(repo, day=dt.date(2026, 1, 1))
        if code != 0 or empty["commit_count"] != 0:
            failures.append("collect: an empty day did not return zero commits")
        return facts


def check_render_refusals(facts, failures):
    good = {"summary": "ملخص", "accomplishments": [{"title": "عمل"}]}
    cases = [
        ("fabricated hash", dict(good, changelog=[{"hash": "deadbeef", "explanation": "x"}])),
        ("missing summary", {"accomplishments": [{"title": "عمل"}]}),
        ("empty day", good),
    ]
    for name, content in cases:
        source = dict(facts, commits=[]) if name == "empty day" else facts
        try:
            r.check_content(content, source)
        except r.UsageError:
            continue
        failures.append("render: %s was accepted" % name)

    short = facts["commits"][0]["short"]
    uncited = r.check_content(dict(good, changelog=[{"hash": short}]), facts)
    if short in uncited or len(uncited) != len(facts["commits"]) - 1:
        failures.append("render: uncited commits computed wrong: %r" % uncited)


def check_inline(failures):
    got = r.inline("عدّل `hooks/guard.py` و<b> **مهم**")
    want = ('عدّل <code dir="ltr">hooks/guard.py</code> و&lt;b&gt; <strong>مهم</strong>')
    if got != want:
        failures.append("inline: %r" % got)
    if "<script>" in r.inline("`<script>`"):
        failures.append("inline: code spans are not escaped")


def check_noise(failures):
    for path, want in [
        ("yarn.lock", True), ("web/dist/app.js", True), ("a/b/x.min.js", True),
        ("reports/2026-03-10-development-report-ar.pdf", True),
        ("app/build.py", False), ("app/public/js/form.js", False), ("docs/lock.md", False),
    ]:
        if r.is_noise(path) != want:
            failures.append("is_noise(%r) is %r" % (path, not want))


def check_end_to_end(facts, failures):
    try:
        r.find_chrome()
    except r.Failure:
        return "skipped: no Chrome"
    if not all(shutil.which(t) for t in ("pdfinfo", "pdffonts", "pdftotext")):
        return "skipped: no poppler-utils"
    content = {
        "summary": "تقرير اختبار يغطي إعادة تسمية ملف وتوثيقاً جديداً.",
        "accomplishments": [{"kind": "refactor", "title": "إعادة تسمية `new_name.py`",
                             "description": "نُقل الملف دون تغيير محتواه."}],
        "changelog": [{"hash": c["short"], "explanation": "شرح"} for c in facts["commits"]],
    }
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "content.json").write_text(json.dumps(content, ensure_ascii=False))
        (tmp / "commits.json").write_text(json.dumps(facts, ensure_ascii=False))
        proc = subprocess.run(
            [str(SCRIPT), "render", str(tmp / "content.json"), "--commits",
             str(tmp / "commits.json"), "--out", str(tmp / "out" / "r.pdf")],
            capture_output=True, text=True, timeout=240,
        )
        if proc.returncode != 0:
            failures.append("render: exit %d: %s" % (proc.returncode, proc.stderr.strip()))
            return "ran"
        result = json.loads(proc.stdout)
        if not result["ok"] or not (tmp / "out" / "r.pdf").is_file():
            failures.append("render: verification failed: %r" % result["problems"])
    return "ran"


def main():
    failures = []
    check_noise(failures)
    check_inline(failures)
    facts = check_collect(failures)
    check_render_refusals(facts, failures)
    end_to_end = check_end_to_end(facts, failures)

    if failures:
        print("FAIL")
        for line in failures:
            print("  " + line)
        return 1
    print("OK (end-to-end render %s)" % end_to_end)
    return 0


if __name__ == "__main__":
    sys.exit(main())
