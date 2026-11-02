// Derived from the original Gen3 window/action/inspection Swift helpers.
// Private release candidate. Exact provenance is recorded separately.
import Foundation
import AppKit
import ApplicationServices
import CoreGraphics
import CryptoKit

struct Refusal: Error { let reason: String }
func require(_ ok: Bool, _ reason: String) throws {
    if !ok { throw Refusal(reason: reason) }
}
func encoded(_ object: Any) throws -> Data {
    try JSONSerialization.data(withJSONObject: object, options: [.sortedKeys, .withoutEscapingSlashes])
}
func digest(_ object: Any) throws -> String {
    SHA256.hash(data: try encoded(object)).map { String(format: "%02x", $0) }.joined()
}
func emit(_ object: [String: Any]) -> Never {
    do { FileHandle.standardOutput.write(try encoded(object)); print("") }
    catch { print("{\"status\":\"UNKNOWN_EFFECT\",\"reason\":\"encoding_failed\"}") }
    exit(object["status"] as? String == "DENIED" || object["status"] as? String == "UNKNOWN_EFFECT" ? 2 : 0)
}

let deadline = ProcessInfo.processInfo.systemUptime + 8
func budget() throws { try require(ProcessInfo.processInfo.systemUptime < deadline, "observation_budget_exceeded") }

// Preserve unknown/error separately from a legitimate optional missing attribute.
func attr(_ element: AXUIElement, _ name: String, optional: Bool = false) throws -> CFTypeRef? {
    try budget()
    var value: CFTypeRef?
    let error = AXUIElementCopyAttributeValue(element, name as CFString, &value)
    if optional && (error == .attributeUnsupported || error == .noValue) { return nil }
    try require(error == .success, "attribute_unavailable:\(name):\(error.rawValue)")
    return value
}
func string(_ e: AXUIElement, _ name: String, optional: Bool = false) throws -> String {
    guard let value = try attr(e, name, optional: optional) else { return "" }
    try require(value is String, "attribute_type:\(name)")
    let text = value as! String
    try require(text.utf8.count <= 2048, "attribute_too_large")
    return text
}
func elements(_ e: AXUIElement, _ name: String) throws -> [AXUIElement] {
    guard let raw = try attr(e, name, optional: true) else { return [] }
    guard let values = raw as? [AXUIElement] else { throw Refusal(reason: "element_list_type") }
    return values
}
func actionNames(_ e: AXUIElement) throws -> [String] {
    try budget()
    var values: CFArray?
    let error = AXUIElementCopyActionNames(e, &values)
    if error == .actionUnsupported { return [] }
    try require(error == .success, "action_list_unavailable")
    return (values as? [String]) ?? []
}
func enabled(_ e: AXUIElement) throws -> Bool {
    guard let raw = try attr(e, kAXEnabledAttribute, optional: true) else { return false }
    guard let value = raw as? NSNumber else { throw Refusal(reason: "enabled_type") }
    return value.boolValue
}
func selectedFields(_ row: [String: Any]) -> [String: String] {
    var fields: [String: String] = [:]
    for key in ["role", "title", "identifier", "description"] { fields[key] = row[key] as? String ?? "" }
    return fields
}
func strictSelector(_ raw: Any?) throws -> [String: String] {
    guard let value = raw as? [String: String] else { throw Refusal(reason: "exact_selector_required") }
    try require(Set(value.keys) == Set(["role", "title", "identifier", "description"]), "selector_fields")
    try require(value.values.allSatisfy { $0 != "*" && $0.utf8.count <= 2048 }, "selector_value")
    try require(!["AXTextField", "AXSecureTextField", "AXTextArea"].contains(value["role"]!), "secure_or_editable_field")
    try require(value["title"] != "" || value["identifier"] != "" || value["description"] != "", "empty_selector")
    return value
}

struct Observation {
    let app: NSRunningApplication
    let root: AXUIElement
    let window: AXUIElement
    let rows: [[String: Any]]
    let refs: [AXUIElement]
    let body: [String: Any]
}

// Calculator is a shipped system app. The demo is a separate, disposable fixture.
let buildDirectory = URL(fileURLWithPath: CommandLine.arguments[0]).standardizedFileURL.deletingLastPathComponent()
let appPaths = [
    "com.apple.calculator": "/System/Applications/Calculator.app",
    "org.klara.SafeMacDemo": buildDirectory.appendingPathComponent("SafeMacDemo.app").path
]

