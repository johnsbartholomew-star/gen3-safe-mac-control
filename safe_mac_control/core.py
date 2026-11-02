"""Validation and local one-attempt receipts; no private Gen3 dependencies."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

BUNDLES = ("com.apple.calculator", "org.klara.SafeMacDemo")
SELECTOR_KEYS = {"role", "title", "identifier", "description"}
SNAPSHOT_KEYS = {"status", "bundle", "window", "pid", "fingerprint", "elements", "frontmost", "observed_at"}


class Denied(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def require(ok, reason):
    if not ok:
        raise Denied(reason)


def selector(value):
    require(isinstance(value, dict) and set(value) == SELECTOR_KEYS, "exact_selector_required")
    require(all(type(v) is str and len(v) <= 512 and "\x00" not in v for v in value.values()), "invalid_selector")
    require(value["role"] not in ("AXTextField", "AXSecureTextField", "AXTextArea"), "editable_or_secure_field")
    require(value["identifier"] != "" or value["title"] != "" or value["description"] != "", "empty_selector")
    require(all(v != "*" for v in value.values()), "wildcard_forbidden")


def validate_request(request, now=None):
    require(isinstance(request, dict), "request_object_required")
    op = request.get("operation")
    require(op in ("activate", "raise", "press"), "operation_not_allowed")
    expected = {"request_id", "operation", "snapshot"}
    if op == "press":
        expected |= {"target", "postcondition"}
    require(set(request) == expected, "unknown_or_missing_request_field")
    require(type(request["request_id"]) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", request["request_id"]), "invalid_request_id")
    snap = request["snapshot"]
    require(isinstance(snap, dict) and set(snap) == SNAPSHOT_KEYS, "snapshot_shape")
    require(snap["status"] == "OBSERVED" and snap["bundle"] in BUNDLES, "unsupported_snapshot")
    require(type(snap["window"]) is str and 0 < len(snap["window"]) <= 512, "exact_window_required")
    require(type(snap["pid"]) is int and snap["pid"] > 0, "invalid_pid")
    require(type(snap["fingerprint"]) is str and re.fullmatch(r"[a-f0-9]{64}", snap["fingerprint"]), "invalid_fingerprint")
    require(type(snap["observed_at"]) in (int, float), "invalid_snapshot_time")
    age = (time.time() if now is None else now) - snap["observed_at"]
    require(0 <= age <= 30, "snapshot_stale_or_future")
    require(type(snap["frontmost"]) is bool and isinstance(snap["elements"], list), "snapshot_shape")
    if op != "activate":
        require(snap["frontmost"], "target_not_frontmost")
    if op == "press":
        selector(request["target"])
        require(request["target"]["role"] == "AXButton", "only_buttons_allowed")
        post = request["postcondition"]
        require(isinstance(post, dict) and set(post) == {"selector", "value"}, "postcondition_required")
        selector(post["selector"])
        require(post["selector"]["role"] == "AXStaticText", "static_postcondition_required")
        require(type(post["value"]) is str and len(post["value"]) <= 512, "invalid_postcondition")
    return request


def _private_directory(path):
    path = Path(path).absolute()
    # Existing ancestors must not be symlinks. This is local custody, not an OS sandbox.
    for p in reversed([path, *path.parents]):
        try:
            st = p.lstat()
        except FileNotFoundError:
            require(p == path, "receipt_parent_missing")
            os.mkdir(p, 0o700)
            st = p.lstat()
        require(stat.S_ISDIR(st.st_mode), "receipt_path_not_directory")
        if p == path:
            require(st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) == 0o700, "receipt_directory_not_private")
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _read_at(fd, name):
    f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
    with os.fdopen(f, "rb") as stream:
        st = os.fstat(stream.fileno())
        require(stat.S_ISREG(st.st_mode) and st.st_uid == os.getuid() and st.st_nlink == 1
                and stat.S_IMODE(st.st_mode) == 0o600 and st.st_size <= 131072, "receipt_custody")
        return json.loads(stream.read(131073))


def _exclusive_at(fd, name, data):
    f = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    with os.fdopen(f, "wb") as stream:
        stream.write(canonical(data) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.fsync(fd)


class NativeBackend:
    def __init__(self, executable):
        self.executable = str(executable)

    def __call__(self, request):
        result = subprocess.run([self.executable], input=canonical(request), capture_output=True, timeout=12, check=False)
        require(len(result.stdout) <= 1048576, "native_output_too_large")
        data = json.loads(result.stdout)
        require(isinstance(data, dict) and type(data.get("status")) is str, "invalid_native_result")
        require(result.returncode == 0 or data["status"] != "VERIFIED", "native_exit_mismatch")
        return data


def inspect(backend, bundle, window):
    require(bundle in BUNDLES and type(window) is str and 0 < len(window) <= 512, "unsupported_target")
    out = backend({"operation": "inspect", "bundle": bundle, "window": window})
    if out.get("status") == "OBSERVED":
        out["observed_at"] = time.time()
    return out


def execute(request, receipt_dir, backend):
    """Only this invocation may dispatch. Incomplete receipts permanently fence its ID."""
    # Validate identity before looking up a receipt, but allow a prior result after expiry.
    require(isinstance(request, dict), "request_object_required")
    rid = request.get("request_id")
    require(type(rid) is str and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", rid), "invalid_request_id")
    digest = hashlib.sha256(canonical(request)).hexdigest()
    fd = _private_directory(receipt_dir)
    try:
        try:
            previous = _read_at(fd, rid + ".intent.json")
        except FileNotFoundError:
            previous = None
        if previous is not None:
            require(previous.get("request_sha256") == digest, "request_id_conflict")
            try:
                saved = _read_at(fd, rid + ".result.json")
                require(saved.get("request_sha256") == digest, "result_digest_conflict")
                return {**saved, "replayed_receipt": True, "dispatched_this_call": False}
            except FileNotFoundError:
                return {"status": "UNKNOWN_EFFECT", "reason": "prior_attempt_incomplete_no_retry",
                        "request_id": rid, "dispatched_this_call": False}
        validate_request(request)
        try:
            _exclusive_at(fd, rid + ".intent.json", {"request_sha256": digest, "request_id": rid,
                                                    "state": "MAY_DISPATCH", "created_at": time.time()})
        except FileExistsError:
            return {"status": "UNKNOWN_EFFECT", "reason": "concurrent_attempt_no_retry", "dispatched_this_call": False}
        try:
            native = backend(request)
            require(native.get("status") in ("VERIFIED", "DENIED", "UNKNOWN_EFFECT"), "unexpected_native_status")
            out = dict(native)
        except Exception as exc:
            out = {"status": "UNKNOWN_EFFECT", "reason": "native_result_unavailable_no_retry",
                   "error_class": type(exc).__name__}
        out.update(request_id=rid, request_sha256=digest, dispatched_this_call=True, replayed_receipt=False)
        # dispatched_this_call means backend was entered, not that a UI effect is proven.
        try:
            _exclusive_at(fd, rid + ".result.json", out)
        except Exception as exc:
            return {"status": "UNKNOWN_EFFECT", "reason": "result_preservation_failed_no_retry",
                    "request_id": rid, "error_class": type(exc).__name__}
        return out
    finally:
        os.close(fd)
