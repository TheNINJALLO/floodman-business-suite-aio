# Android 0.4.0-alpha01 RoomFlow Capture build evidence

Evidence date: 2026-08-18

This evidence applies to the distinct Android `0.4.0-alpha01`/version code 13 local release authorized with the Floodman web/server 4.7.0 package. It is locally built but not production signed or device/store accepted.

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
| `--rerun-tasks :app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug` | PASS; 36 tasks executed in 3m 36s |
| Unit XML | PASS; 8 tests, 0 failures/errors/skips |
| Lint XML | PASS; 27 advisory issues, 0 error/fatal findings; no check disabled |
| `:app:assembleDebug :app:assembleRelease :app:bundleRelease` | PASS; 99 tasks, 34 executed/65 up to date, in 3m 22s |
| Package inspection | PASS; debug ID `com.floodman.operations.debug`, version code 13, `0.4.0-alpha01-debug`, min 28, target 36 |
| Debug signature | PASS; local Android debug certificate, APK Signature Scheme v2 |
| Release signature | Expected unsigned; release APK reports missing signature and AAB reports unsigned |
| Embedded runtime | PASS; capture schema/code, Floodman 4.7.0, attribution, exact pin, and offline-manifest hash `d5a7fbc4aae6a072318a279f22c78319ccdc21f8d246cc72b637efe641ee1d09` |

## Artifact checksums

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `app/build/outputs/apk/debug/app-debug.apk` | 71,157,967 | `0e3876bc8d88987b47ae05bd1843c3806e0cf20592ea1d67baf18e2498fc9148` |
| `app/build/outputs/apk/release/app-release-unsigned.apk` | 6,615,467 | `641f7cfda1f67b63c475d268690a19a195b7e1c8f279c9cb8cf441f7ce525a94` |
| `app/build/outputs/bundle/release/app-release.aab` | 6,971,269 | `113d544fbd6ad7c9574bcce67ff2e3ceb399a6b567ac6070f64480ca80d4bbb7` |

Physical ARCore/Depth acceptance, clean install/upgrade, release signing, Play upload, and public-staging HTTPS remain BLK-006/BLK-007 and are not claimed.
