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

## v4.7.1 server-compatibility rerun — 2026-08-21

The Android source and `0.4.0-alpha01`/build 13 identity did not change for the server-only v4.7.1 release. A current-tree JDK 17/Gradle 8.13 gate was nevertheless attempted. The initial combined `--rerun-tasks` invocation exceeded its 15-minute command ceiling after producing the fresh debug APK; its Gradle/Kotlin child processes were identified and stopped, and that invocation is not counted as a pass. A continuation of the remaining tasks completed normally in 5m 50s with 95 actionable tasks (13 executed, 82 up to date).

- unit XML: 8 tests, 0 failures, 0 errors, 0 skipped;
- debug lint XML: 27 advisory issues, 0 error/fatal findings;
- debug APK: `0e3876bc8d88987b47ae05bd1843c3806e0cf20592ea1d67baf18e2498fc9148` (71,157,967 bytes);
- unsigned release APK: `d7b0e38635715c2f73b9514e20bb77e7cb4126463c3ff8e129cd764cda462e2d` (6,615,467 bytes);
- unsigned release AAB: `f34a216b3767cebfa97040f21c0993f2f2c36aa6f8667f497ffa1ba6fe17ca40` (6,970,587 bytes).

This rerun confirms compatibility with the unchanged additive Mobile API contract. It does not relabel the embedded v4.7.0 RoomFlow asset metadata, sign the release outputs, or claim device/store acceptance.

Physical ARCore/Depth acceptance, clean install/upgrade, release signing, Play upload, and public-staging HTTPS remain BLK-006/BLK-007 and are not claimed.

## WEB-007 safe-area rerun — 2026-08-28

The unchanged `0.4.0-alpha01`/build 13 source now applies safe-drawing padding to Compose login/lock screens and consumes system-bar plus display-cutout insets in the local RoomFlow WebView and AR capture shell. No API, capture schema, RoomFlow pin, endpoint, credential, or version changed.

Official Temurin and Gradle archives were downloaded into a temporary host toolchain and verified before use:

```text
e53a79c3c3d86865bd7e787903884331068e71321714ffd44f145785affc7cb0  OpenJDK17U-jdk_x64_windows_hotspot_17.0.20.1_1.zip
20f1b1176237254a6fc204d8434196fa11a4cfb387567519c61556e8710aed78  gradle-8.13-bin.zip
```

| Gate | Result |
|---|---|
| Temurin 17.0.20.1+1 / Gradle 8.13 / SDK 36.1.0 | PASS |
| `--rerun-tasks :app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug` | PASS; 36 tasks in 9m33s |
| Unit XML | PASS; 8 tests, 0 failures/errors/skips |
| Debug lint XML | PASS; 27 advisories, 0 error/fatal findings |
| `:app:assembleDebug :app:assembleRelease :app:bundleRelease` | PASS; 99 tasks in 5m42s |
| Package metadata | PASS; `com.floodman.operations.debug`, build 13, `0.4.0-alpha01-debug`, min 28, target 36 |
| Signing state | PASS; debug APK verifies with APK Signature Scheme v2; release APK and AAB are intentionally unsigned |

Fresh artifact checksums:

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `app/build/outputs/apk/debug/app-debug.apk` | 72,447,417 | `072edc318914435682cfdb9ca49fa2b9ec9b747a43c44c280bf335455810c6fc` |
| `app/build/outputs/apk/release/app-release-unsigned.apk` | 6,631,851 | `f9b1f3aa9a7677e4da65fb86e98a1edeb393672cf382b888ed97e9b0b278d82e` |
| `app/build/outputs/bundle/release/app-release.aab` | 6,972,900 | `f29cf2ace8462797eeee5ed5e219290f97326c25911f939ebe8129dcfc092714` |

These files are local pre-signing outputs. Physical-device layout/capture, clean install/upgrade, public HTTPS, signing, and Play upload remain BLK-006/BLK-007.
