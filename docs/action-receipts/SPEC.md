# Action Receipts: spec v0 (experimental)

## What is built, and what isn't

| Part | State |
|---|---|
| Expectation checks, verdict rules, once-only step store, private receipt files, CLI | Built; 19 offline tests pass on Linux, Python 3.13 |
| File and folder readings (level 2) | Built and tested with real files |
| Generated-UI JSON readings, e.g. A2UI (level 1) | Built; tested with a hand-written JSON file, not real A2UI agent output |
| Accessibility readings (level 3) | Built on this package's existing read-only `inspect`; tested **only with a stand-in**. Limited to the apps `inspect` already allows (the demo app and Calculator) |
| Screenshots | Not included in v0 |
| Planted-failure evaluation | **Not run.** Needs a Mac |

Each verdict rule was also checked by deliberately breaking it: five broken versions each made the tests fail.

## Expectation format (as built)

```json
{
  "checks": [
    { "source": "file", "path": "~/Documents/report.docx", "change": "modified" },
    { "source": "file_count", "dir": "~/Outbox", "pattern": "*.eml", "delta": 1 },
    { "source": "a2ui", "path": "/tmp/agent-ui.json", "component": "status", "change": "equals", "value": "Saved" },
    { "source": "ax", "bundle": "org.klara.SafeMacDemo", "window": "Safe Mac Demo",
      "element": { "identifier": "safe-demo-count" }, "change": "changed" }
  ],
  "watch": [ { "source": "dir", "dir": "~/Documents" } ]
}
```

- `file` changes: `modified` (content hash differs), `created`, `deleted`. A file whose time changed but whose content didn't is **not** counted as modified.
- `file_count`: the number of entries matching `pattern` should change by `delta`. A multiple of `delta` (2, 3…) means `REPEATED`.
- `a2ui` and `ax`: `changed`, or `equals` with a `value`.
- `watch`: things that should **not** change. If the expected target didn't change but a watched item did, the verdict is `WRONG_TARGET`.
- `"keep_text": true` on a check stores readable text for that check; otherwise only hashes are stored.

## Verdict rules (as built, in order)

1. Any reading unavailable → `UNKNOWN_EFFECT`.
2. Any check changed, but not as expected → `UNKNOWN_EFFECT`.
3. Nothing expected changed: a watched item changed → `WRONG_TARGET`; otherwise → `NO_CHANGE`.
4. Some checks changed and some didn't → `UNKNOWN_EFFECT` (sources disagree).
5. The expected change happened but a watched item also changed → `UNKNOWN_EFFECT`.
6. A count changed by a multiple of what was expected → `REPEATED`.
7. Fewer than two **different kinds** of source agree → `UNKNOWN_EFFECT`. Two file checks are one kind.
8. Otherwise → `VERIFIED`.

## Prior art (checked 2026-11-19, not exhaustive)

- **[agent-desktop](https://flaviocopes.com/agent-desktop/)** (Vercel Labs, Apache-2.0; macOS, Windows, Linux) reads the accessibility tree and reports a delivery state such as "delivered_verified", a retry-safety flag and incomplete snapshots. This is the closest tool. Its "verified" refers to the control's state, not the underlying document: in the article's test, a text field was verified but the file on disk had not changed. Comparing against the document itself is the gap this design aims at. Contributing the idea there may be a better route than a separate tool.
- **[VisCritic](https://arxiv.org/pdf/2606.24525)** compares before and after **screenshots** and outputs success, no-op, wrong-target, page-error or timeout. Similar verdicts, vision only.
- **[Trailblaze](https://block.github.io/trailblaze/devlog/2026-06-30-assertwaypoint-tool-replaces-postcondition-field/)** (Block) checks step waypoints in UI tests, mainly on mobile.
- **["Teach it to stop, not just to click"](https://arxiv.org/pdf/2607.17136)** uses a separate verifier for task completion; it notes duplicated actions as a failure but doesn't detect them directly.

What did not appear in this check: requiring two **independent kinds** of source before saying "verified", with an explicit `REPEATED` verdict and a refusal to guess.

## Original proposal (v0 design notes)

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
