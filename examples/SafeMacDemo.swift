// Native Cocoa fixture: no files, network, credentials, or production app state.
import AppKit

class Demo: NSObject, NSApplicationDelegate {
    var window: NSWindow!
    var count = 0
    let label = NSTextField(labelWithString: "0")
    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 200, y: 200, width: 320, height: 160),
                          styleMask: [.titled, .closable], backing: .buffered, defer: false)
        window.title = "Safe Mac Demo"
        let button = NSButton(title: "Increment", target: self, action: #selector(increment))
        button.frame = NSRect(x: 80, y: 35, width: 160, height: 40)
        button.setAccessibilityIdentifier("safe-demo-increment")
        label.frame = NSRect(x: 140, y: 100, width: 80, height: 25)
        label.setAccessibilityIdentifier("safe-demo-count")
        window.contentView!.addSubview(button)
        window.contentView!.addSubview(label)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate()
    }
    @objc func increment() { count += 1; label.stringValue = String(count) }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}
let app = NSApplication.shared
let delegate = Demo()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
