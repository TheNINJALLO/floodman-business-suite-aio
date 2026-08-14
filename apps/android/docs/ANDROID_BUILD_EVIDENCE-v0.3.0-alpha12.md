# Android 0.3.0-alpha12 build evidence

Evidence date: 2026-08-14

## Candidate identity

- Application ID: `com.floodman.operations` (`com.floodman.operations.debug` for debug)
- Version code/name: `12` / `0.3.0-alpha12`
- Minimum/compile/target SDK: `28` / `36` / `36`
- Floodman server payload: `4.6.9`
- Mobile API compatibility baseline: `0.3.0-alpha11`
- RoomFlow commit: `1f97817a52b916875e50cc6380c0d284072b8ce8`

## Toolchain and configuration

- Windows 11 x64
- Eclipse Temurin JDK `17.0.20+8`
- Gradle `8.13`
- Android Gradle Plugin `8.13.2`
- Kotlin `2.3.20`
- Android SDK 36 with local build tools `36.1.0`
- Ignored local configuration used `https://example.invalid/mobile-api/` and a Square placeholder. No production URL, payment credential, signing key, or live data was used.

The downloaded Temurin and Gradle archives matched their publishers' SHA-256 values before use. An initial lint invocation correctly rejected an unescaped Windows SDK drive separator in the ignored `local.properties`; the path was corrected, lint analysis was explicitly rerun, and the complete unchanged gate was then run successfully.

## Build gate

The final command used JDK 17 and Gradle 8.13:

```text
gradle --no-daemon --max-workers=1 :app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease :app:bundleRelease
```

| Gate | Result | Evidence |
|---|---|---|
| Debug and release compilation | PASS | The final 114-task graph completed successfully. |
| Unit tests | PASS | 1 test, 0 failures, 0 errors, 0 skipped. |
| Debug lint | PASS | 0 errors and 17 informational dependency/newer-version warnings; no lint check was disabled. |
| Debug APK | PASS | Version code 12, `0.3.0-alpha12-debug`, SDK 28–36; APK Signature Scheme v2 verifies with the local Android debug certificate. |
| Release APK | PASS, unsigned | Version code 12, `0.3.0-alpha12`, SDK 28–36; `apksigner` rejects it as unsigned, as expected without release credentials. |
| Release AAB | PASS, unsigned | Bundle packaging completed; `jarsigner` reports the bundle is unsigned, as expected. |
| Embedded RoomFlow | PASS | Debug APK, release APK, and release AAB contain Floodman 4.6.9 metadata, the exact pinned commit, Josh Aldrich attribution, and bridge cache version 12. |

## Artifact checksums

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `app/build/outputs/apk/debug/app-debug.apk` | 69,958,432 | `d48752c9f7eca6cfc2718ed539c48fd73cd24efdfa7b9ea43e337bf765d4acf9` |
| `app/build/outputs/apk/release/app-release-unsigned.apk` | 5,600,339 | `ea571db5930336571adfbf43f7239a1cb8ce10b590d996b3cd518655159ce07f` |
| `app/build/outputs/bundle/release/app-release.aab` | 6,607,766 | `194b9d017304cdff0eaf487c1da0d3508413cd3334a02920a7a545edf945a59a` |

`app/build/outputs/SHA256SUMS` records the same values beside the generated packages. Build outputs and local machine configuration remain ignored rather than being committed to source control.

Physical-device/public-HTTPS acceptance, production signing, and Play upload remain BLK-006/BLK-007 and are not claimed by this local build.
