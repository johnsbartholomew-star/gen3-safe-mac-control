# Action Receipts: draft spec v0 (proposal, not built)

## Scope (v0)

- macOS only, the current user's own session.
- Observes; never acts.
- Sources in v0: **file state** (path, size, modified time, SHA-256), **Accessibility** (frontmost app bundle ID,
  window title, focused element role, title and value hash), and optional **A2UI/MCP Apps JSON** when an agent
  hands it over. Screenshots are out of scope for v0.

## Interface (sketch)

```sh
receipts begin  --step S-001 --expect expect.json   # snapshot "before"
#   ... the agent performs its action ...
receipts end    --step S-001                        # snapshot "after", compare, write receipt
receipts show   --step S-001
```

`expect.json` says what should change, for example:

```json
{ "target": { "file": "~/Documents/report.docx" },
  "change": "content_changed_once",
  "app": "com.microsoft.Word" }
```

A step ID can be used once. Re-running `end` for the same ID returns the stored receipt; it never re-observes.

## Receipt (sketch)

```json
{
  "step": "S-001",
  "verdict": "VERIFIED",
  "expected": { "target": { "file": "~/Documents/report.docx" }, "change": "content_changed_once" },
  "readings": [
    { "source": "file", "level": 2, "before": { "mtime": 1763560000, "sha256": "ab12…" },
      "after": { "mtime": 1763560042, "sha256": "cd34…" } },
    { "source": "accessibility", "level": 3, "before": { "window": "report.docx — Edited" },
      "after": { "window": "report.docx" } }
  ],
  "agreement": "both_sources_agree",
  "notes": [],
  "privacy": "hashes_only"
}
```

## Verdict rules

1. Two sources agree the expected change happened, once, on the expected target → `VERIFIED`.
2. Both show no relevant change → `NO_CHANGE`.
3. A change is seen on another target → `WRONG_TARGET`.
4. The change appears twice (for example, two new rows, or the file changed twice within the step) → `REPEATED`.
5. Any disagreement, missing reading or permission denial → `UNKNOWN_EFFECT`, with the reason.

One source alone can never produce `VERIFIED`; at best it gives `UNKNOWN_EFFECT` with a note that only one source was available.

## Privacy and safety

- Receipt directory `0700`, files `0600`, the same as the existing controls.
- Hashes only by default; text capture is opt-in per step.
- No network access. No helper runs in the background between steps.
- Accessibility permission is requested through macOS's normal prompt only; the tool never changes permissions.

## Evaluation (do this before writing code)

**Question:** does a two-source receipt catch more real failures than a screenshot-only check?

- **20 everyday tasks** on a disposable test account: save, save-as, rename, fill a form, send a draft to a test address, etc.
- **Planted failures,** about half the runs: saving to the wrong file, a double submit, a save that never finished,
  a dialog that silently cancelled, the right action in the wrong window.
- **Two checkers:** (a) a vision model looking at before and after screenshots; (b) the two-source receipt.
- **Scored by someone who didn't plant the failures,** blind to which checker produced which verdict.
- **Pass:** the receipt catches at least 30 percentage points more planted failures, with no more false alarms on clean runs.
- **Kill:** it doesn't. Write that down as the result.

## Open questions

- Which apps expose enough Accessibility detail to identify the target document reliably?
- How to handle apps that autosave continuously, where "changed once" is fuzzy.
- Whether browser steps should come in v0 (DOM via a user-controlled browser) or wait for v1.
- Prior art: check existing agent-evaluation and GUI-testing tools before building.
