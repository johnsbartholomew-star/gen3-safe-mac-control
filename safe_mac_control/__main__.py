import argparse
import json
from pathlib import Path
import sys

from .core import BUNDLES, Denied, NativeBackend, execute, inspect


def load_json(path):
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise Denied("duplicate_json_key")
            out[key] = value
        return out
    raw = Path(path).read_bytes()
    if len(raw) > 65536:
        raise Denied("input_too_large")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(Denied("nonfinite_json")))


def main():
    parser = argparse.ArgumentParser(description="Gen3 standalone alpha: exact Mac targets, one-attempt effects.")
    sub = parser.add_subparsers(dest="command", required=True)
    observe = sub.add_parser("inspect", help="Read one exact supported app window; no UI action")
    observe.add_argument("--bundle", choices=BUNDLES, required=True)
    observe.add_argument("--window", required=True)
    run = sub.add_parser("run", help="One explicit request; durable local receipt; never blindly retries")
    run.add_argument("request", type=Path)
    run.add_argument("--receipts", type=Path, required=True)
    demo = sub.add_parser("demo", help="Inspect and press the disposable demo's Increment button once")
    demo.add_argument("--perform", action="store_true", required=True)
    demo.add_argument("--request-id", required=True)
    demo.add_argument("--receipts", type=Path, required=True)
    sub.add_parser("supported")
    args = parser.parse_args()
    try:
        if args.command == "supported":
            out = {"bundles": list(BUNDLES), "operations": ["inspect", "activate", "raise", "press"]}
        else:
            if sys.platform != "darwin":
                raise Denied("macos_required")
            executable = Path(__file__).resolve().parents[1] / "build" / "native-helper"
            if not executable.is_file():
                raise Denied("build_native_helper_first")
            backend = NativeBackend(executable)
            if args.command == "inspect":
                out = inspect(backend, args.bundle, args.window)
            elif args.command == "demo":
                snapshot = inspect(backend, "org.klara.SafeMacDemo", "Safe Mac Demo")
                if snapshot.get("status") != "OBSERVED":
                    out = snapshot
                else:
                    def one(identifier):
                        rows = [r for r in snapshot["elements"] if r.get("identifier") == identifier]
                        if len(rows) != 1:
                            raise Denied("demo_target_missing_or_ambiguous")
                        return rows[0]
                    def select(row):
                        return {k: row.get(k, "") for k in ("role", "title", "identifier", "description")}
                    button, counter = one("safe-demo-increment"), one("safe-demo-count")
                    value = counter.get("value", "")
                    if not value.isascii() or not value.isdecimal() or len(value) > 8:
                        raise Denied("demo_counter_not_an_integer")
                    request = {"request_id": args.request_id, "operation": "press", "snapshot": snapshot,
                               "target": select(button), "postcondition": {"selector": select(counter), "value": str(int(value) + 1)}}
                    out = execute(request, args.receipts, backend)
            else:
                out = execute(load_json(args.request), args.receipts, backend)
    except Exception as exc:
        out = {"status": "DENIED", "reason": str(exc) if isinstance(exc, Denied) else type(exc).__name__}
    print(json.dumps(out, sort_keys=True, ensure_ascii=False))
    return 0 if out.get("status") in (None, "OBSERVED", "VERIFIED") else 2


if __name__ == "__main__":
    raise SystemExit(main())
