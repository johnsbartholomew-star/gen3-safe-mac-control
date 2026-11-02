# Source and dependency provenance

This document describes the standalone source package and its dependencies. The [MIT License](LICENSE) applies only to these released files.

The native helper is derived from the existing Gen3 `window_action_helper.swift`, `desktop_action_helper.swift` and bounded Accessibility inspection helper. Reused concepts and API sequences include exact app/window selection, AX attribute/action reads, secure-field refusal, AXRaise/AXPress and postcondition observation. The standalone helper replaces the broad original app list, removes coordinate clicks and private routes, and adds explicit observation errors, complete-traversal rejection, exact fingerprints and a closed benign action set.

The Python CLI/one-attempt receipt layer and disposable Cocoa fixture are newly written integration and demonstration code for this extraction. No original private Python policy, receipt database, dispatcher, configuration, credentials, connectors, Motion routines or compiled helper is bundled. No private Git history is included. A private source manifest records the precise original file hashes and derivation for Legal; it is not part of the publishable export.

Dependencies:

| Dependency | Use | Bundled? |
|---|---|---|
| Python standard library | CLI, validation, subprocess and local receipts | No Python interpreter bundled |
| Apple Swift compiler | Local native compilation | No toolchain bundled |
| Foundation, AppKit, ApplicationServices, CoreGraphics, CryptoKit | Native macOS APIs | Referenced system frameworks; no SDK/framework redistribution |

There are no downloaded Python/Swift packages or vendored third-party source in this package. Referenced system tools and frameworks remain governed by their own terms.

John directed and coordinated the work. The standalone integration and demonstration were produced with Codex assistance using the existing Gen3 controls. The copyright notice identifies John (johnsbartholomew-star); it does not claim that he personally wrote the code or performed the tests. The original private Gen3 implementation and unrelated Command Center materials are not licensed or distributed by this release.
