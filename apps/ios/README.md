# Floodman Operations for iPhone and iPad

Release candidate: `0.1.0-alpha03` (marketing version `0.1.0`, build `3`).

Native SwiftUI shell using the encrypted Floodman Mobile API. The complete pinned RoomFlow field-estimating engine is bundled locally and synchronized through the same customer, property, job, layout, and estimate records as Android and the private PWA.

The source gate enforces an HTTPS `/mobile-api/` endpoint, checks the server's minimum iOS version and required capability list before restoring or creating a session, stores tokens in the device-bound Keychain, coordinates rotating refresh requests, and rejects PDF responses unless both the MIME type and `%PDF-` signature are valid.

RoomFlow is served only on loopback. The local HTTP reader handles fragmented requests and rejects oversized headers and path traversal; WebView navigation and camera/microphone grants are limited to that loopback origin. The full-screen workspace always has a native close control, and cloud-import/workspace-create sheets remain cancellable while requests are active.

Run `.github/workflows/build-ios-simulator.yml` for the unsigned iPhone/iPad simulator compiler gate. It prepares and validates the exact RoomFlow pin, generates the Xcode project, builds without signing, packages the `.app`, and records SHA-256 checksums. TestFlight is separately guarded and repeats the simulator compile for the same commit before signing. Local source evidence is in `docs/IOS_BUILD_READINESS-v0.1.0-alpha03.md`; no macOS/Xcode pass is claimed from Windows.
