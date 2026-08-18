# iPhone and iPad application

## Current release

```text
Version: 0.1.0-alpha03
Bundle ID: com.floodman.operations
UI: SwiftUI
Project generation: XcodeGen
Build target: iPhone and iPad
```

## Included foundation

- Floodman login and Mobile API client
- Keychain session storage
- rotating refresh-token proof
- Face ID, Touch ID, or device passcode flow
- dashboard and core module shells
- dark/light/system appearance
- bundled RoomFlow engine and local asset server
- customer/property/job/layout synchronization scaffolding
- RoomPlan/LiDAR room capture on supported devices
- guided ARKit raycast capture fallback, including LiDAR scene reconstruction when available
- versioned capture bridge and bounded private offline-operation outbox
- HTTPS, minimum-version and required-capability validation before session use
- PDF MIME and `%PDF-` signature rejection
- loopback-only, dismissible RoomFlow with cancellable import/workspace sheets

## Simulator build

Use the unsigned simulator workflow first:

```text
.github/workflows/build-ios-simulator.yml
```

It uses the HTTPS default when `FLOODMAN_API_BASE_URL` is absent and validates any repository override. It requires no Apple signing secrets.

The workflow verifies the offline RoomFlow export, prepares the exact-pin local assets without a GitHub checkout, compiles the app, boots an available iPhone simulator, runs the capture unit target, and publishes build/test logs plus checksums.

## TestFlight

Run the guarded TestFlight workflow only after the simulator build is green. It requires:

```text
APPLE_TEAM_ID
IOS_DISTRIBUTION_CERTIFICATE_BASE64
IOS_DISTRIBUTION_CERTIFICATE_PASSWORD
IOS_PROVISIONING_PROFILE_BASE64
APP_STORE_CONNECT_KEY_ID
APP_STORE_CONNECT_ISSUER_ID
APP_STORE_CONNECT_PRIVATE_KEY_BASE64
```

Never commit those values. Store them only as GitHub Actions secrets or in a dedicated secret manager.

## Known status

The 2026-08-18 unreleased capture-source readiness gate passes 11 Swift source files, project/plist/workflow contracts, six deterministic capture test methods, exact-pin asset preparation, RoomPlan conversion, ARKit fallback, private outbox, lifecycle/privacy checks, and the versioned bridge. Details are in `apps/ios/docs/IOS_ROOMFLOW_CAPTURE_READINESS-UNRELEASED.md`.

Windows cannot run Xcode, so simulator compilation and those six tests remain `BLK-004`; no Swift compiler pass is inferred. LiDAR RoomPlan, ARKit fallback, relocalization, iPhone/iPad layout, signing, and physical-device behavior remain external gates. The app version stays alpha03, and this source must not be distributed over an older alpha03 binary without assigning the next approved identity.
