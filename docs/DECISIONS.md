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