func appFor(_ bundle: String) throws -> NSRunningApplication {
    guard let permittedPath = appPaths[bundle] else { throw Refusal(reason: "bundle_not_allowed") }
    let matches = NSWorkspace.shared.runningApplications.filter { $0.bundleIdentifier == bundle && !$0.isTerminated }
    try require(matches.count == 1, "running_app_not_unique")
    let app = matches[0]
    try require(app.bundleURL?.standardizedFileURL.path == permittedPath, "app_path_mismatch")
    try require(NSWorkspace.shared.frontmostApplication != nil, "foreground_unavailable")
    try require(NSWorkspace.shared.frontmostApplication?.bundleIdentifier != "com.apple.loginwindow", "session_locked")
    return app
}

func observe(_ bundle: String, _ title: String) throws -> Observation {
    try require(appPaths[bundle] != nil, "bundle_not_allowed")
    try require(AXIsProcessTrusted(), "accessibility_unavailable")
    try require(AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(), 0.4) == .success, "ax_timeout_unavailable")
    let app = try appFor(bundle)
    let root = AXUIElementCreateApplication(app.processIdentifier)
    let allWindows = try elements(root, kAXWindowsAttribute)
    var matching: [AXUIElement] = []
    for w in allWindows {
        if try string(w, kAXTitleAttribute) == title { matching.append(w) }
    }
    try require(matching.count == 1, "window_not_unique")
    let window = matching[0]
    var rows: [[String: Any]] = [], refs: [AXUIElement] = []
    func walk(_ e: AXUIElement, _ depth: Int) throws {
        try budget()
        try require(depth <= 32 && rows.count < 2048, "incomplete_tree_limit")
        try require(!refs.contains(where: { CFEqual($0, e) }), "incomplete_tree_cycle")
        let role = try string(e, kAXRoleAttribute)
        let subrole = try string(e, kAXSubroleAttribute, optional: true)
        let sensitive = ["AXTextField", "AXTextArea", "AXSecureTextField"].contains(role) || subrole == "AXSecureTextField"
        // Never read value/title/description or descendants of an editable/secure field.
        var row: [String: Any] = ["role": role, "subrole": subrole, "redacted": sensitive]
        if !sensitive {
            row["title"] = try string(e, kAXTitleAttribute, optional: true)
            row["identifier"] = try string(e, kAXIdentifierAttribute, optional: true)
            row["description"] = try string(e, kAXDescriptionAttribute, optional: true)
            row["enabled"] = try enabled(e)
            row["actions"] = try actionNames(e).sorted()
            if role == "AXStaticText" { row["value"] = try string(e, kAXValueAttribute, optional: true) }
        }
        rows.append(row); refs.append(e)
        if !sensitive { for child in try elements(e, kAXChildrenAttribute) { try walk(child, depth + 1) } }
    }
    try walk(window, 0)
    let front = NSWorkspace.shared.frontmostApplication?.processIdentifier == app.processIdentifier
    let content: [String: Any] = ["bundle": bundle, "window": title, "pid": Int(app.processIdentifier), "elements": rows, "frontmost": front]
    var body = content
    body["fingerprint"] = try digest(content)
    body["status"] = "OBSERVED"
    return Observation(app: app, root: root, window: window, rows: rows, refs: refs, body: body)
}

func unique(_ observation: Observation, _ selector: [String: String]) throws -> Int {
    let matches = observation.rows.indices.filter {
        observation.rows[$0]["redacted"] as? Bool == false && selectedFields(observation.rows[$0]) == selector
    }
    try require(matches.count == 1, "semantic_target_not_unique")
    return matches[0]
}

func benignButton(_ bundle: String, _ fields: [String: String]) -> Bool {
    if bundle == "org.klara.SafeMacDemo" { return fields["identifier"] == "safe-demo-increment" && fields["title"] == "Increment" }
    if bundle == "com.apple.calculator" {
        // Deliberately exclude menu items, financial operations, files, and permissions.
        let digits = Set((0...9).map(String.init))
        return digits.contains(fields["title"] ?? "") || digits.contains(fields["description"] ?? "")
    }
    return false
}

