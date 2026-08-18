# Android application

## Current release

```text
Version: 0.4.0-alpha01 (build 13)
Package: com.floodman.operations
Minimum Android: API 28 / Android 9
Compile and target SDK: 36
JDK: 17
Gradle: 8.13
Android Gradle Plugin: 8.13.2
Kotlin: 2.3.20
```

## Architecture

The app is a native Jetpack Compose staff application. RoomFlow runs from checksum-verified local web assets inside a secure Android app-assets origin and communicates with Kotlin through a versioned bridge. RoomFlow Capture opens a native ARCore session only after the user starts a scan. Supported devices use ARCore Depth hit tests; other ARCore devices use guided plane/point hit tests. Both return normalized room geometry to the existing authenticated RoomFlow review screen. Manual entry remains available.

Reviewed operations are written to a bounded, atomic private outbox and replayed through the existing Mobile API with stable operation IDs and room revisions. Raw camera images, video, depth maps, and point clouds are never placed in the bridge, outbox, or API.

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
python scripts/verify_roomflow_release_assets.py
cd apps/android
bash scripts/prepare-roomflow-assets.sh
gradle --no-daemon :app:compileDebugKotlin
gradle --no-daemon :app:testDebugUnitTest :app:lintDebug
gradle --no-daemon :app:assembleDebug :app:assembleRelease :app:bundleRelease
```

The authoritative workflow is `.github/workflows/build-android.yml`. Local 0.4.0-alpha01 evidence is recorded in `apps/android/docs/ANDROID_BUILD_EVIDENCE-v0.4.0-alpha01.md`.

## Required acceptance test

1. Sign in with Tailscale disabled on the phone.
2. Confirm server capability negotiation succeeds.
3. Search and open customers and properties.
4. Create, edit, send, authorize, accept, pay, and convert an estimate.
5. Create, edit, send, pay, void, and open an invoice PDF.
6. Open RoomFlow from an existing Floodman job and scan one rectangle plus one L-shaped room.
7. Verify ARCore Depth is used on a supported phone and guided ARCore remains usable on a non-Depth phone.
8. Exercise permission denial, weak tracking, pause/resume, undo/reset, closure guidance, discard confirmation, and manual fallback.
9. Correct walls/openings/affected areas in review; save offline, reconnect, and confirm exactly one server revision.
10. Confirm grouped estimate headers and line items update without duplication.
11. Confirm the actual reviewed RoomFlow layout appears in the estimate PDF.
12. Test calendar assignment, tasks, documents, time clock, notifications, dark mode, and device revocation.

## Known status

The 2026-08-18 0.4.0-alpha01 capture gate passes JDK 17/Gradle 8.13 debug and release compilation, 8/8 unit tests, lint with 0 error/fatal findings, debug APK, unsigned release APK, and release AAB. The APK contains capture schema v2, the exact RoomFlow pin, Floodman 4.7.0 metadata, and the checksum of the offline RoomFlow export. Evidence and current hashes are in `apps/android/docs/ANDROID_BUILD_EVIDENCE-v0.4.0-alpha01.md`.

No physical ARCore/Depth device, release signature, Play upload, or GitHub workflow run is claimed. This build has a distinct 0.4.0-alpha01/build-13 identity and must complete those external gates before production distribution.
