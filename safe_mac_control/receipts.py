"""Action Receipts (experimental, observe-only).

Wraps someone else's action: `begin` records the state before it, `end` records the state after it,
compares the two, and stores one verdict. It never clicks, types, retries or changes anything it observes.

Verdicts: VERIFIED, NO_CHANGE, REPEATED, WRONG_TARGET, UNKNOWN_EFFECT.
VERIFIED needs agreement from at least two independent kinds of source.
Readings are stored as hashes unless a check opts in with "keep_text": true.

Sources (highest level first):
  1 generated_ui  A2UI / MCP Apps style JSON an agent hands over (a file path)
  2 filesystem    file state (size, mtime, SHA-256) and folder entry counts
  3 interface     macOS Accessibility, through this package's existing read-only `inspect`
                  (only the apps that `inspect` already allows)
"""

import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

from .core import Denied, _exclusive_at, _private_directory, _read_at, canonical, require

VERDICTS = ("VERIFIED", "NO_CHANGE", "REPEATED", "WRONG_TARGET", "UNKNOWN_EFFECT")
KIND = {"file": "filesystem", "file_count": "filesystem", "a2ui": "generated_ui", "ax": "interface"}
LEVEL = {"generated_ui": 1, "filesystem": 2, "interface": 3}
FILE_CHANGES = ("modified", "created", "deleted")  # "must not change" belongs in watch
MAX_HASH_BYTES = 256 * 1024 * 1024
STEP_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
CHECK_KEYS = {
    "file": ({"source", "path", "change"}, {"keep_text"}),
    "file_count": ({"source", "dir", "pattern", "delta"}, set()),
    "a2ui": ({"source", "path", "component", "change"}, {"value", "keep_text"}),
    "ax": ({"source", "bundle", "window", "element", "change"}, {"value", "keep_text"}),
}
WATCH_KEYS = {"file": {"source", "path"}, "dir": {"source", "dir"}}


def _h(data):
    return hashlib.sha256(data if isinstance(data, bytes) else canonical(data)).hexdigest()


# ---------------------------------------------------------------------------------------------
# Expectation format
# ---------------------------------------------------------------------------------------------

def validate_expectation(exp):
    require(isinstance(exp, dict) and set(exp) <= {"checks", "watch"} and "checks" in exp, "expectation_shape")
    checks, watch = exp["checks"], exp.get("watch", [])
    require(isinstance(checks, list) and 1 <= len(checks) <= 16, "checks_count")
    require(isinstance(watch, list) and len(watch) <= 16, "watch_count")
    for c in checks:
        require(isinstance(c, dict) and c.get("source") in CHECK_KEYS, "check_source")
        need, optional = CHECK_KEYS[c["source"]]
        require(need <= set(c) <= need | optional, "check_fields:" + c["source"])
        if c["source"] == "file":
            require(c["change"] in FILE_CHANGES, "file_change")
        elif c["source"] == "file_count":
            require(type(c["delta"]) is int and type(c["pattern"]) is str and "/" not in c["pattern"], "file_count_fields")
        elif c["source"] == "a2ui":
            require(c["change"] in ("changed", "equals") and type(c["component"]) is str, "a2ui_fields")
            require(c["change"] != "equals" or "value" in c, "a2ui_value_required")
        else:
            require(c["change"] in ("changed", "equals") and isinstance(c["element"], dict), "ax_fields")
            require(c["change"] != "equals" or type(c.get("value")) is str, "ax_value_required")
    for w in watch:
        require(isinstance(w, dict) and w.get("source") in WATCH_KEYS and set(w) == WATCH_KEYS[w["source"]], "watch_fields")
    return exp


# ---------------------------------------------------------------------------------------------
# Readings. Each returns a small dict; {"available": False, "reason": ...} when it can't read.
# ---------------------------------------------------------------------------------------------

