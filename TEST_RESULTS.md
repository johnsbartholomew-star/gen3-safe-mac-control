# Verification results — November 2, 2026

These results distinguish builder observations, separate independent execution and synthetic challenges. Independent acceptance is limited to the exact source and narrow demo on the tested Mac; it is not a general application or security certification.

## Independent checks

| Check | Actual result |
|---|---|
| Fresh source copy | Frozen archive and all 15 original source members matched; executable/test/build-script bytes remained unchanged |
| Clean build | PASS; Python 3.14.7, Swift 6.4.2, Xcode 27.2, Apple Silicon macOS 26.6.2 |
| Documented suite | 19/19 PASS, run once on the independent copy |
| Seven additional challenges | Unsupported bundle, editable target, secure postcondition and stale snapshot refused before injected backend entry; injected ambiguity/changed-tree denials preserved; injected timeout retained as UNKNOWN_EFFECT |
| First native admission | DENIED: accessibility_unavailable in the restricted execution context; no fixture launch or native action |
| Separately authorized native-only admission | Exact retained binary identities; Accessibility access observed using the approved command route; zero existing same-bundle fixtures |
| Documented convenience demo | One `demo --perform` invocation, EXIT0 / VERIFIED; action and expected postcondition reported |
| Independent counter observations | Same fixture PID/window, counter 0 before and 1 after; post-action fingerprint matched |
| Receipts | Private 0700 directory, 0600 intent/result, matching request ID and request digest |
| Owned fixture closure | Exact PID and app path checked; termination requested; subsequent same-bundle count zero |
| Reviewer disposition | ACCEPT_ALPHA for this narrow standalone candidate on this Mac |
| Other contexts/apps | Not accepted by this result; see LIMITATIONS.md |

No build or suite was repeated for the second native-only session. No macOS permission, task-wide access mode, package source or guard was changed. The earlier permission denial and two older uncorrelated handoff outcomes remain preserved privately; the latter remain UNKNOWN, not reclassified as failed or harmless.

## Preserved builder observations

The builder compiled the helper and fixture and passed 19 tests. Its initial test run had three failures and seven errors because the test fixture used a macOS `/var` symlink; the fixture was changed to use its resolved path, without weakening the production path guard. A first native action request was denied after the Accessibility tree changed. A separately observed current-state request later verified a counter change from 0 to 1. These observations are retained separately and are not presented as independent results.

## What the tests do not prove

The documented suite covers unsupported app/operation, stale/future snapshots, focus, editable/secure selectors, wildcard/postcondition rejection, receipt path/symlink/private-mode checks, duplicate JSON keys, same-ID conflict and receipt return, interruption after intent, timeout/malformed native output, and preservation of denials. Its backends and the seven extra challenge backends are synthetic; their output cannot prove native adversarial behavior.

The real independent demo tests one allowed button on one disposable app. Calculator, activation/raise, production applications, hostile-user behavior, another host and other macOS/hardware configurations were not qualified. Exact command outputs, source identities and native observations are retained in the private review record; raw UI snapshots, user paths and private role records are excluded from this source release. The final manifest identifies this package's source files; final documentation/license changes do not alter the tested code.
