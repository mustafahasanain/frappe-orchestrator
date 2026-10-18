#!/usr/bin/env python3
"""The review gate: when a change needs an independent Codex review, from its real diff.

    python3 tests/test_review_gate.py

Each case builds a small Frappe-shaped app in a temporary git repository, makes one
change, and asks orchlib.review_gate (and `orch gate`, the same code behind a CLI) whether
Codex must run. The first five are the representative scenarios the upgrade is measured
on: a text change, a CSS change, a small Python fix, a routine NORMAL feature, and a
permission/data-integrity change. No agent runs here.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import orchlib  # noqa: E402

ROUTING = orchlib.load_routing()

DOCTYPE = "myapp/myapp/doctype/sales_note/sales_note.json"
CONTROLLER = "myapp/myapp/doctype/sales_note/sales_note.py"
UTILS = "myapp/myapp/utils.py"
CSS = "myapp/public/css/myapp.css"
API = "myapp/myapp/api.py"
FORM_JS = "myapp/myapp/doctype/sales_note/sales_note.js"

BASE = {
    DOCTYPE: json.dumps({
        "doctype": "DocType", "name": "Sales Note",
        "fields": [{"fieldname": "customer", "fieldtype": "Link", "label": "Customer Name",
                    "options": "Customer"},
                   {"fieldname": "note", "fieldtype": "Text", "label": "Note"}],
        "permissions": [{"role": "Sales User", "read": 1, "write": 1}],
    }, indent=1) + "\n",
    CONTROLLER: "import frappe\nfrom frappe.model.document import Document\n\n\n"
                "class SalesNote(Document):\n    def validate(self):\n        pass\n",
    UTILS: "def total(a, b):\n    return a - b\n",
    CSS: ".sales-note { color: #333; }\n",
    API: "import frappe\n",
    FORM_JS: "frappe.ui.form.on('Sales Note', {});\n",
    "myapp/hooks.py": "app_name = 'myapp'\n",
    "myapp/patches.txt": "",
}


def repo(tmp):
    path = Path(tmp)
    path.mkdir(parents=True, exist_ok=True)
    for name, body in BASE.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(body)
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"]):
        subprocess.run(["git", "-C", str(path)] + args, check=True, capture_output=True)
    return path


def edit(path, name, old, new):
    target = path / name
    text = target.read_text()
    assert old in text, (name, old)
    target.write_text(text.replace(old, new, 1))


def append(path, name, text):
    target = path / name
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a") as handle:
        handle.write(text)


# (name, tier, change, expected review, trigger names that must appear)
SCENARIOS = [
    ("1 text-only label change", "FAST",
     lambda p: edit(p, DOCTYPE, '"label": "Customer Name"', '"label": "Client Name"'),
     "not_required", []),
    ("2 simple CSS change", "SMALL",
     lambda p: edit(p, CSS, "#333", "#1a1a1a"), "not_required", []),
    ("3 small Python bug fix", "SMALL",
     lambda p: edit(p, UTILS, "a - b", "a + b"), "not_required", []),
    ("4 routine NORMAL feature (new field, validation, form JS, endpoint)", "NORMAL",
     lambda p: (
         edit(p, DOCTYPE, '{\n   "fieldname": "note"',
              '{\n   "fieldname": "priority",\n   "fieldtype": "Select",\n'
              '   "label": "Priority",\n   "options": "Low\\nHigh"\n  },\n'
              '  {\n   "fieldname": "note"'),
         edit(p, CONTROLLER, "        pass\n",
              "        if self.priority == 'High' and not self.note:\n"
              "            frappe.throw('A high-priority note needs text')\n"),
         append(p, FORM_JS, "frappe.ui.form.on('Sales Note', {\n  priority(frm) {\n"
                "    frm.toggle_reqd('note', frm.doc.priority === 'High');\n  }\n});\n"),
         append(p, API, "\n\n@frappe.whitelist()\ndef priorities():\n"
                "    return ['Low', 'High']\n"),
     ),
     "not_required", []),
    ("5 permission + data-integrity change", "NORMAL",
     lambda p: (
         edit(p, CONTROLLER, "        pass\n",
              "        if not frappe.has_permission('Customer', 'write'):\n"
              "            frappe.throw('Not permitted')\n"
              "        frappe.db.set_value('Customer', self.customer, 'note', self.note)\n"),
     ),
     "required", ["auth-or-permissions", "data-integrity-or-destructive"]),
]

# Mandatory triggers fire on every tier, including FAST.
MANDATORY = [
    ("ignore_permissions on FAST", "FAST",
     lambda p: edit(p, CONTROLLER, "pass", "self.save(ignore_permissions=True)"),
     "auth-or-permissions"),
    ("DocType permission rows", "SMALL",
     lambda p: edit(p, DOCTYPE, '"role": "Sales User"', '"role": "Guest"'),
     "doctype-permissions"),
    ("removed field", "SMALL",
     lambda p: edit(p, DOCTYPE, '{\n   "fieldname": "note",\n   "fieldtype": "Text",\n'
                    '   "label": "Note"\n  }', '{}'),
     "doctype-schema-change"),
    ("retyped field", "FAST",
     lambda p: edit(p, DOCTYPE, '"fieldtype": "Text"', '"fieldtype": "Int"'),
     "doctype-schema-change"),
    ("new patch", "SMALL",
     lambda p: (append(p, "myapp/patches.txt", "myapp.patches.v1.fix\n"),
                append(p, "myapp/patches/v1/fix.py", "def execute():\n    pass\n")),
     "schema-or-migration"),
    ("ledger arithmetic", "SMALL",
     lambda p: edit(p, UTILS, "return a - b", "return flt(a.grand_total) - flt(b)"),
     "financial-calculation"),
    ("raw delete", "SMALL",
     lambda p: edit(p, UTILS, "return a - b",
                    "frappe.db.sql('DELETE FROM `tabSales Note` WHERE 1')"),
     "data-integrity-or-destructive"),
    ("row lock", "SMALL",
     lambda p: edit(p, UTILS, "return a - b",
                    "return frappe.get_doc('X', a, for_update=True)"),
     "concurrency-locking"),
    ("override in hooks", "SMALL",
     lambda p: append(p, "myapp/hooks.py",
                      "override_whitelisted_methods = {'a': 'myapp.api.priorities'}\n"),
     "global-hooks"),
    ("guest endpoint", "SMALL",
     lambda p: append(p, API, "\n@frappe.whitelist(allow_guest=True)\ndef open():\n"
                      "    return 1\n"), "auth-or-permissions"),
]


ENDPOINTS = "myapp/myapp/endpoints.py"
WWW = "myapp/www/payslips.py"
TEMPLATE = "myapp/www/payslips.html"
PLAIN_TEMPLATE = "myapp/templates/includes/footer.html"
HAS_PERM = "myapp/myapp/access.py"
BASE.update({
    ENDPOINTS: "import frappe\n\n\n@frappe.whitelist()\ndef open_notes(customer):\n"
               "    filters = {'customer': customer}\n"
               "    return frappe.get_list('Sales Note', filters=filters, fields=['name'])\n",
    WWW: "import frappe\n\n\ndef get_context(context):\n    context.title = 'Payslips'\n",
    TEMPLATE: "{% extends 'templates/web.html' %}\n{% block page_content %}\n"
              "{% set slips = frappe.get_list('Salary Slip', fields=['name']) %}\n"
              "<h1>{{ _(\"Payslips\") }}</h1>\n<p>Your recent payslips.</p>\n"
              "{% for s in slips %}<li>{{ s.name }}</li>{% endfor %}\n{% endblock %}\n",
    PLAIN_TEMPLATE: "<footer class=\"muted\">Made with care</footer>\n",
    HAS_PERM: "def has_permission(doc, ptype, user):\n    if doc.owner == user:\n"
              "        return True\n    return False\n",
    "myapp/package.json": "{\n  \"dependencies\": {}\n}\n",
    "myapp/myapp/report/open_notes/open_notes.json":
        "{\n \"doctype\": \"Report\",\n \"query\": \"select name from `tabSales Note`\"\n}\n",
})


# Frappe security changes that must reach Codex, on the smallest tiers too. Most of these
# came back not_required in the final verification. (name, tier, change, trigger)
SECURITY = [
    ("new endpoint exposing contacts", "SMALL",
     lambda p: append(p, API, "\n\n@frappe.whitelist()\ndef contacts():\n"
                      "    return frappe.get_all('Contact', fields=['email_id'])\n"),
     "sensitive-endpoint"),
    ("new endpoint writing any doctype", "FAST",
     lambda p: append(p, API, "\n\n@frappe.whitelist()\ndef touch(doctype, name):\n"
                      "    doc = frappe.get_doc(doctype, name)\n    doc.save()\n"),
     "sensitive-endpoint"),
    ("changed body of an existing endpoint, decorator untouched", "SMALL",
     lambda p: edit(p, ENDPOINTS, "filters = {'customer': customer}", "filters = {}"),
     "sensitive-endpoint"),
    ("serialised document returned by an endpoint", "SMALL",
     lambda p: append(p, API, "\n\n@frappe.whitelist(methods=['GET'])\ndef note(name):\n"
                      "    return frappe.get_doc('Sales Note', name).as_dict()\n"),
     "sensitive-endpoint"),
    ("whitelisted controller method inserting a record", "SMALL",
     lambda p: edit(p, CONTROLLER, "    def validate(self):\n        pass\n",
                    "    def validate(self):\n        pass\n\n    @frappe.whitelist()\n"
                    "    def copy(self):\n        frappe.copy_doc(self).insert()\n"),
     "sensitive-endpoint"),
    ("www page context exposing salary slips", "SMALL",
     lambda p: edit(p, WWW, "    context.title = 'Payslips'\n",
                    "    context.title = 'Payslips'\n"
                    "    context.slips = frappe.get_all('Salary Slip', fields=['*'])\n"),
     "sensitive-endpoint"),
    ("Jinja template querying with ignore_permissions", "SMALL",
     lambda p: edit(p, PLAIN_TEMPLATE, "Made with care",
                    "{{ frappe.get_all('User', ignore_permissions=True) }}"),
     "sensitive-template"),
    ("new field rendered in a template that queries data", "SMALL",
     lambda p: edit(p, TEMPLATE, "<li>{{ s.name }}</li>",
                    "<li>{{ s.name }} {{ s.net_pay }}</li>"),
     "sensitive-template"),
    ("unescaped template output", "SMALL",
     lambda p: edit(p, PLAIN_TEMPLATE, "Made with care", "{{ comment | safe }}"),
     "template-unescaped-output"),
    ("access-control function changed without a keyword", "SMALL",
     lambda p: edit(p, HAS_PERM, "if doc.owner == user:", "if doc.owner or user:"),
     "access-control-logic"),
    ("npm dependency added", "SMALL",
     lambda p: edit(p, "myapp/package.json", "{}", "{\"left-pad\": \"^1.3.0\"}"),
     "dependencies-or-tooling"),
    ("shell script with rm -rf", "SMALL",
     lambda p: append(p, "myapp/scripts/clean.sh", "#!/bin/sh\nrm -rf \"$1\"/*\n"),
     "dependencies-or-tooling"),
    ("Query Report SQL changed", "SMALL",
     lambda p: edit(p, "myapp/myapp/report/open_notes/open_notes.json",
                    "select name from", "select * from"),
     "doctype-permissions"),
]

# Changes that must stay cheap: complete, and no Codex. (name, tier, change)
HARMLESS = [
    ("markup text in a template that queries data", "SMALL",
     lambda p: edit(p, TEMPLATE, "Your recent payslips.", "Your payslips this year.")),
    ("translated heading in a template that queries data", "FAST",
     lambda p: edit(p, TEMPLATE, '_("Payslips")', '_("Your payslips")')),
    ("markup in a template without data", "FAST",
     lambda p: edit(p, PLAIN_TEMPLATE, 'class="muted"', 'class="muted small"')),
    ("comment inside an endpoint", "SMALL",
     lambda p: edit(p, ENDPOINTS, "    filters = {'customer': customer}\n",
                    "    # only this customer's notes\n    filters = {'customer': customer}\n")),
    ("text in a www page context", "SMALL",
     lambda p: edit(p, WWW, "'Payslips'", "'My payslips'")),
    ("README mentioning permissions", "FAST",
     lambda p: append(p, "myapp/README.md", "\nUse has_permission and ignore_permissions "
                      "carefully; credit and debit are ledger terms.\n")),
    ("image added", "FAST",
     lambda p: (p / "myapp/public/logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR")),
    ("new pure helper", "SMALL",
     lambda p: append(p, UTILS, "\n\ndef double(x):\n    return x * 2\n")),
]


def broken(mutate):
    routing = json.loads(json.dumps(orchlib.load_routing()))
    mutate(routing)
    return routing


# Each must fail closed: review required and gate_status not "complete", never a crash
# and never a silent not_required. (name, routing, change, files, status, reason fragment)
def _set_level(r):
    r["review"]["triggers"][0]["level"] = "mandatroy"


def _bad_regex(r):
    r["review"]["triggers"][2]["lines"].append("([unclosed")


def _misspelt_key(r):
    trigger = r["review"]["triggers"][3]
    trigger["line"] = trigger.pop("lines")


def _drop_tier(r):
    del r["review"]["tiers"]["SMALL"]


def _drop_review(r):
    del r["review"]


def _unreadable(p):
    target = p / "myapp/myapp/secret.py"
    target.write_text("x = 1\n")
    target.chmod(0)


def _symlink(p):
    os.symlink("/etc/hostname", str(p / "myapp/public/hostname.txt"))


def _huge(p):
    (p / "myapp/myapp/generated.py").write_text("x = 1\n" * 400000)


def _unknown_type(p):
    append(p, "myapp/tools/convert.rb", "puts 'hi'\n")


def _binary_code(p):
    (p / "myapp/myapp/blob.py").write_bytes(b"\0\1\2" * 10)


def _unparsable_endpoint(p):
    append(p, API, "\n\n@frappe.whitelist()\ndef broken(:\n    return frappe.get_all('User')\n")


FAILCLOSED = [
    ("misspelt trigger level", broken(_set_level), lambda p: edit(p, CSS, "#333", "#111"),
     "error", "level 'mandatroy'"),
    ("trigger regex that does not compile", broken(_bad_regex),
     lambda p: edit(p, CSS, "#333", "#111"), "error", "does not compile"),
    ("misspelt trigger key", broken(_misspelt_key), lambda p: edit(p, CSS, "#333", "#111"),
     "error", "unknown key 'line'"),
    ("tier with no review policy", broken(_drop_tier), lambda p: edit(p, CSS, "#333", "#111"),
     "error", "review.tiers.SMALL"),
    ("no review block", broken(_drop_review), lambda p: edit(p, CSS, "#333", "#111"),
     "error", "no review block"),
    ("unreadable untracked file", None, _unreadable, "incomplete", "could not be read"),
    ("untracked symlink", None, _symlink, "incomplete", "symbolic link"),
    ("untracked file too large to inspect", None, _huge, "incomplete", "larger than"),
    ("file type the gate does not assess", None, _unknown_type, "incomplete",
     "does not assess"),
    ("binary content in a code file", None, _binary_code, "incomplete", "binary"),
    ("endpoint file that does not parse", None, _unparsable_endpoint, "incomplete",
     "does not parse"),
]


def gate(path, tier, **kw):
    return orchlib.review_gate(str(path), tier, ROUTING, **kw)


def check_security_and_harmless(failures):
    print("\nFrappe security changes (must require review):")
    for name, tier, change, trigger in SECURITY:
        with tempfile.TemporaryDirectory() as tmp:
            path = repo(tmp)
            change(path)
            result = gate(path, tier)
            fired = {t["name"]: t["evidence"] for t in result["triggers"]}
            print("  %-60s %-6s %s  %s" % (name, tier, result["review"],
                                          fired.get(trigger, "-")[:70]))
            if result["review"] != "required" or trigger not in fired:
                failures.append("security %s: review %s, %s not in %s"
                                % (name, result["review"], trigger, sorted(fired)))
            if result["gate_status"] != "complete":
                failures.append("security %s: gate %s %r" % (name, result["gate_status"],
                                                              result["unevaluated"]))
    print("\nHarmless changes (must stay complete and not_required):")
    for name, tier, change in HARMLESS:
        with tempfile.TemporaryDirectory() as tmp:
            path = repo(tmp)
            change(path)
            result = gate(path, tier)
            print("  %-60s %-6s %s / %s" % (name, tier, result["review"], result["gate_status"]))
            if result["review"] != "not_required" or result["gate_status"] != "complete":
                failures.append("harmless %s: %s/%s %r" % (
                    name, result["review"], result["gate_status"], result["reasons"]))


def check_fail_closed(failures):
    print("\nGate failures (must fail closed):")
    for name, routing, change, status, fragment in FAILCLOSED:
        with tempfile.TemporaryDirectory() as tmp:
            path = repo(tmp)
            change(path)
            try:
                result = orchlib.review_gate(str(path), "SMALL", routing or ROUTING)
            except Exception as exc:   # noqa: BLE001
                failures.append("fail-closed %s: the gate raised %r" % (name, exc))
                continue
            finally:
                for root, _dirs, files in os.walk(str(path)):
                    for f in files:
                        try:
                            os.chmod(os.path.join(root, f), 0o644)
                        except OSError:
                            pass
            text = json.dumps(result)
            print("  %-45s %s / %s" % (name, result["review"], result["gate_status"]))
            if result["review"] != "required" or result["gate_status"] != status \
                    or fragment not in text:
                failures.append("fail-closed %s: %s/%s, wanted required/%s with %r: %s" % (
                    name, result["review"], result["gate_status"], status, fragment,
                    result["reasons"]))

    def crash(_text):
        raise RuntimeError("synthetic parser crash")
    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        edit(path, CSS, "#333", "#111")
        original, orchlib.parse_diff = orchlib.parse_diff, crash
        try:
            result = gate(path, "SMALL")
        finally:
            orchlib.parse_diff = original
        if result["review"] != "required" or result["gate_status"] != "error":
            failures.append("a crash inside the gate gave %r" % result)
        if gate(path, "SMALL", base="no-such-commit")["gate_status"] != "incomplete":
            failures.append("an unreadable base did not fail closed")
    with tempfile.TemporaryDirectory() as tmp:
        result = gate(tmp, "SMALL")
        if result["review"] != "required" or result["gate_status"] == "complete":
            failures.append("a directory that is not a repository passed the gate: %r" % result)


def check_implementation_gate(failures):
    """The dispatcher's view: measured files, plus commits made during the run."""
    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        before = orchlib.head(str(path))
        result = orchlib.implementation_gate(str(path), "SMALL", ROUTING, None, before, before)
        if result["review"] != "required" or result["gate_status"] != "incomplete":
            failures.append("a failed snapshot did not fail closed: %r" % result)
        result = orchlib.implementation_gate(str(path), "SMALL", ROUTING, [], None, None)
        if result["review"] != "required" or result["gate_status"] != "incomplete":
            failures.append("an unreadable HEAD did not fail closed: %r" % result)
        empty = orchlib.implementation_gate(str(path), "NORMAL", ROUTING, [], before, before)
        if empty["review"] != "not_required" or empty["gate_status"] != "complete":
            failures.append("a genuinely empty change was not complete/not_required: %r" % empty)
        # The run committed a destructive change and left the tree clean.
        edit(path, UTILS, "return a - b", "frappe.db.sql('DELETE FROM `tabSales Note`')")
        subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-qam", "agent"], check=True)
        after = orchlib.head(str(path))
        result = orchlib.implementation_gate(str(path), "SMALL", ROUTING, [], before, after)
        fired = {t["name"] for t in result["triggers"]}
        if result["review"] != "required" or "data-integrity-or-destructive" not in fired \
                or UTILS not in result["files"]:
            failures.append("a committed change escaped the gate: %r" % result)
        # Even a harmless commit is reported: the agent was not supposed to commit.
        with tempfile.TemporaryDirectory() as tmp2:
            path2 = repo(tmp2)
            start = orchlib.head(str(path2))
            edit(path2, CSS, "#333", "#111")
            subprocess.run(["git", "-C", str(path2), "-c", "user.email=t@t", "-c",
                            "user.name=t", "commit", "-qam", "agent"], check=True)
            moved = orchlib.implementation_gate(str(path2), "SMALL", ROUTING, [], start,
                                                orchlib.head(str(path2)))
            if moved["review"] != "required" or not any("HEAD moved" in r
                                                       for r in moved["reasons"]):
                failures.append("a commit during the run was not reported: %r" % moved)