def _file_state(path, keep_text=False):
    p = Path(path).expanduser()
    try:
        st = p.stat()
    except FileNotFoundError:
        return {"available": True, "exists": False}
    except OSError as exc:
        return {"available": False, "reason": "stat_failed:" + type(exc).__name__}
    if not p.is_file():
        return {"available": False, "reason": "not_a_regular_file"}
    out = {"available": True, "exists": True, "size": st.st_size, "mtime_ns": st.st_mtime_ns}
    if st.st_size <= MAX_HASH_BYTES:
        digest = hashlib.sha256()
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    digest.update(chunk)
        except OSError as exc:
            return {"available": False, "reason": "read_failed:" + type(exc).__name__}
        out["sha256"] = digest.hexdigest()
        if keep_text and st.st_size <= 4096:
            out["text"] = p.read_bytes().decode("utf-8", "replace")
    else:
        out["sha256"] = None  # too large to hash; size and mtime only
    return out


def _dir_entries(path):
    p = Path(path).expanduser()
    try:
        names = sorted(os.listdir(p))
    except OSError as exc:
        return None, "list_failed:" + type(exc).__name__
    return names, None


def _file_count(c):
    names, err = _dir_entries(c["dir"])
    if err:
        return {"available": False, "reason": err}
    match = [n for n in names if fnmatch.fnmatch(n, c["pattern"])]
    return {"available": True, "count": len(match), "names_sha256": _h(match)}


def _dir_digest(path):
    names, err = _dir_entries(path)
    if err:
        return {"available": False, "reason": err}
    rows = []
    for n in names:
        try:
            st = os.stat(os.path.join(os.path.expanduser(path), n), follow_symlinks=False)
            rows.append([n, st.st_size, st.st_mtime_ns])
        except OSError:
            rows.append([n, None, None])
    return {"available": True, "count": len(names), "digest": _h(rows)}


def _find_component(node, component):
    if isinstance(node, dict):
        if node.get("id") == component or node.get("componentId") == component:
            return node
        values = node.values()
    elif isinstance(node, list):
        values = node
    else:
        return None
    for v in values:
        found = _find_component(v, component)
        if found is not None:
            return found
    return None


def _a2ui(c):
    try:
        raw = Path(c["path"]).expanduser().read_bytes()
        require(len(raw) <= 4 * 1024 * 1024, "a2ui_too_large")
        doc = json.loads(raw)
    except FileNotFoundError:
        return {"available": False, "reason": "a2ui_missing"}
    except Exception as exc:
        return {"available": False, "reason": "a2ui_unreadable:" + type(exc).__name__}
    comp = _find_component(doc, c["component"])
    if comp is None:
        return {"available": False, "reason": "component_not_found"}
    value = comp.get("value", comp.get("text"))
    out = {"available": True, "component_sha256": _h(comp), "value_sha256": _h(value)}
    if c.get("keep_text"):
        out["value"] = value
    return out


def _ax(c, backend):
    if backend is None:
        return {"available": False, "reason": "accessibility_backend_unavailable"}
    try:
        from .core import inspect
        snap = inspect(backend, c["bundle"], c["window"])
    except Exception as exc:
        return {"available": False, "reason": "inspect_failed:" + (str(exc) if isinstance(exc, Denied) else type(exc).__name__)}
    if snap.get("status") != "OBSERVED":
        return {"available": False, "reason": "inspect_status:" + str(snap.get("status"))}
    want = c["element"]
    rows = [r for r in snap.get("elements", []) if all(r.get(k, "") == v for k, v in want.items())]
    if len(rows) != 1:
        return {"available": False, "reason": "element_missing_or_ambiguous"}
    if rows[0].get("redacted"):
        return {"available": False, "reason": "element_redacted"}
    value = rows[0].get("value", "")
    out = {"available": True, "frontmost": snap.get("frontmost"), "value_sha256": _h(value)}
    if c.get("keep_text"):
        out["value"] = value
    return out


