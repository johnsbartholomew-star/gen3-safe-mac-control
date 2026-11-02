import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from safe_mac_control.core import Denied, canonical, execute, inspect, validate_request
from safe_mac_control.__main__ import load_json


def request():
    return {"request_id": "one", "operation": "raise", "snapshot": {
        "status": "OBSERVED", "bundle": "org.klara.SafeMacDemo", "window": "Safe Mac Demo",
        "pid": 100, "fingerprint": "a" * 64, "elements": [], "frontmost": True,
        "observed_at": time.time(),
    }}


class Controls(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        # macOS tempfile uses /var, a system symlink; test the physical path.
        self.root = Path(self.temp.name).resolve()
        self.receipts = self.root / "receipts"
        self.calls = []

    def tearDown(self):
        self.temp.cleanup()

    def backend(self, value):
        self.calls.append(value)
        return {"status": "VERIFIED", "postcondition_observed": True}

    def test_same_request_returns_receipt_without_second_call(self):
        r = request()
        self.assertEqual(execute(r, self.receipts, self.backend)["status"], "VERIFIED")
        replay = execute(r, self.receipts, self.backend)
        self.assertTrue(replay["replayed_receipt"])
        self.assertFalse(replay["dispatched_this_call"])
        self.assertEqual(len(self.calls), 1)

    def test_same_id_different_input_is_denied(self):
        r = request(); execute(r, self.receipts, self.backend)
        r["operation"] = "activate"
        with self.assertRaisesRegex(Denied, "request_id_conflict"):
            execute(r, self.receipts, self.backend)
        self.assertEqual(len(self.calls), 1)

    def test_timeout_is_unknown_and_never_retried(self):
        def timeout(r):
            self.calls.append(r)
            raise subprocess.TimeoutExpired("native-helper", 12)
        r = request()
        self.assertEqual(execute(r, self.receipts, timeout)["status"], "UNKNOWN_EFFECT")
        self.assertEqual(execute(r, self.receipts, timeout)["status"], "UNKNOWN_EFFECT")
        self.assertEqual(len(self.calls), 1)

    def test_crash_after_intent_never_calls_backend(self):
        self.receipts.mkdir(mode=0o700)
        r = request()
        path = self.receipts / "one.intent.json"
        path.write_bytes(canonical({"request_sha256": hashlib.sha256(canonical(r)).hexdigest()}))
        path.chmod(0o600)
        self.assertEqual(execute(r, self.receipts, self.backend)["status"], "UNKNOWN_EFFECT")
        self.assertEqual(self.calls, [])

    def test_negative_native_result_preserved(self):
        r = request()
        out = execute(r, self.receipts, lambda _: {"status": "DENIED", "reason": "semantic_target_not_unique"})
        self.assertEqual(out["status"], "DENIED")
        self.assertEqual(out["reason"], "semantic_target_not_unique")

    def test_malformed_result_after_backend_is_unknown(self):
        out = execute(request(), self.receipts, lambda _: {"status": "MAYBE"})
        self.assertEqual(out["status"], "UNKNOWN_EFFECT")

    def test_unapproved_app_never_reaches_backend(self):
        r = request(); r["snapshot"]["bundle"] = "com.apple.systempreferences"
        with self.assertRaisesRegex(Denied, "unsupported_snapshot"):
            execute(r, self.receipts, self.backend)
        self.assertEqual(self.calls, [])

    def test_stale_and_future_snapshots_denied(self):
        for delta in (-31, 5):
            r = request(); r["snapshot"]["observed_at"] = time.time() + delta
            with self.assertRaisesRegex(Denied, "stale_or_future"):
                execute(r, self.receipts, self.backend)
        self.assertEqual(self.calls, [])

    def test_nonfrontmost_effect_denied(self):
        r = request(); r["snapshot"]["frontmost"] = False
        with self.assertRaisesRegex(Denied, "target_not_frontmost"):
            validate_request(r)

    def test_unsupported_operation_denied(self):
        for op in ("type", "shell", "delete", "frame_click", "launch"):
            r = request(); r["operation"] = op
            with self.assertRaisesRegex(Denied, "operation_not_allowed"):
                validate_request(r)

    def press(self):
        r = request(); r["operation"] = "press"
        r["target"] = {"role": "AXButton", "title": "Increment", "identifier": "safe-demo-increment", "description": ""}
        r["postcondition"] = {"selector": {"role": "AXStaticText", "title": "", "identifier": "safe-demo-count", "description": ""}, "value": "1"}
        return r

    def test_secure_and_editable_fields_denied(self):
        for role in ("AXSecureTextField", "AXTextField", "AXTextArea"):
            r = self.press(); r["target"]["role"] = role
            with self.assertRaisesRegex(Denied, "editable_or_secure"):
                validate_request(r)

    def test_wildcards_and_missing_postconditions_denied(self):
        r = self.press(); r["target"]["identifier"] = "*"
        with self.assertRaisesRegex(Denied, "wildcard"):
            validate_request(r)
        r = self.press(); del r["postcondition"]
        with self.assertRaises(Denied):
            validate_request(r)

    def test_nonstatic_postcondition_denied(self):
        r = self.press(); r["postcondition"]["selector"]["role"] = "AXButton"
        with self.assertRaisesRegex(Denied, "static_postcondition_required"):
            validate_request(r)

    def test_ids_cannot_escape_receipt_directory(self):
        for value in ("../escape", "absolute/name", "", "a" * 65):
            r = request(); r["request_id"] = value
            with self.assertRaisesRegex(Denied, "invalid_request_id"):
                execute(r, self.receipts, self.backend)

    def test_receipt_directory_symlink_denied(self):
        self.receipts.symlink_to(self.root)
        with self.assertRaisesRegex(Denied, "not_directory"):
            execute(request(), self.receipts, self.backend)
        self.assertEqual(self.calls, [])

    def test_nonprivate_receipt_directory_denied(self):
        self.receipts.mkdir(mode=0o755)
        with self.assertRaisesRegex(Denied, "not_private"):
            execute(request(), self.receipts, self.backend)

    def test_symlink_receipt_does_not_dispatch(self):
        self.receipts.mkdir(mode=0o700)
        (self.receipts / "one.intent.json").symlink_to(self.root / "absent")
        with self.assertRaises(OSError):
            execute(request(), self.receipts, self.backend)
        self.assertEqual(self.calls, [])

    def test_duplicate_json_key_and_nonfinite_rejected(self):
        p = self.root / "input.json"
        for raw in ('{"operation":"raise","operation":"press"}', '{"observed_at":NaN}'):
            p.write_text(raw)
            with self.assertRaises(Denied):
                load_json(p)

    def test_inspection_is_a_distinct_operation(self):
        sent = []
        def reader(value):
            sent.append(value)
            return {"status": "DENIED", "reason": "accessibility_unavailable"}
        out = inspect(reader, "org.klara.SafeMacDemo", "Safe Mac Demo")
        self.assertEqual(out["status"], "DENIED")
        self.assertEqual(sent[0]["operation"], "inspect")
        self.assertFalse(self.receipts.exists())


if __name__ == "__main__":
    unittest.main()
