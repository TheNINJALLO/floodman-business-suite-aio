# iPhone and iPad application

## Current release

```text
Version: 0.1.0-alpha02
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

## Simulator build

Use the unsigned simulator workflow first:

```text
deployment/github-actions/build-ios-simulator-alpha02.yml
```

It requires the `FLOODMAN_API_BASE_URL` repository variable but no Apple signing secrets.

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

The last TestFlight attempt in the session failed before compilation because Apple signing secrets were missing. The alpha02 source includes the Swift fixes from the first compiler pass, but a new simulator build is still required. Native estimate, invoice, payment, scheduling, and employee-assignment depth must be verified against Android before calling the Apple app feature-complete.
