"""Offline tests for Action Receipts. Accessibility readings use a stand-in backend;
no real Mac app is observed here."""

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest

from safe_mac_control.core import Denied
from safe_mac_control import receipts as R

DEMO = {"bundle": "org.klara.SafeMacDemo", "window": "Safe Mac Demo"}
COUNTER = {"identifier": "safe-demo-count", "role": "AXStaticText"}


class FakeAX:
    """Stands in for the native `inspect` helper: one window with a counter."""
    def __init__(self, value="0"):
        self.value = value
        self.available = True

    def __call__(self, request):
        if not self.available:
            return {"status": "DENIED", "reason": "accessibility_unavailable"}
        return {"status": "OBSERVED", "bundle": DEMO["bundle"], "window": DEMO["window"], "pid": 1,
                "fingerprint": "a" * 64, "frontmost": True,
                "elements": [{"role": "AXStaticText", "identifier": "safe-demo-count", "value": self.value,
                              "title": "", "description": "", "redacted": False}]}


class Receipts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.receipts = self.root / "receipts"
        self.docs = self.root / "docs"
        self.docs.mkdir()
        self.doc = self.docs / "report.txt"
        self.doc.write_text("draft 1")
        self.ax = FakeAX()
        self.n = 0

    def tearDown(self):
        self.temp.cleanup()

    def step(self, exp, action):
        self.n += 1
        sid = f"S-{self.n:03d}"
        self.assertEqual(R.begin(sid, exp, self.receipts, self.ax)["status"], "BEGUN")
        action()
        return R.end(sid, self.receipts, self.ax)

    def file_check(self, change="modified", path=None):
        return {"source": "file", "path": str(path or self.doc), "change": change}

    def ax_check(self, **kw):
        return {"source": "ax", **DEMO, "element": COUNTER, "change": "changed", **kw}

    def save(self, text="draft 2"):
        self.doc.write_text(text)
        os.utime(self.doc, ns=(1, self.doc.stat().st_mtime_ns + 10**9))

    def bump(self, by=1):
        self.ax.value = str(int(self.ax.value) + by)

    # ---- the five verdicts ----------------------------------------------------------------
    def test_verified_needs_two_kinds_of_source(self):
        r = self.step({"checks": [self.file_check(), self.ax_check()]}, lambda: (self.save(), self.bump()))
        self.assertEqual(r["verdict"], "VERIFIED", r)
        self.assertEqual(r["independent_kinds_agreeing"], ["filesystem", "interface"])

    def test_one_source_alone_is_never_verified(self):
        r = self.step({"checks": [self.file_check()]}, self.save)
        self.assertEqual((r["verdict"], r["reason"]), ("UNKNOWN_EFFECT", "only_one_kind_of_source_confirms"))

    def test_two_checks_of_the_same_kind_are_not_independent(self):
        new = self.docs / "export.pdf"
        exp = {"checks": [self.file_check("created", new),
                          {"source": "file_count", "dir": str(self.docs), "pattern": "*.pdf", "delta": 1}]}
        r = self.step(exp, lambda: new.write_text("pdf"))
        self.assertEqual((r["verdict"], r["reason"]), ("UNKNOWN_EFFECT", "only_one_kind_of_source_confirms"))

    def test_no_change(self):
        r = self.step({"checks": [self.file_check(), self.ax_check()]}, lambda: None)
        self.assertEqual(r["verdict"], "NO_CHANGE")

    def test_wrong_target_when_a_neighbour_changes_instead(self):
        exp = {"checks": [self.file_check(), self.ax_check()], "watch": [{"source": "dir", "dir": str(self.docs)}]}
        r = self.step(exp, lambda: (self.docs / "report copy.txt").write_text("draft 2"))
        self.assertEqual(r["verdict"], "WRONG_TARGET", r)

    def test_repeated_double_submit(self):
        out = self.root / "sent"; out.mkdir()
        exp = {"checks": [{"source": "file_count", "dir": str(out), "pattern": "*.eml", "delta": 1}, self.ax_check()]}
        def double():
            (out / "a.eml").write_text("x"); (out / "b.eml").write_text("x"); self.bump(2)
        r = self.step(exp, double)
        self.assertEqual(r["verdict"], "REPEATED", r)

    # ---- every kind of doubt becomes UNKNOWN_EFFECT ---------------------------------------
    def test_sources_disagree(self):
        r = self.step({"checks": [self.file_check(), self.ax_check()]}, self.save)
        self.assertEqual((r["verdict"], r["reason"]), ("UNKNOWN_EFFECT", "sources_disagree"))

    def test_unavailable_reading(self):
        self.ax.available = False
        r = self.step({"checks": [self.file_check(), self.ax_check()]}, self.save)
        self.assertEqual((r["verdict"], r["reason"]), ("UNKNOWN_EFFECT", "a_reading_was_unavailable"))

    def test_no_accessibility_backend_off_mac(self):
        self.n += 1
        exp = {"checks": [self.file_check(), self.ax_check()]}
        R.begin("OFF", exp, self.receipts, None); self.save()
        self.assertEqual(R.end("OFF", self.receipts, None)["verdict"], "UNKNOWN_EFFECT")

    def test_touched_but_content_identical(self):
        r = self.step({"checks": [self.file_check(), self.ax_check()]}, lambda: (self.save("draft 1"), self.bump()))
        self.assertEqual((r["verdict"], r["reason"]), ("UNKNOWN_EFFECT", "changed_but_not_as_expected"))

    def test_expected_change_plus_side_change(self):
        other = self.docs / "notes.txt"; other.write_text("n")
        exp = {"checks": [self.file_check(), self.ax_check()], "watch": [{"source": "file", "path": str(other)}]}
        r = self.step(exp, lambda: (self.save(), self.bump(), other.write_text("changed")))
        self.assertEqual((r["verdict"], r["reason"]), ("UNKNOWN_EFFECT", "expected_change_plus_unexpected_side_change"))

    # ---- other sources --------------------------------------------------------------------
    def test_created_and_deleted(self):
        new = self.docs / "export.pdf"
        r = self.step({"checks": [self.file_check("created", new), self.ax_check()]}, lambda: (new.write_text("pdf"), self.bump()))
        self.assertEqual(r["verdict"], "VERIFIED")
        r = self.step({"checks": [self.file_check("deleted", new), self.ax_check()]}, lambda: (new.unlink(), self.bump()))
        self.assertEqual(r["verdict"], "VERIFIED")

    def test_generated_ui_json_counts_as_its_own_source(self):
        ui = self.root / "a2ui.json"
        ui.write_text(json.dumps({"surface": {"components": [{"id": "status", "text": "Draft"}]}}))
        exp = {"checks": [self.file_check(), {"source": "a2ui", "path": str(ui), "component": "status",
                                              "change": "equals", "value": "Saved"}]}
        def act():
            self.save(); ui.write_text(json.dumps({"surface": {"components": [{"id": "status", "text": "Saved"}]}}))
        r = self.step(exp, act)
        self.assertEqual(r["verdict"], "VERIFIED", r)
        self.assertEqual([s["level"] for s in r["sources"]], [1, 2])

    def test_ax_equals_value(self):
        r = self.step({"checks": [self.file_check(), self.ax_check(change="equals", value="1")]},
                      lambda: (self.save(), self.bump()))
        self.assertEqual(r["verdict"], "VERIFIED")

    # ---- once only, private, hashes by default --------------------------------------------
    def test_step_ids_are_once_only_and_end_replays(self):
        exp = {"checks": [self.file_check(), self.ax_check()]}
        R.begin("ONE", exp, self.receipts, self.ax)
        with self.assertRaises(Denied):
            R.begin("ONE", exp, self.receipts, self.ax)
        self.save(); self.bump()
        first = R.end("ONE", self.receipts, self.ax)
        self.save("draft 3")  # later changes must not alter the stored answer
        again = R.end("ONE", self.receipts, self.ax)
        self.assertEqual(again["verdict"], first["verdict"])
        self.assertTrue(again["replayed_receipt"])
        with self.assertRaises(Denied):
            R.end("NEVER", self.receipts, self.ax)

    def test_private_files_and_hashes_only(self):
        self.doc.write_text("secret salary figures")
        r = self.step({"checks": [self.file_check(), self.ax_check()]}, lambda: (self.save("more secret"), self.bump()))
        raw = (self.receipts / "S-001.receipt.json").read_text()
        self.assertNotIn("secret", raw)
        self.assertNotIn('"value"', raw)
        self.assertEqual(r["privacy"], "hashes_only")
        self.assertEqual(stat.S_IMODE(self.receipts.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.receipts / "S-001.receipt.json").stat().st_mode), 0o600)

    def test_keep_text_is_opt_in(self):
        r = self.step({"checks": [self.file_check(), self.ax_check(keep_text=True)]}, lambda: (self.save(), self.bump()))
        self.assertEqual(r["after"]["checks"][1]["value"], "1")
        self.assertEqual(r["privacy"], "text_kept_where_opted_in")

    def test_bad_expectations_refused(self):
        for bad in ({}, {"checks": []}, {"checks": [{"source": "shell", "cmd": "rm"}]},
                    {"checks": [self.file_check("overwritten")]},
                    {"checks": [self.file_check()], "watch": [{"source": "dir"}]}):
            with self.assertRaises(Denied):
                R.validate_expectation(bad)
        with self.assertRaises(Denied):
            R.begin("../x", {"checks": [self.file_check()]}, self.receipts)

    def test_command_line(self):
        ui = self.root / "ui.json"; ui.write_text(json.dumps({"id": "s", "value": 1}))
        exp = self.root / "expect.json"
        exp.write_text(json.dumps({"checks": [self.file_check(), {"source": "a2ui", "path": str(ui), "component": "s", "change": "changed"}]}))
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1])}
        run = lambda *a: json.loads(subprocess.run([sys.executable, "-m", "safe_mac_control.receipts", *a],
                                                   capture_output=True, text=True, env=env).stdout)
        self.assertEqual(run("begin", "--step", "CLI", "--expect", str(exp), "--receipts", str(self.receipts))["status"], "BEGUN")
        self.save(); ui.write_text(json.dumps({"id": "s", "value": 2}))
        self.assertEqual(run("end", "--step", "CLI", "--receipts", str(self.receipts))["verdict"], "VERIFIED")
        self.assertEqual(run("show", "--step", "CLI", "--receipts", str(self.receipts))["verdict"], "VERIFIED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
