"""Turn one current observed demo snapshot into one exact, reviewable request."""
import argparse
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser()
parser.add_argument("snapshot", type=Path)
parser.add_argument("--id", required=True)
args = parser.parse_args()
snapshot = json.loads(args.snapshot.read_text())
if snapshot.get("status") != "OBSERVED" or snapshot.get("bundle") != "org.klara.SafeMacDemo":
    raise SystemExit("Need an actual observed Safe Mac Demo snapshot")
def one(identifier):
    rows = [x for x in snapshot["elements"] if x.get("identifier") == identifier]
    if len(rows) != 1:
        raise SystemExit("Demo target is missing or ambiguous")
    return rows[0]
button = one("safe-demo-increment")
counter = one("safe-demo-count")
def select(row):
    return {k: row.get(k, "") for k in ("role", "title", "identifier", "description")}
request = {"request_id": args.id, "operation": "press", "snapshot": snapshot, "target": select(button),
           "postcondition": {"selector": select(counter), "value": str(int(counter["value"]) + 1)}}
json.dump(request, sys.stdout, sort_keys=True)
print()