def read_check(c, ax_backend=None):
    src = c["source"]
    if src == "file":
        return _file_state(c["path"], c.get("keep_text", False))
    if src == "file_count":
        return _file_count(c)
    if src == "a2ui":
        return _a2ui(c)
    return _ax(c, ax_backend)


def read_watch(w):
    return _file_state(w["path"]) if w["source"] == "file" else _dir_digest(w["dir"])


def snapshot(exp, ax_backend=None):
    return {"checks": [read_check(c, ax_backend) for c in exp["checks"]],
            "watch": [read_watch(w) for w in exp.get("watch", [])],
            "at": time.time()}


# ---------------------------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------------------------

def _strip(r):
    return {k: v for k, v in r.items() if k not in ("text", "value")} if r.get("available") else r


def judge_check(c, before, after):
    """EXPECTED, NONE, EXTRA (more than once), OTHER (changed, but not as expected) or UNAVAILABLE."""
    if not (before.get("available") and after.get("available")):
        return "UNAVAILABLE"
    src = c["source"]
    if src == "file":
        same = _strip(before) == _strip(after)
        want = c["change"]
        if same:
            return "NONE"
        if want == "created":
            return "EXPECTED" if (not before["exists"] and after["exists"]) else "OTHER"
        if want == "deleted":
            return "EXPECTED" if (before["exists"] and not after["exists"]) else "OTHER"
        if not (before["exists"] and after["exists"]):
            return "OTHER"
        if before.get("sha256") and before.get("sha256") == after.get("sha256"):
            return "OTHER"  # touched (time changed) but content identical
        return "EXPECTED"
    if src == "file_count":
        delta = after["count"] - before["count"]
        if delta == 0 and before["names_sha256"] == after["names_sha256"]:
            return "NONE"
        if delta == c["delta"]:
            return "EXPECTED"
        if c["delta"] > 0 and delta > c["delta"] and delta % c["delta"] == 0:
            return "EXTRA"
        return "OTHER"
    # a2ui and ax
    if c["change"] == "changed":
        return "NONE" if before["value_sha256"] == after["value_sha256"] else "EXPECTED"
    want = _h(c["value"])
    if after["value_sha256"] == want:
        return "NONE" if before["value_sha256"] == want else "EXPECTED"
    return "NONE" if before["value_sha256"] == after["value_sha256"] else "OTHER"


def verdict(exp, before, after):
    outcomes = [judge_check(c, b, a) for c, b, a in zip(exp["checks"], before["checks"], after["checks"])]
    watch_changed = [i for i, (b, a) in enumerate(zip(before["watch"], after["watch"]))
                     if not (b.get("available") and a.get("available")) or b != a]
    kinds_expected = {KIND[c["source"]] for c, o in zip(exp["checks"], outcomes) if o in ("EXPECTED", "EXTRA")}
    detail = {"check_outcomes": outcomes, "watch_changed": watch_changed,
              "independent_kinds_agreeing": sorted(kinds_expected)}

    def out(v, reason):
        return {"verdict": v, "reason": reason, **detail}

    if "UNAVAILABLE" in outcomes:
        return out("UNKNOWN_EFFECT", "a_reading_was_unavailable")
    if "OTHER" in outcomes:
        return out("UNKNOWN_EFFECT", "changed_but_not_as_expected")
    if all(o == "NONE" for o in outcomes):
        return out("WRONG_TARGET", "expected_target_unchanged_but_watched_item_changed") if watch_changed \
            else out("NO_CHANGE", "nothing_relevant_changed")
    if "NONE" in outcomes:
        return out("UNKNOWN_EFFECT", "sources_disagree")
    if watch_changed:
        return out("UNKNOWN_EFFECT", "expected_change_plus_unexpected_side_change")
    if "EXTRA" in outcomes:
        return out("REPEATED", "change_seen_more_than_once")
    if len(kinds_expected) < 2:
        return out("UNKNOWN_EFFECT", "only_one_kind_of_source_confirms")
    return out("VERIFIED", "two_or_more_independent_sources_agree")


