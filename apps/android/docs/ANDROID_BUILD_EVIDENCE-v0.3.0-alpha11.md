# Android 0.3.0-alpha11 build evidence

Evidence date: 2026-08-13

## Fixed toolchain

- Temurin OpenJDK `17.0.20+8`
- Gradle `8.13`
- Android Gradle Plugin `8.13.2`
- Kotlin `2.3.20`
- Android SDK compile/target API `36`, minimum API `28`
- Pinned RoomFlow commit `1f97817a52b916875e50cc6380c0d284072b8ce8`

The first exact-JDK-17 run followed a clean application build and completed all requested compile, unit, lint, debug APK, release APK, and release AAB tasks. A second invocation of the same fixed command completed successfully with 114 actionable tasks (3 executed, 111 up-to-date), confirming the resulting task graph. The long repository path could not reliably host Gradle's atomic transform cache on Windows, so the ignored cache was placed at `C:\Users\Flood\.gradle\floodman-android-8.13`; this changes no source or package input.

```powershell
gradle --no-daemon --max-workers=1 :app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease :app:bundleRelease
```

## Results

| Gate | Result | Evidence |
|---|---|---|
| Debug and release compilation | PASS | Kotlin/Java compilation and release R8/resource shrinking completed. |
| Debug unit tests | PASS | 1 test, 0 failures, 0 errors, 0 skipped (`DeviceProofTest`). |
| Debug lint | PASS | 0 errors; 17 warnings, all dependency/newer-version availability notices. No lint rule was disabled. |
| Debug APK | PASS | Package `com.floodman.operations.debug`; version code 11; version `0.3.0-alpha11-debug`; APK signature v2 verifies with the local Android debug certificate. |
| Release APK/AAB generation | PASS | Both pre-signing packages generated. They are intentionally unsigned because release credentials are outside this gate. |
| Embedded RoomFlow | PASS | Package contains the validated native runtime, bridge, `cost-tests.js`, vendor assets, and package-visible provenance metadata for the exact pin. |

## Artifact SHA-256

These hashes identify the local pre-signing outputs from the final source gate. Build outputs are ignored and are not committed.

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `app-debug.apk` | 70,790,918 | `b41d7964cf812d4bfe27c77899a928a9304a5f2ededd8fb72977e1abc0c37445` |
| `app-release-unsigned.apk` | 5,600,335 | `437c2bc5d87472112c4d644533a1f68eac635be8010f1b2e9eb876de962594cb` |
| `app-release.aab` | 6,606,955 | `6b89cbea87de2e7d602612915ead96e1719d80b1d32320af23baca60065166cf` |

The CI workflow now emits its own `SHA256SUMS` beside uploaded packages because signed or separately rebuilt artifacts will have different hashes.

## Remaining external gates

- Physical Android device acceptance and public staging HTTPS: `BLK-006`.
- Release keystore signing and Play upload: `BLK-007` and explicit approval.