def check_claimed_files(failures):
    """`orch gate --files` is a claim by the orchestrator, so the whole diff is still
    read: a risk outside the list requires review, harmless extras do not."""
    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        edit(path, UTILS, "a - b", "a + b")
        edit(path, CONTROLLER, "pass", "frappe.db.sql('DELETE FROM x')")
        result = gate(path, "SMALL", files=[UTILS], files_claimed=True)
        if result["review"] != "required" or not any("outside the given files" in r
                                                    for r in result["reasons"]):
            failures.append("a risky change outside --files passed: %r" % result["reasons"])
    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        edit(path, UTILS, "a - b", "a + b")
        edit(path, CSS, "#333", "#111")
        result = gate(path, "SMALL", files=[UTILS], files_claimed=True)
        if result["review"] != "not_required":
            failures.append("a harmless change outside --files forced review: %r"
                            % result["reasons"])
        if not any("not in the given files" in a for a in result["advisories"]):
            failures.append("the change outside --files was not even noted")


def check_invalid_files(failures):
    """The FAST check needs no command of its own: the gate parses changed .py and .json."""
    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        edit(path, DOCTYPE, '"label": "Customer Name"', '"label": "Client Name",')
        edit(path, UTILS, "return a - b", "return (a - b")
        result = gate(path, "FAST")
        bad = sorted(item["file"] for item in result.get("invalid_files") or [])
        if bad != sorted([DOCTYPE, UTILS]):
            failures.append("invalid files reported as %r" % result.get("invalid_files"))
    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        edit(path, DOCTYPE, '"label": "Customer Name"', '"label": "Client Name"')
        if gate(path, "FAST").get("invalid_files") != []:
            failures.append("a valid label change was reported invalid")
    # Risk outside a claimed list follows the tier rule; mandatory risk always requires.
    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        edit(path, CSS, "#333", "#111")
        append(path, "myapp/hooks.py", "# the user's own experiment\n")
        if gate(path, "FAST", files=[CSS], files_claimed=True)["review"] != "not_required":
            failures.append("a risk-level user change outside --files forced review on FAST")
        if gate(path, "NORMAL", files=[CSS], files_claimed=True)["review"] != "required":
            failures.append("a risk-level change outside --files passed on NORMAL")
        append(path, "myapp/hooks.py", "override_doctype_class = {'User': 'x.User'}\n")
        if gate(path, "FAST", files=[CSS], files_claimed=True)["review"] != "required":
            failures.append("a mandatory change outside --files passed on FAST")


