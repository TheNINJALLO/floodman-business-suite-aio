# iOS 0.1.0-alpha02 build readiness

Evidence date: 2026-08-13

## Local source gate

`python scripts/verify_ios_readiness.py` passes with:

- 7 Swift source files discovered through the XcodeGen source root;
- 18 valid iPhone, iPad, and App Store icon slots with matching PNG dimensions;
- iOS 17 deployment, Swift 5 language mode, bundle `com.floodman.operations`, marketing version `0.1.0`, build `2`;
- parseable plist and workflow YAML;
- HTTPS `/mobile-api/` validation, `minimum_ios_version` enforcement, and required capability checks;
- device-bound Keychain session storage, coordinated rotating refresh, and PDF MIME/signature rejection;
- loopback-only RoomFlow serving, request framing and traversal defenses, loopback-only WebView navigation/media permission, and user-controlled close/cancel paths;
- simulator checksum packaging and a guarded TestFlight workflow that repeats the unsigned simulator compile before signing.

The prepared iOS RoomFlow bundle validates in native mode and carries package-visible metadata for Floodman `4.6.7`, attribution `Created by Josh Aldrich`, time zone `America/Detroit`, and exact commit `1f97817a52b916875e50cc6380c0d284072b8ce8`. The complete local core, compatibility overlay, bridge, `cost-tests.js`, catalog, and pinned browser libraries are present; upstream Supabase/Townsquare browser sessions are not embedded.

The additive Mobile API `minimum_ios_version` response is covered by health, config, and RoomFlow bootstrap smoke assertions. All 9 server smoke programs passed after the change.

## macOS compiler gate

The final simulator command is intentionally not marked as run on Windows:

```bash
xcodegen generate
xcodebuild \
  -project FloodmanOperations.xcodeproj \
  -scheme FloodmanOperations \
  -configuration Debug \
  -destination 'generic/platform=iOS Simulator' \
  -derivedDataPath DerivedData \
  CODE_SIGNING_ALLOWED=NO \
  CODE_SIGNING_REQUIRED=NO \
  build
```

Run `.github/workflows/build-ios-simulator.yml` on the macOS 26/Xcode 26 runner. The workflow packages the simulator `.app`, the RoomFlow asset manifest, compiler logs/settings, and `SHA256SUMS.txt`.

## Remaining gates

- Actual Xcode simulator compilation: `BLK-004`.
- Physical iPhone/iPad acceptance and public staging HTTPS: `BLK-006`.
- Apple signing, archive, TestFlight upload, and production release: `BLK-007` and explicit approval.

This is build-readiness evidence, not a claim that the current Apple feature depth equals Android. Estimate, invoice, payment, scheduling, and employee-assignment acceptance remain part of the device/staging gates.
