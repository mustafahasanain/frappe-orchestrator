#!/usr/bin/env python3
"""Tests for the delegation dispatcher's result parser.

    python3 tests/test_parser.py

The parser is the one component of this plugin that fails silently. A missing CLI, a
malformed routing file, a wrong hook decision - all announce themselves. A parser that
returns the wrong object hands the orchestrator a plausible-looking report that nobody
questions, so it is the piece that earns coverage.

Two fixtures are real captured stdout from `codex exec`, not invented samples. The
inner-fence one is the output that broke the previous parser: its own `detail` string
contains a fenced example, and a regex delimiting a block on triple backticks truncates
the body there. A tidier stub is exactly how that defect survived.

No framework and nothing to install: standard library only.
"""

import importlib.machinery
import importlib.util
import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load_dispatcher():
    """Import scripts/delegate, which has no .py extension, without running it."""
    path = ROOT / "scripts" / "delegate"
    loader = importlib.machinery.SourceFileLoader("delegate", str(path))
    spec = importlib.util.spec_from_loader("delegate", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def fixture(name):
    return (FIXTURES / name).read_text()


d = load_dispatcher()
extract = d.extract_report

BANNER = "OpenAI Codex v0.149.0\n--------\nmodel: gpt-5.6-sol\n--------\n"
FOOTER = "\ntokens used\n10,078\n"
BLOCK = '```json\n{"verdict": "PASS", "summary": "s", "findings": []}\n```'
DEEP = '{"a":' * 10000 + "1" + "}" * 10000

# (name, mode, text, expected state, expected discriminator or None)
CASES = [
    # --- real captured output ---------------------------------------------
    ("real codex output", "review", fixture("codex-review-clean.txt"), "present", "PASS"),
    ("real output, fence inside a string value", "review",
     fixture("codex-review-inner-fence.txt"), "present", "FAIL"),

    # --- shapes a CLI can wrap the report in -------------------------------
    ("banner and footer on the same stream", "review", BANNER + BLOCK + FOOTER, "present", "PASS"),
    ("prose either side of the block", "review", "Review:\n\n" + BLOCK + "\n\nDone.", "present", "PASS"),
    ("no fence at all", "review", BANNER + '{"verdict":"BLOCKED","summary":"s"}' + FOOTER,
     "present", "BLOCKED"),

    # --- fences are not parsed, so none of these can matter ----------------
    ("untagged fence", "review", '```\n{"verdict":"FAIL","summary":"s"}\n```', "present", "FAIL"),
    ("multiword info string", "review", '```json result\n{"verdict":"PASS","summary":"s"}\n```',
     "present", "PASS"),
    ("unterminated fence", "review", '```json\n{"verdict":"PASS","summary":"s"}', "present", "PASS"),
    ("braces and backticks inside a string", "review",
     '{"verdict":"PASS","summary":"see {a:1} and ```x"}', "present", "PASS"),

    # --- selection ---------------------------------------------------------
    ("last report wins", "review", '{"verdict":"FAIL","summary":"a"}\n' + BLOCK, "present", "PASS"),
    ("report nested in a wrapper is found", "review",
     '{"wrapper":{"verdict":"PASS","summary":"n"}}', "present", "PASS"),
    ("discriminator compared casefolded", "review", '{"verdict":"pass","summary":"s"}',
     "present", "pass"),

    # --- CLI JSON must not be mistaken for a report ------------------------
    ("connected/summary pair rejected", "review", '{"status":"connected","summary":"x"}',
     "missing", None),
    ("summary and findings without a verdict rejected", "review",
     '{"summary":"s","findings":[]}', "missing", None),
    ("off-contract verdict rejected", "review", '{"verdict":"PARTIAL","summary":"s"}',
     "missing", None),
    ("config JSON alone", "review", 'echo {"model":"x","port":8080}', "missing", None),
    ("telemetry after a real report does not displace it", "review",
     '{"verdict":"PASS","summary":"real"}\n{"status":"connected","summary":"tel"}',
     "present", "PASS"),

    # --- mode decides the discriminator ------------------------------------
    ("implement report", "implement", '{"status":"completed","summary":"s"}', "present", None),
    ("implement rejects a non-contract status", "implement",
     '{"status":"connected","summary":"s"}', "missing", None),
    ("a review report is not an implement report", "implement", BLOCK, "invalid", None),

    # --- states ------------------------------------------------------------
    ("fence present but nothing parses", "review", "```json\n{oops}\n```", "invalid", None),
    ("truncated JSON, no fence", "review", '{"verdict":', "missing", None),
    ("no JSON anywhere", "review", BANNER + "Could not review." + FOOTER, "missing", None),
    ("empty output", "review", "", "missing", None),

    # --- untrusted input must not raise ------------------------------------
    ("nesting past the recursion limit", "review", DEEP, "missing", None),
    ("real report after deep nesting", "review", DEEP + '{"verdict":"PASS","summary":"s"}',
     "present", "PASS"),

    # --- limits fail closed ------------------------------------------------
    ("report larger than MAX_REPORT_CHARS is dropped, not truncated", "review",
     '{"verdict":"PASS","summary":"%s"}' % ("x" * (d.MAX_REPORT_CHARS + 10)), "missing", None),
    ("report just inside MAX_REPORT_CHARS is kept", "review",
     '{"verdict":"PASS","summary":"%s"}' % ("x" * (d.MAX_REPORT_CHARS - 100)), "present", "PASS"),
    ("report behind more than MAX_DECODE_ATTEMPTS candidates is dropped", "review",
     '{"verdict":"PASS","summary":"s"}' + ("{x" * (d.MAX_DECODE_ATTEMPTS + 100)), "missing", None),
]

# Bounded-time checks. Thresholds are generous: this asserts the bounds exist, not that
# the machine is fast.
TIMED = [
    ("one million malformed candidates", "review", "{x" * 1000000, 3.0),
    ("compact hostile nesting", "review", '{"x":' * 20000 + "0" + "}" * 20000,
     d.MAX_SCAN_SECONDS + 3.0),
    ("hostile input with a real report at the end", "review",
     '{"x":' * 20000 + "0" + "}" * 20000 + '{"verdict":"PASS","summary":"s"}', 1.0),
]

# Behaviour that is known to be wrong and is not yet fixed. Recorded so it is visible
# rather than mistaken for correctness. Reported by Codex, attempt 3 of the Phase 03
# review loop, which reached the three-attempt bound. See PHASE_03_REPORT.md.
KNOWN_GAPS = [
    ("generic object with a valid discriminator is accepted", "implement",
     '{"status":"completed","operation":"session"}', "present"),
    ("same, review mode", "review", '{"verdict":"PASS","rule":"transport"}', "present"),
]


def main():
    failures = []

    for name, mode, text, want_state, want_value in CASES:
        try:
            state, report = extract(text, mode)
        except Exception as exc:  # a parser of untrusted output must never raise
            failures.append("%s: raised %s" % (name, type(exc).__name__))
            continue
        got_value = (report or {}).get("verdict") if report else None
        if state != want_state:
            failures.append("%s: state %r, wanted %r" % (name, state, want_state))
        elif want_value is not None and got_value != want_value:
            failures.append("%s: value %r, wanted %r" % (name, got_value, want_value))

    for name, mode, text, budget in TIMED:
        started = time.monotonic()
        try:
            extract(text, mode)
        except Exception as exc:
            failures.append("%s: raised %s" % (name, type(exc).__name__))
            continue
        elapsed = time.monotonic() - started
        if elapsed > budget:
            failures.append("%s: took %.1fs, budget %.1fs" % (name, elapsed, budget))

    print("%d cases, %d timed" % (len(CASES), len(TIMED)))

    regressed = []
    for name, mode, text, current in KNOWN_GAPS:
        state, _ = extract(text, mode)
        if state != current:
            regressed.append(name)
    if KNOWN_GAPS:
        print("\n%d known gap(s), documented, not counted as failures:" % len(KNOWN_GAPS))
        for name, _, _, _ in KNOWN_GAPS:
            print("  - %s" % name)
    if regressed:
        print("\nA known gap no longer behaves as recorded. If it was fixed, move it into")
        print("CASES; if it changed some other way, it needs looking at:")
        for name in regressed:
            print("  - %s" % name)

    if failures:
        print("\nFAILED (%d):" % len(failures))
        for line in failures:
            print("  - %s" % line)
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
