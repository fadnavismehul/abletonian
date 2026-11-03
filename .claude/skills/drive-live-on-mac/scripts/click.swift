// Posts a real left click at screen point (x, y). Live draws its own UI, so
// System Events "click at" does not reach most of it; a CGEvent does.
import CoreGraphics
import Foundation

let args = CommandLine.arguments
guard args.count == 3, let x = Double(args[1]), let y = Double(args[2]) else {
    print("usage: click X Y   (screen points)")
    exit(2)
}
let point = CGPoint(x: x, y: y)
for type in [CGEventType.leftMouseDown, .leftMouseUp] {
    CGEvent(mouseEventSource: nil, mouseType: type, mouseCursorPosition: point,
            mouseButton: .left)?.post(tap: .cghidEventTap)
    usleep(80_000)
}
