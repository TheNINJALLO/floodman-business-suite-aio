# Android RoomFlow Capture build evidence — unreleased

Evidence date: 2026-08-18

This evidence applies to the RoomFlow Capture source candidate, not to a newly versioned or signed release. The identity remains `0.3.0-alpha12`/version code 12 solely because the Apple/device/staging release gates have not authorized the next identity. Do not distribute these artifacts over an older alpha12 binary.

## Implemented capture path

- real ARCore `Session` and camera texture lifecycle;
- center-screen hit tests using Depth points when supported and plane/feature points otherwise;
- stabilized samples, confidence, segment/closure guidance, editable ceiling height, undo/reset, haptic feedback, optional beep, and discard confirmation;
- foreground/background and camera-permission handling with manual fallback;
- bridge-v2 request validation and bounded replies;
- atomic private outbox with stable operation IDs, revisions, ordered replay, and a 200-operation/256-KB bound;
- no raw camera, video, depth, or point-cloud retention.

## Local gate

Toolchain: Windows 11 x64, Temurin JDK `17.0.20+8`, Gradle `8.13`, Android Gradle Plugin `8.13.2`, Kotlin `2.3.20`, compile/target SDK 36, build tools 36.1.0.

| Gate | Result |
|---|---|
| `--rerun-tasks :app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug` | PASS; 36 tasks executed in 4m 5s |
| Unit XML | PASS; 8 tests, 0 failures/errors/skips |
| Lint XML | PASS; 27 advisory issues, 0 error/fatal findings; no check disabled |
| `:app:assembleDebug :app:assembleRelease :app:bundleRelease` | PASS; 99 tasks, 22 executed/77 up to date, in 3m 40s |
| Package inspection | PASS; debug ID `com.floodman.operations.debug`, version code 12, `0.3.0-alpha12-debug`, min 28, target 36 |
| Debug signature | PASS; local Android debug certificate, APK Signature Scheme v2 |
| Release signature | Expected unsigned; release APK reports missing signature and AAB reports unsigned |
| Embedded runtime | PASS; capture schema/code, Floodman 4.6.10, attribution, exact pin, and offline-manifest hash `d5a7fbc4aae6a072318a279f22c78319ccdc21f8d246cc72b637efe641ee1d09` |

## Artifact checksums

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `app/build/outputs/apk/debug/app-debug.apk` | 73,432,329 | `0f3aa38ad232673a7c39ccd5d5ed3b8d0a55695c3eaecd94dd5a3035ef48719f` |
| `app/build/outputs/apk/release/app-release-unsigned.apk` | 6,615,467 | `4890870db8d33512d3afe40c8a9152fc11637be1984cc021c60e28bf7e2b33a7` |
| `app/build/outputs/bundle/release/app-release.aab` | 6,971,264 | `8b3f6720ebcffbc82014ec59fe21cb19c8efb322f7ba958e636bf21a63f3ca18` |

Physical ARCore/Depth acceptance, clean install/upgrade, release signing, Play upload, and public-staging HTTPS remain BLK-006/BLK-007 and are not claimed.