# ---------------------------------------------------------------------------------------------
# Once-only step store
# ---------------------------------------------------------------------------------------------

def begin(step, exp, receipt_dir, ax_backend=None):
    require(type(step) is str and STEP_ID.fullmatch(step), "invalid_step_id")
    validate_expectation(exp)
    fd = _private_directory(receipt_dir)
    try:
        record = {"step": step, "expectation": exp, "expectation_sha256": _h(exp),
                  "before": snapshot(exp, ax_backend)}
        try:
            _exclusive_at(fd, step + ".before.json", record)
        except FileExistsError:
            raise Denied("step_already_begun")
        return {"status": "BEGUN", "step": step}
    finally:
        os.close(fd)


def end(step, receipt_dir, ax_backend=None):
    require(type(step) is str and STEP_ID.fullmatch(step), "invalid_step_id")
    fd = _private_directory(receipt_dir)
    try:
        try:
            return {**_read_at(fd, step + ".receipt.json"), "replayed_receipt": True}
        except FileNotFoundError:
            pass
        try:
            rec = _read_at(fd, step + ".before.json")
        except FileNotFoundError:
            raise Denied("step_not_begun")
        exp = validate_expectation(rec["expectation"])
        require(rec.get("expectation_sha256") == _h(exp), "expectation_tampered")
        after = snapshot(exp, ax_backend)
        result = verdict(exp, rec["before"], after)
        sources = sorted({(KIND[c["source"]], LEVEL[KIND[c["source"]]]) for c in exp["checks"]}, key=lambda s: s[1])
        receipt = {"step": step, **result, "sources": [{"kind": k, "level": lv} for k, lv in sources],
                   "expectation_sha256": rec["expectation_sha256"],
                   "before": rec["before"], "after": after,
                   "privacy": "text_kept_where_opted_in" if any(c.get("keep_text") for c in exp["checks"]) else "hashes_only"}
        try:
            _exclusive_at(fd, step + ".receipt.json", receipt)
        except FileExistsError:
            return {**_read_at(fd, step + ".receipt.json"), "replayed_receipt": True}
        return {**receipt, "replayed_receipt": False}
    finally:
        os.close(fd)


def show(step, receipt_dir):
    require(type(step) is str and STEP_ID.fullmatch(step), "invalid_step_id")
    fd = _private_directory(receipt_dir)
    try:
        return _read_at(fd, step + ".receipt.json")
    except FileNotFoundError:
        raise Denied("no_receipt_for_step")
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------------------------

def _ax_backend():
    if sys.platform != "darwin":
        return None
    executable = Path(__file__).resolve().parents[1] / "build" / "native-helper"
    if not executable.is_file():
        return None
    from .core import NativeBackend
    return NativeBackend(executable)


def main(argv=None):
    from .__main__ import load_json
    parser = argparse.ArgumentParser(prog="python3 -m safe_mac_control.receipts",
                                     description="Observe-only action receipts. Never acts or retries.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("begin", help="Record the state before someone else's action")
    b.add_argument("--step", required=True)
    b.add_argument("--expect", type=Path, required=True)
    b.add_argument("--receipts", type=Path, required=True)
    e = sub.add_parser("end", help="Record the state after the action and store one verdict")
    e.add_argument("--step", required=True)
    e.add_argument("--receipts", type=Path, required=True)
    s = sub.add_parser("show", help="Print a stored receipt")
    s.add_argument("--step", required=True)
    s.add_argument("--receipts", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "begin":
            out = begin(args.step, load_json(args.expect), args.receipts, _ax_backend())
        elif args.command == "end":
            out = end(args.step, args.receipts, _ax_backend())
        else:
            out = show(args.step, args.receipts)
    except Exception as exc:
        out = {"status": "DENIED", "reason": str(exc) if isinstance(exc, Denied) else type(exc).__name__}
    print(json.dumps(out, sort_keys=True, ensure_ascii=False))
    return 0 if out.get("status") == "BEGUN" or out.get("verdict") == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
