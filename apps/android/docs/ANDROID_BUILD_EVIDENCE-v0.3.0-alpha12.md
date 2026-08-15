# Android 0.3.0-alpha12 build evidence

Evidence date: 2026-08-15

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

The downloaded Temurin and Gradle archives matched their publishers' SHA-256 values before use. The ignored local configuration and fixed short Gradle cache were reused from the verified alpha12 toolchain.

## Build gate

The final command used JDK 17 and Gradle 8.13:

```text
gradle --no-daemon --max-workers=1 :app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease :app:bundleRelease
```

| Gate | Result | Evidence |
|---|---|---|
| Debug and release compilation | PASS | After the cold graph produced fresh artifacts, the same complete 114-task gate returned `BUILD SUCCESSFUL` in 51 seconds (3 executed, 111 verified up to date). |
| Unit tests | PASS | 1 test, 0 failures, 0 errors, 0 skipped. |
| Debug lint | PASS | 0 errors and 17 informational dependency/newer-version warnings; no lint check was disabled. |
| Debug APK | PASS | Version code 12, `0.3.0-alpha12-debug`, SDK 28–36; APK Signature Scheme v2 verifies with the local Android debug certificate. |
| Release APK | PASS, unsigned | Version code 12, `0.3.0-alpha12`, SDK 28–36; `apksigner` rejects it as unsigned, as expected without release credentials. |
| Release AAB | PASS, unsigned | Bundle packaging completed; `jarsigner` reports the bundle is unsigned, as expected. |
| Embedded RoomFlow | PASS | Debug APK, release APK, and release AAB contain Floodman 4.6.9 metadata, the exact pinned commit, Josh Aldrich attribution, and the refreshed customer/import/Detroit-time usability bridge. |

## Artifact checksums

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `app/build/outputs/apk/debug/app-debug.apk` | 71,222,878 | `c0e753b7ed8a64c0e0ba11282bcf6c495272175f98d970520dd1bd9d9afd5e93` |
| `app/build/outputs/apk/release/app-release-unsigned.apk` | 5,600,447 | `22f3afa31be51cb9e621389eb66c79fe1264185fafa3af25aff85bdb68ff7d38` |
| `app/build/outputs/bundle/release/app-release.aab` | 6,610,597 | `a429eb11ae64d55254f471bda751219dbeeb433f792a3d67fdba95a0a068026f` |

`app/build/outputs/SHA256SUMS` records the same values beside the generated packages. Build outputs and local machine configuration remain ignored rather than being committed to source control.

Physical-device/public-HTTPS acceptance, production signing, and Play upload remain BLK-006/BLK-007 and are not claimed by this local build.