var crossedEffectBoundary = false
do {
    let input = FileHandle.standardInput.readData(ofLength: 65537)
    try require(input.count <= 65536, "input_too_large")
    guard let request = try JSONSerialization.jsonObject(with: input) as? [String: Any],
          let operation = request["operation"] as? String else { throw Refusal(reason: "invalid_request") }
    try require(["inspect", "activate", "raise", "press"].contains(operation), "operation_not_allowed")
    if operation == "inspect" {
        try require(Set(request.keys) == Set(["operation", "bundle", "window"]), "inspect_fields")
        guard let bundle = request["bundle"] as? String, let window = request["window"] as? String,
              !window.isEmpty else { throw Refusal(reason: "exact_window_required") }
        emit(try observe(bundle, window).body)
    }
    let fields = operation == "press" ? Set(["request_id", "operation", "snapshot", "target", "postcondition"]) : Set(["request_id", "operation", "snapshot"])
    try require(Set(request.keys) == fields, "request_fields")
    guard let prior = request["snapshot"] as? [String: Any], let bundle = prior["bundle"] as? String,
          let window = prior["window"] as? String, let fingerprint = prior["fingerprint"] as? String,
          let timestamp = prior["observed_at"] as? Double else { throw Refusal(reason: "snapshot_required") }
    let age = Date().timeIntervalSince1970 - timestamp
    try require(age >= 0 && age <= 30, "snapshot_stale_or_future")
    let before = try observe(bundle, window)
    try require(before.body["fingerprint"] as? String == fingerprint, "snapshot_changed")
    try require(before.body["pid"] as? Int == prior["pid"] as? Int, "process_changed")
    if operation != "activate" { try require(before.body["frontmost"] as? Bool == true, "target_not_frontmost") }
    var postSelector: [String: String]? = nil, wantedValue: String? = nil
    var target: AXUIElement? = nil
    if operation == "press" {
        let selection = try strictSelector(request["target"])
        try require(selection["role"] == "AXButton" && benignButton(bundle, selection), "button_not_allowlisted")
        let index = try unique(before, selection)
        try require(before.rows[index]["enabled"] as? Bool == true, "button_disabled")
        try require((before.rows[index]["actions"] as? [String] ?? []).contains(kAXPressAction), "AXPress_unavailable")
        guard let post = request["postcondition"] as? [String: Any], Set(post.keys) == Set(["selector", "value"]),
              let value = post["value"] as? String, value.count <= 512 else { throw Refusal(reason: "postcondition_required") }
        let selector = try strictSelector(post["selector"])
        try require(selector["role"] == "AXStaticText", "static_postcondition_required")
        let postIndex = try unique(before, selector)
        try require(before.rows[postIndex]["value"] as? String != value, "postcondition_already_true")
        postSelector = selector; wantedValue = value; target = before.refs[index]
    }
    // Recheck both complete state and object identities immediately before the one action.
    let last = try observe(bundle, window)
    try require(last.body["fingerprint"] as? String == fingerprint && CFEqual(before.window, last.window), "state_changed_before_dispatch")
    if operation == "press" {
        let index = try unique(last, strictSelector(request["target"]))
        try require(CFEqual(target!, last.refs[index]), "element_replaced")
    }
    try budget()
    crossedEffectBoundary = true
    var accepted = false
    if operation == "activate" { accepted = before.app.activate(options: []) }
    if operation == "raise" { accepted = AXUIElementPerformAction(before.window, kAXRaiseAction as CFString) == .success }
    if operation == "press" { accepted = AXUIElementPerformAction(target!, kAXPressAction as CFString) == .success }
    // Observation only; no retries of the action.
    RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.2))
    let after = try observe(bundle, window)
    try require(accepted, "native_action_unconfirmed")
    try require(after.app.processIdentifier == before.app.processIdentifier && after.body["frontmost"] as? Bool == true, "post_process_or_focus_changed")
    if operation == "raise" {
        guard let focused = try attr(after.root, kAXFocusedWindowAttribute), CFGetTypeID(focused) == AXUIElementGetTypeID() else {
            throw Refusal(reason: "focused_window_unavailable")
        }
        try require(CFEqual(focused, before.window), "window_raise_unverified")
    }
    if let selector = postSelector {
        let index = try unique(after, selector)
        try require(after.rows[index]["value"] as? String == wantedValue, "postcondition_not_observed")
    }
    emit(["status": "VERIFIED", "operation": operation, "native_action_called": true,
          "before_fingerprint": fingerprint, "after_fingerprint": after.body["fingerprint"]!,
          "postcondition_observed": true])
} catch let error as Refusal {
    emit(["status": crossedEffectBoundary ? "UNKNOWN_EFFECT" : "DENIED", "reason": error.reason,
          "native_action_called_or_possible": crossedEffectBoundary, "retry": false])
} catch {
    emit(["status": crossedEffectBoundary ? "UNKNOWN_EFFECT" : "DENIED", "reason": "native_error",
          "error_class": String(describing: type(of: error)), "retry": false])
}
