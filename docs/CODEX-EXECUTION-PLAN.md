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

## Phase 2 — RoomFlow and Supabase

- **Complete (2026-08-12).** Fetched and verified only the pinned RoomFlow commit in the ignored vendor location: 1,032 tracked files, clean checkout.
- Inventoried estimator, jobs, geometry, AR/3D, costing, documents, recovery, guide, shared-data, and external-integration features across server, Android, and iOS packages.
- Repaired the Windows fetch failure reporting, required the previously omitted native `cost-tests.js`, added full local-dependency validation, and applied a deterministic overlay for the pinned duplicate job renderer.
- Passed 35 upstream Node tests, 9 upstream Edge smoke pages, the prepared-bundle Edge test, server/native RoomFlow smoke tests, and source/server/native package validation without advancing the pin.
- Proved authenticated, RLS-scoped original Supabase reads and stable repeat updates with fictional/mock fixtures; credentials and access tokens are not persisted.

## Phase 3 — Android

- Check Gradle wrapper/toolchain reproducibility and dependency pins.
- Prepare RoomFlow assets from the pinned source.
- Run `compileDebugKotlin`, `testDebugUnitTest`, `lintDebug`, `assembleDebug`, `assembleRelease`, and `bundleRelease` without weakening lint.
- Record artifact SHA-256 values. Physical-device/public-HTTPS acceptance remains a separate external gate.

## Phase 4 — iOS

- Review source parity, bundle preparation, entitlements, transport security, API capability checks, PDF validation, and project-generation inputs.
- Prepare RoomFlow assets from the same pin.
- Generate the project and run an unsigned simulator build on macOS.
- Keep signing, archive, TestFlight, and device acceptance blocked until explicitly authorized and configured.

## Phase 5 — server and packaging

- Run the complete server smoke suite with isolated data.
- Re-run static, secret, structured-file, and manifest checks.
- Inspect container inputs for mutable tags and verify the derivative build when Docker/network are available.
- Defer live staging and release work to their recorded safety boundaries.

## Continuous evidence

After each phase, update `TASK-STATUS.md`, `TEST-MATRIX.md`, `BLOCKERS.md`, `DECISIONS.md`, generated inventories, affected manifests/checksums, and Git history. Do not convert an unavailable external gate into a pass.