def check_parse_diff(failures):
    """Files with no +++ line - binary, empty, mode-only - are still files the gate sees."""
    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        (path / "myapp/public/icon.png").write_bytes(b"\0PNG")
        (path / "myapp/myapp/empty.py").write_text("")
        (path / "myapp/myapp/with space.py").write_text("x = 1\n")
        subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
        os.chmod(str(path / UTILS), 0o755)
        text = orchlib.git(str(path), "diff", "--no-renames", "--src-prefix=a/",
                           "--dst-prefix=b/", "-U0", "HEAD")
        parsed = orchlib.parse_diff(text)
        for name in ("myapp/public/icon.png", "myapp/myapp/empty.py", UTILS,
                     "myapp/myapp/with space.py"):
            if name not in parsed:
                failures.append("parse_diff dropped %s: %s" % (name, sorted(parsed)))
        if not parsed.get("myapp/public/icon.png", {}).get("binary"):
            failures.append("a binary file was not flagged binary")


def main():
    failures = []
    print("Representative scenarios:")
    for name, tier, change, want, names in SCENARIOS:
        with tempfile.TemporaryDirectory() as tmp:
            path = repo(tmp)
            change(path)
            result = gate(path, tier)
            got = result["review"]
            fired = {t["name"] for t in result["triggers"]}
            print("  %-70s %-9s review: %s%s" % (
                name, tier, got, "" if not result["reasons"] else "  (%s)"
                % "; ".join(result["reasons"])))
            if got != want:
                failures.append("%s: review %s, wanted %s (%r)" % (name, got, want, result))
            for trigger in names:
                if trigger not in fired:
                    failures.append("%s: %s did not fire (fired: %s)" % (name, trigger, fired))

    for name, tier, change, trigger in MANDATORY:
        with tempfile.TemporaryDirectory() as tmp:
            path = repo(tmp)
            change(path)
            result = gate(path, tier)
            if result["review"] != "required":
                failures.append("mandatory %s: review %s on %s" % (name, result["review"], tier))
            if trigger not in {t["name"] for t in result["triggers"]}:
                failures.append("mandatory %s: %s did not fire: %r"
                                % (name, trigger, result["triggers"]))
            if result["effort"] != "high":
                failures.append("mandatory %s: effort %s" % (name, result["effort"]))

    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        edit(path, UTILS, "a - b", "a + b")
        # Escalations the orchestrator reports.
        for kw, label in (({"tests_failed": True}, "failed tests"),
                          ({"fix_rounds": 2}, "two fix rounds"),
                          ({"user_requested": True}, "user request")):
            if gate(path, "SMALL", **kw)["review"] != "required":
                failures.append("%s did not require a review" % label)
        if gate(path, "SMALL", fix_rounds=1)["review"] != "not_required":
            failures.append("a single fix round required a review")
        # An unrelated dirty file the user owns does not make the task's diff risky.
        edit(path, CONTROLLER, "pass", "frappe.db.sql('DELETE FROM x')")
        if gate(path, "SMALL", files=[UTILS])["review"] != "not_required":
            failures.append("--files did not narrow the gate to the task's files")
        if gate(path, "SMALL")["review"] != "required":
            failures.append("the whole diff did not see the destructive change")

    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        for i in range(8):
            append(path, "myapp/myapp/mod%d.py" % i, "x = %d\n" * 40 % tuple(range(40)))
        small = gate(path, "SMALL")
        if small["review"] != "required" or not any("exceeds" in r for r in small["reasons"]):
            failures.append("an oversized SMALL diff was not escalated: %r" % small["reasons"])
        fast = gate(path, "FAST")
        if not fast["reclassify"]:
            failures.append("an oversized FAST diff was not flagged for reclassification")
        difficult = gate(path, "DIFFICULT")
        if difficult["review"] != "required":
            failures.append("a significant DIFFICULT change did not require review")

    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        if gate(path, "NORMAL")["review"] != "not_required":
            failures.append("an empty diff required a review")
        notes = gate(path, "DIFFICULT")
        if notes["review"] != "not_required":
            failures.append("an empty DIFFICULT diff required a review")

    # A removed line reading "-- x" or an added "++ y" is content, not a file header.
    parsed = orchlib.parse_diff(
        "diff --git a/q.sql b/q.sql\n--- a/q.sql\n+++ b/q.sql\n@@ -1,2 +1,2 @@\n"
        "--- header comment\n+++ new header\n-DELETE FROM x\n+SELECT 1\n")
    if set(parsed) != {"q.sql"} or "DELETE FROM x" not in parsed["q.sql"]["removed"]:
        failures.append("parse_diff mistook content for a file header: %r" % parsed)

    # `orch gate` is the same function behind a CLI.
    with tempfile.TemporaryDirectory() as tmp:
        path = repo(tmp)
        edit(path, CONTROLLER, "pass", "self.flags.ignore_permissions = True")
        proc = subprocess.run([sys.executable, str(ROOT / "scripts" / "orch"), "gate",
                               "--cwd", str(path), "--tier", "SMALL"],
                              capture_output=True, text=True, timeout=60)
        try:
            cli = json.loads(proc.stdout)
        except ValueError:
            cli = {}
        if cli.get("review") != "required" or proc.returncode != 0:
            failures.append("orch gate disagreed with the library: %r rc=%s %s"
                            % (cli, proc.returncode, proc.stderr[-200:]))

    # `orch gate` on a broken routing file: a JSON result requiring review, and exit 3.
    with tempfile.TemporaryDirectory() as tmp:
        plugin = Path(tmp) / "plugin"
        shutil.copytree(str(ROOT / "scripts"), str(plugin / "scripts"))
        shutil.copytree(str(ROOT / "config"), str(plugin / "config"))
        (plugin / "config" / "model-routing.json").write_text("{ not json")
        path = repo(Path(tmp) / "repo")
        proc = subprocess.run([sys.executable, str(plugin / "scripts" / "orch"), "gate",
                               "--cwd", str(path), "--tier", "FAST"],
                              capture_output=True, text=True, timeout=60)
        try:
            cli = json.loads(proc.stdout)
        except ValueError:
            cli = {}
        if cli.get("review") != "required" or proc.returncode != 3:
            failures.append("orch gate on a broken config: %r rc=%s %s"
                            % (cli, proc.returncode, proc.stderr[-200:]))

    check_security_and_harmless(failures)
    check_fail_closed(failures)
    check_implementation_gate(failures)
    check_claimed_files(failures)
    check_parse_diff(failures)
    check_invalid_files(failures)

    print("\n%d scenarios, %d mandatory triggers, %d security changes, %d harmless changes, "
          "%d fail-closed cases, escalations, scope, commits and CLI checked"
          % (len(SCENARIOS), len(MANDATORY), len(SECURITY), len(HARMLESS), len(FAILCLOSED)))
    if failures:
        print("\nFAILED (%d):" % len(failures))
        for line in failures:
            print("  - %s" % line)
        return 1
    print("\nok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
