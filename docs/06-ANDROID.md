# Android application

## Current release

```text
Version: 0.3.0-alpha11
Package: com.floodman.operations
Minimum Android: API 28 / Android 9
Compile and target SDK: 36
JDK: 17
Gradle: 8.13
Android Gradle Plugin: 8.13.2
Kotlin: 2.3.20
```

## Architecture

The app is a native Jetpack Compose staff application. RoomFlow runs from local packaged web assets inside a secure Android app-assets origin and communicates with Kotlin through a narrow bridge. The app does not need the Tailscale Android client because it uses the public HTTPS Mobile API.

## Security

- HTTPS only; cleartext disabled
- device enrollment
- short-lived access tokens
- rotating refresh tokens
- encrypted local session storage backed by Android Keystore
- biometric or device-PIN unlock
- device revocation
- capability/version check during login
- PDF content-type and `%PDF-` signature validation

## Build

Copy `local.properties.example` to `local.properties` and configure the Mobile API URL and Square Sandbox application ID.

```bash
cd apps/android
gradle --no-daemon :app:compileDebugKotlin
gradle --no-daemon :app:testDebugUnitTest :app:lintDebug
gradle --no-daemon :app:assembleDebug :app:assembleRelease :app:bundleRelease
```

The authoritative workflow is `deployment/github-actions/build-android-alpha11.yml`.

## Required acceptance test

1. Sign in with Tailscale disabled on the phone.
2. Confirm server capability negotiation succeeds.
3. Search and open customers and properties.
4. Create, edit, send, authorize, accept, pay, and convert an estimate.
5. Create, edit, send, pay, void, and open an invoice PDF.
6. Open RoomFlow, select a workspace, open an imported job, edit the layout, and Save & Sync.
7. Confirm grouped estimate headers and line items update without duplication.
8. Confirm the actual RoomFlow layout appears in the estimate PDF.
9. Test calendar assignment, tasks, documents, time clock, notifications, and dark mode.
10. Revoke the device and confirm refresh fails.

## Known status

No final green alpha11 GitHub Actions log is included in this conversation handoff. Treat the current source as a release candidate until the complete workflow passes and a physical-device test is recorded.
