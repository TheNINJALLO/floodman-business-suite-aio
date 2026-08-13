# Apple build

The simulator workflow requires only a new GitHub repository and the source ZIP. A physical-device/TestFlight build requires Apple Developer Program membership, an App Store Connect app record for `com.floodman.operations`, Team ID, App Store Connect API key ID, issuer ID, and the `.p8` private key.

The active repository workflow is `.github/workflows/build-ios-simulator.yml`. It validates the source and the exact RoomFlow pin, selects Xcode 26, generates the project, compiles for generic iOS Simulator with signing disabled, and uploads a zipped application plus build, RoomFlow-asset, and artifact checksums. Run `python scripts/verify_ios_readiness.py` before moving the source to macOS.

The guarded TestFlight workflow compiles the unsigned simulator target again for the same commit before installing signing material. Selecting `UPLOAD` is an explicit release action; do not run it until the simulator gate is green and the Apple secrets are configured.


## Alpha 02 compiler corrections

- Corrected `LocalAssetServer` optional binding reported by Xcode 26.
- Restricted the bundled RoomFlow HTTP listener to loopback and added path traversal checks.
- Read `UIDevice.current.name` through `MainActor` so the source remains ready for Swift 6 language mode.
- Replaced deprecated localized interpolation of dictionary `Any` values with explicit display strings.
- Enforced HTTPS Mobile API configuration, minimum iOS version, capability compatibility, device-bound tokens, coordinated rotating refresh, and PDF MIME/signature validation.
- Made RoomFlow covers and sheets dismissible, restricted WebView navigation/media permission to loopback, and hardened the local HTTP reader for fragmented requests.
