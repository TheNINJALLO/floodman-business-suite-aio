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
- HTTPS, minimum-version and required-capability validation before session use
- PDF MIME and `%PDF-` signature rejection
- loopback-only, dismissible RoomFlow with cancellable import/workspace sheets

## Simulator build

Use the unsigned simulator workflow first:

```text
.github/workflows/build-ios-simulator.yml
```

It uses the HTTPS default when `FLOODMAN_API_BASE_URL` is absent and validates any repository override. It requires no Apple signing secrets.

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

The 2026-08-15 alpha03 Windows source/readiness gate passes, including build 3 identity, guided RoomFlow workflow, progressive company/import controls, fixed Detroit business time, transient import-password handling, workspace-aware lookup, and the exact prepared pin. Windows cannot run Xcode, so a simulator build is still required and remains `BLK-004`; no compiler pass is inferred. Native estimate, invoice, payment, scheduling, and employee-assignment depth must be verified against Android before calling the Apple app feature-complete.
