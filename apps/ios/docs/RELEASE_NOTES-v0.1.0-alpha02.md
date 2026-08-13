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
- Reads fragmented HTTP requests safely and rejects oversized request headers.
- Restricts WebView navigation and media grants to the loopback RoomFlow origin.
- Keeps a native close control visible and lets users cancel cloud-import and workspace-create sheets while a request is active.

## Mobile API compatibility

- Requires an HTTPS address ending in `/mobile-api/`.
- Checks the server's `minimum_ios_version` and required capabilities before login or session restore.
- Stores session material in the device-bound Keychain and coordinates rotating refresh requests.
- Rejects estimate or invoice downloads unless the response is `application/pdf` and starts with `%PDF-`.
