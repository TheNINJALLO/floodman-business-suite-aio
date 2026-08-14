# Android application

## Current release

```text
Version: 0.3.0-alpha12
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

The authoritative workflow is `.github/workflows/build-android.yml`. Local alpha12 evidence is recorded in `apps/android/docs/ANDROID_BUILD_EVIDENCE-v0.3.0-alpha12.md`.

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

The 2026-08-14 local alpha12 JDK 17/Gradle 8.13 gate passes compile, 1/1 unit test, lint with 0 errors, debug APK, unsigned release APK, and unsigned release AAB. Artifact identity, embedded RoomFlow pin, signature state, and SHA-256 values were inspected. No GitHub run was dispatched because this checkout has no remote (BLK-010), and no physical-device/signing/store pass is claimed.
