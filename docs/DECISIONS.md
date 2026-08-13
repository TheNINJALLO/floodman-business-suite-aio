# Decisions

## DEC-001 — Preserve the supplied archive state as the immutable baseline

- Date: 2026-08-12
- Decision: Verify the root manifest before initializing Git, then commit and annotate-tag the untouched extracted handoff.
- Reason: The supplied directory had no `.git` history, while its own handoff instructions required a private repository baseline before edits.
- Evidence: 553 manifest entries passed; commit `a3177cc`; tag `handoff-v4.6.7`.

## DEC-002 — Reconstruct missing execution controls without inventing historical passes

- Date: 2026-08-12
- Decision: Create the requested master prompt and ledgers from `AGENTS.md`, packaged handoff documents, recorded version identities, and the user's current acceptance priorities.
- Reason: The named files did not exist anywhere in the byte-verified package. Their absence means there is no trustworthy prior task/test state to resume.
- Consequence: Packaged claims remain historical context; every active pass requires fresh evidence.

## DEC-003 — Keep the RoomFlow pin unchanged

- Date: 2026-08-12
- Decision: Fetch and inspect exactly `1f97817a52b916875e50cc6380c0d284072b8ce8`; do not move to a newer upstream commit during readiness work.
- Reason: Release identity and native/server compatibility depend on the reviewed pin. Advancing it crosses an explicit release safety boundary.

## DEC-004 — Resolve executables explicitly in the Windows verifier

- Date: 2026-08-12
- Decision: On Windows, replace bare executable names with the absolute path returned by `shutil.which` before `subprocess.run`.
- Reason: Windows process search selected the inaccessible WSL `bash.exe` even when Git Bash appeared first on `PATH`; the explicit Git Bash path passed the same syntax check.
- Scope: Verification tooling only; no application runtime behavior changes.

## DEC-005 — Treat the root handoff manifest as baseline evidence

- Date: 2026-08-12
- Decision: Do not rewrite root `MANIFEST.sha256` after development begins. Refresh generated inventories and the component source manifests/checksums that cover modified deliverables instead.
- Reason: Rewriting the root manifest would erase the byte-level record of the untouched handoff preserved by `handoff-v4.6.7`.

## DEC-006 — Require browser evidence for persistent overlays

- Date: 2026-08-12
- Decision: Keep the new `server/tests/web_ui_smoke.py` in the normal server smoke glob and use a locally installed Chromium-family browser when available, while retaining route and static contract coverage when a browser is absent.
- Reason: A real browser exposed a Hub temporal-dead-zone initialization failure that JavaScript syntax checks and server route tests could not detect.
- Scope: The test uses fictional temporary records and no provider credentials or live data.

## DEC-007 — Make the Office test/runtime dependency set Windows-capable

- Date: 2026-08-12
- Decision: Pin `tzdata==2026.3` for the Office runtime, pin `playwright==1.62.0` for development tests, and format PDF dates without Unix-only `strftime` flags.
- Reason: `America/Detroit` resolution and `%-d` formatting failed on a clean Windows environment even though the application logic was otherwise valid.

## DEC-008 — Exclude local tool environments from repository evidence

- Date: 2026-08-12
- Decision: Exclude `.venv`, dependency/build directories, and test/type-check caches from generated source inventory, syntax validation, structured-file parsing, and secret-pattern scans. On Windows, prefer the Git installation's `bin/bash.exe` before the WSL shim.
- Reason: Local Playwright and Python dependencies are ignored test infrastructure, not checked-in Floodman source; counting or validating them made evidence host-dependent and allowed Windows executable search order to select an unusable Bash shim.

## DEC-009 — Preserve the RoomFlow pin and apply a deterministic package overlay

- Date: 2026-08-12
- Decision: Keep commit `1f97817a52b916875e50cc6380c0d284072b8ce8` untouched and ignored, then apply the reviewed duplicate-job-renderer repair only to prepared server/Android/iOS bundles.
- Reason: The pin's `app.js` declares two `renderJobsList` functions for different surfaces. Chromium runs it, but Node rejects the duplicate declaration and callers cannot explicitly refresh both lists. Advancing the pin is outside the release boundary.
- Gate: The overlay must reject an unexpected source layout, be idempotent, pass Node syntax, and pass a real browser render/close test.

## DEC-010 — Replace upstream native cloud sessions with Floodman Mobile API bridges

- Date: 2026-08-12
- Decision: Package the complete core RoomFlow estimator in both native apps while removing upstream Supabase/Townsquare browser-session scripts from native HTML. Use the authenticated Floodman Mobile API for workspaces, shared jobs, catalog data, stable imports, actual layouts, and grouped estimates.
- Reason: A second browser login would weaken the private-surface and short-lived-token contract. Original Supabase data remains available through a one-time RLS-scoped import using credentials that are never persisted.
- Consequence: Android exposes the import inside its RoomFlow bar; iOS exposes workspace selection/creation and import as native, dismissible sheets and bootstraps the WebView from the same shared Mobile API contract.

## DEC-011 — Keep the Android alpha toolchain fixed and separate buildability from signing

- Date: 2026-08-13
- Decision: Validate alpha11 with JDK 17, Gradle 8.13, SDK 36, AGP 8.13.2, and Kotlin 2.3.20; do not absorb lint-advertised dependency upgrades into this fixed release. Use a short ignored Gradle user home on Windows when the long checkout path prevents atomic cache moves.
- Reason: The exact source gate passes with zero lint errors. Unreviewed dependency changes would expand the release scope, while the short cache path is host infrastructure only.
- Consequence: Debug and unsigned release packages are build-ready and checksummed. Release signing, store upload, and physical-device acceptance remain BLK-006/BLK-007 rather than being represented as local passes.

## DEC-012 — Narrow the live-data ignore exception for Android source

- Date: 2026-08-13
- Decision: Keep the repository-wide `data/` safety exclusion, but explicitly unignore only `apps/android/app/src/main/java/com/floodman/operations/data/*.kt`.
- Reason: Comparing the immutable 553-file handoff manifest to the baseline Git tree showed that the broad live-data rule had hidden four required Kotlin source files. Their bytes remained on disk and still matched both root and Android component hashes.
- Consequence: The original baseline tag is not rewritten. The four unchanged sources join version control in the Android milestone, while runtime/live data and the seven other policy-excluded archive/environment artifacts stay untracked and covered by manifest evidence.

## DEC-013 — Separate iOS source readiness from the macOS compiler gate

- Date: 2026-08-13
- Decision: Mark every locally verifiable iOS source, project, asset, transport, session, PDF, RoomFlow, and workflow contract with a dedicated static gate, while leaving the actual simulator result BLOCKED until Xcode runs it.
- Reason: Windows can prove deterministic inputs and catch platform-independent failures, but it cannot honestly substitute for Swift/Xcode compilation. The simulator workflow now creates the project, compiles without signing, packages the app, and records checksums; TestFlight repeats that compile for the same commit before touching signing.
- Consequence: IOS-001 advances past all available local work without creating a false T-014 pass. Feature-depth and physical-device acceptance remain separate staging/device gates.

## DEC-014 — Advertise and enforce the minimum iOS client additively

- Date: 2026-08-13
- Decision: Add `minimum_ios_version: 0.1.0-alpha02` to Mobile API health, config, and RoomFlow bootstrap responses, and require the iOS app to validate that value plus its capability set before login or session restore.
- Reason: Android already had a minimum-client field, while the Apple client had no equivalent compatibility contract. The additive field is ignored safely by older Android decoders and is smoke-tested across all three response surfaces.
