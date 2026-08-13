# Codex execution plan

## Phase 0 — provenance and controls

- Preserve the byte-verified handoff as a local Git baseline and tag.
- Restore the missing execution records.
- Make verification work from both Windows and Unix-like runners.
- Refresh generated source inventory and record the first evidence commit.

## Phase 1 — web correctness and usability

- **Complete (2026-08-12).** Enumerated custom HTML/CSS/JavaScript producers and public/private route families.
- Rendered 37 authenticated route states plus public estimate, invoice, payment, receipt, and PDF routes with fictional temporary data.
- Added a real Chromium-family browser gate for dialog/drawer close paths, Escape behavior, focus restoration, and horizontal overflow at 1440×900 and 390×844.
- Repaired PWA, Hub, active/legacy RoomFlow, Full ERP recovery, Windows time-zone, and PDF portability defects while preserving Floodman branding and attribution.
- **Complete (2026-08-13).** Routed the genuine ERP credential exchange through the Office identity bridge so one successful ERP login establishes ERP, Office, and RoomFlow browser access; retained an explicit local-owner recovery path and return signed-in users to the originally requested module.

## Phase 2 — RoomFlow and Supabase

- **Complete (2026-08-12).** Fetched and verified only the pinned RoomFlow commit in the ignored vendor location: 1,032 tracked files, clean checkout.
- Inventoried estimator, jobs, geometry, AR/3D, costing, documents, recovery, guide, shared-data, and external-integration features across server, Android, and iOS packages.
- Repaired the Windows fetch failure reporting, required the previously omitted native `cost-tests.js`, added full local-dependency validation, and applied a deterministic overlay for the pinned duplicate job renderer.
- Passed 35 upstream Node tests, 9 upstream Edge smoke pages, the prepared-bundle Edge test, server/native RoomFlow smoke tests, and source/server/native package validation without advancing the pin.
- Proved authenticated, RLS-scoped original Supabase reads and stable repeat updates with fictional/mock fixtures; credentials and access tokens are not persisted.

## Phase 3 — Android

- **Complete (2026-08-13).** Fixed the build to JDK 17, Gradle 8.13, Android SDK 36, AGP 8.13.2, and Kotlin 2.3.20, using a short ignored Gradle cache to avoid Windows long-path atomic-move failures.
- Prepared and validated RoomFlow assets from the exact pin with package-visible release/pin provenance.
- Passed `compileDebugKotlin`, `testDebugUnitTest`, `lintDebug`, `assembleDebug`, `assembleRelease`, and `bundleRelease` without weakening lint; the only 17 lint notices concern newer dependency versions.
- Recorded local artifact SHA-256 values and added CI checksum generation. Physical-device/public-HTTPS and release signing remain separate external gates.

## Phase 4 — iOS

- **Local readiness complete (2026-08-13); compiler gate blocked by BLK-004.** Verified project generation inputs, plist/ATS, all icon slots, HTTPS/minimum-version/capability enforcement, device-bound session storage, coordinated refresh, and PDF MIME/signature validation.
- Prepared and validated the complete native RoomFlow bundle from the same exact pin; hardened loopback HTTP framing, WebView origin permissions, and all native close/cancel paths.
- Rebuilt the simulator workflow to select Xcode 26, validate sources/assets, generate the project, build unsigned, package the `.app`, and record checksums. The guarded TestFlight path now repeats the unsigned simulator compile for the same commit before signing.
- Actual `xcodebuild` remains `BLOCKED`, not passed, until the macOS workflow runs. Signing, archive, TestFlight, and device acceptance remain blocked until explicitly authorized and configured.

## Phase 5 — server and packaging

- **Local gates complete (2026-08-13); external acceptance remains blocked.** All 9 server smoke programs pass with isolated fictional state.
- Pinned the derivative base and four complete-AIO upstream images by registry digest, plus all five server-image workflow actions by commit.
- Added service-specific transitive Python constraints, a deny-by-default Docker context, and an automated immutable-input verifier.
- Completed a clean `--pull --no-cache` linux/amd64 derivative build and a network-isolated image audit: 174/174 server manifest entries, all five installed Python package sets, non-root ownership, empty inherited development-secret placeholders, and live-state exclusions passed.
- The publishing workflow now emits the registry digest, input hashes, provenance, and SBOM. Local Docker Scout advisory output is still unavailable under BLK-008; live staging, signing, and deployment remain at their recorded safety boundaries.

## Continuous evidence

After each phase, update `TASK-STATUS.md`, `TEST-MATRIX.md`, `BLOCKERS.md`, `DECISIONS.md`, generated inventories, affected manifests/checksums, and Git history. Do not convert an unavailable external gate into a pass.
