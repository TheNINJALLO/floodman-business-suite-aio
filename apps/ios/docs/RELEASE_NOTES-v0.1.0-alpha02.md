# Floodman Operations iOS 0.1.0-alpha02

## Compiler corrections

- Fixed the Xcode 26 `Data? cannot be used as a boolean` error in `LocalAssetServer.swift`.
- Fixed the main-actor warning for `UIDevice.current.name`.
- Removed deprecated SwiftUI interpolation warnings from calendar and RoomFlow rows.

## Local RoomFlow server hardening

- Binds only to `127.0.0.1`.
- Rejects paths that escape the bundled `RoomFlow` resource directory.
- Sends explicit MIME, content length, no-store, and nosniff headers.
- Keeps the complete pinned RoomFlow workspace local to the app.
