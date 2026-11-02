# Gen3 Safe Mac Control

Experimental source alpha, `0.1.0-alpha.1` (Python package version `0.1.0a1`).

A small standalone extraction of Gen3's native macOS controls: inspect an exact app window, activate or raise that window, and press a narrowly allowed Accessibility button with a checked postcondition. It runs locally using Python's standard library and a Swift helper. No Bridge, server, tunnel, model account or paid API is needed.

**Verified scope:** a separate reviewer built a clean copy on macOS 26.6.2 / Apple Silicon, passed all 19 documented control tests, and ran the documented native demo once. The demo returned `VERIFIED`; separate inspections confirmed the same fixture's counter changed from 0 to 1, and the owned app was closed. Seven additional challenges were synthetic, not native adversarial tests. Calculator, activation/raise, other Macs and other operating systems remain unqualified. This is not general-purpose desktop automation.

## Build and run from source

Requirements: macOS, Python 3.10 or later, and an already installed Apple Swift compiler available through `xcrun`. The builder observed Python 3.14.7 / Swift 6.4.2. Other versions and Intel Macs are not yet verified. Nothing downloads dependencies or installs system software.

From a fresh unpacked source directory:

```sh
python3 tools/build_native.py --demo
python3 -m unittest discover -s tests -v
python3 -m safe_mac_control supported
```

The build creates local `build/native-helper` and `build/SafeMacDemo.app`. It refuses to overwrite a binary. The optional demo is an ordinary native Cocoa app containing a counter and Increment button. It has no file or network operations. Generated binaries and toolchain caches are not part of the source release.

## One real native demonstration

The actual process doing Accessibility work must have the user's permission and an execution environment that allows the required macOS APIs. If the program reports `accessibility_unavailable`, stop: the message alone does not identify whether macOS permissions or an execution sandbox caused it. Use the normal user-controlled permission process; do not bypass a denied approval. The package does not modify permissions or trigger an automatic permission prompt. Existing permissions for another program are not a guarantee for this executable.

Open the demo explicitly:

```sh
open build/SafeMacDemo.app
```

After the window has settled, leave it frontmost and run one explicit action:

```sh
python3 -m safe_mac_control demo --perform --request-id demo-001 --receipts ./demo-receipts
```

This observes the current native tree, selects the exact Increment button and counter, and attempts one AXPress. `VERIFIED` means the native action returned successfully and the next exact counter value was observed. Close the demo window when finished; its counter is disposable. The same request ID cannot be used for another action.

If the window, focus or tree changes, the request is denied. If the action may have happened but its result is unavailable, the result is `UNKNOWN_EFFECT`. Neither outcome triggers another action. Inspect the actual app and retained receipt before deciding what to do; do not cycle through new request IDs to override a denial or uncertainty.

For read-only inspection:

```sh
python3 -m safe_mac_control inspect --bundle org.klara.SafeMacDemo --window 'Safe Mac Demo'
```

Advanced requests use `python3 -m safe_mac_control run request.json --receipts ./demo-receipts`. A request must name `activate`, `raise` or `press`, one unique request ID, and a complete unmodified snapshot from `inspect` obtained within 30 seconds. `press` additionally needs an exact selector and a different expected static-text postcondition. `tools/demo_request.py` shows the exact schema; no wildcard, coordinate click, typing, shell, deletion or permission operation is supported. An app must already be running at the allowed path; this tool never launches it implicitly.

## Scope and result meanings

| Result | Meaning |
|---|---|
| `OBSERVED` | One supported native window was read. No action requested. |
| `DENIED` | The request failed a check before an action was dispatched. |
| `VERIFIED` | One native call and its expected postcondition were observed. |
| `UNKNOWN_EFFECT` | The action may have happened; do not blindly retry. |

The public command keeps an exclusive intent and result per ID in a user-owned `0700` receipt directory, with `0600` files. An incomplete intent fences its ID. Same-ID/different-input requests fail. A repeat of the exact stored request returns its saved result without dispatch. The convenience `demo` command generates a fresh snapshot, so reusing its ID is a conflict, not a replay interface. Receipts are local user data, not authorization from another person or proof of an OS sandbox.

Read [SECURITY.md](SECURITY.md), [LIMITATIONS.md](LIMITATIONS.md), [PROVENANCE.md](PROVENANCE.md) and [TEST_RESULTS.md](TEST_RESULTS.md) before use. This standalone package is provided under the [MIT License](LICENSE). The original private Gen3 platform and unrelated Command Center materials are excluded.
