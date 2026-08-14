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

## DEC-015 — Make production container inputs immutable and minimal

- Date: 2026-08-13
- Decision: Pin every active upstream image by registry digest, pin server-image workflow actions by commit, constrain every installed Python package version per service, and send only reviewed Dockerfiles plus server source through a deny-by-default build context.
- Reason: Mutable image tags, unconstrained transitive packages, and a broad repository context prevented a later build from being reproduced or proved free of ignored live-state files.
- Consequence: The active derivative and complete-AIO Dockerfiles share reviewed input identities; `verify_container_inputs.py` is part of repository verification; CI always pulls and builds without cache and records provenance, SBOM, published digest, and build-input hashes.

## DEC-016 — Separate isolated image verification from live-host acceptance

- Date: 2026-08-13
- Decision: Audit the built image only in a one-shot container with networking disabled and no mounts or published ports. Do not start, stop, restart, or reuse the unrelated running host containers discovered during Docker inspection.
- Reason: The available Docker engine contains pre-existing Floodman and supporting service containers whose data and operational ownership were not placed in scope. Exercising them would cross the staging and database safety boundaries.
- Consequence: PKG-001 can prove image contents and package reproducibility locally, while startup/restart/backup/restore remain STAGE-001. A vulnerability scan that produced no report remains BLK-008 rather than a pass.

## DEC-017 — Regenerate deployable Pterodactyl artifacts without rewriting rollback provenance

- Date: 2026-08-13
- Decision: Treat `launcher/mobile-start.sh`, current tracked server runtime files, and the reviewed immutable AIO base as the inputs for `deployment/releases/`. Generate the ZIP, its internal manifest, deployment checksum list, synchronized release launcher, and v4.6.7 egg through one deterministic script.
- Reason: The deployable ZIP preceded later web, RoomFlow, native contract, and test repairs, and the egg still embedded a v3.3.0 launcher even though its filename described v4.6.7. That combination could install stale code on a new server.
- Consequence: `scripts/verify_pterodactyl_release.py` is a repository gate. `release-artifacts/` remains immutable historical/rollback evidence; it is deliberately not overwritten by current deployment packaging.

## DEC-018 — Use the genuine ERP login as the browser identity entry point

- Date: 2026-08-13
- Decision: Route the same-origin Gauzy `/api/auth/login` request through a narrow Office bridge. The bridge forwards the verified Gauzy response to the ERP browser, maps the verified identity to its existing Office role, and issues the HttpOnly `floodman_session` used by Office and integrated RoomFlow. Existing ERP JWTs may be exchanged only through `/login/erp-session`, after `/user/me`, tenant, and organization validation.
- Reason: A second Office-branded password form still required users to think about two login surfaces. Intercepting the real ERP request produces one credential entry and preserves Gauzy's native browser session.
- Safety: Passwords and ERP bearer tokens are held only for the verification request and are not persisted or logged. The local Owner login remains reachable only as an explicit installation-recovery fallback. RoomFlow still requires `estimates.view`, and anonymous/forbidden auth subrequests return 401/403 rather than exposing its static assets.

## DEC-019 — Scope v4.6.8 to a non-native Pterodactyl test release

- Date: 2026-08-13
- Decision: On the user's explicit instruction, assign server and Pterodactyl artifacts the distinct `4.6.8` identity needed to test an update on a host that already recognizes `4.6.7`. Keep Android `0.3.0-alpha11`, iOS `0.1.0-alpha02`, Mobile API `0.3.0-alpha11`, and RoomFlow commit `1f97817a52b916875e50cc6380c0d284072b8ce8` unchanged.
- Evidence policy: Run and record every available server, browser, package, manifest, and container-input gate. Record Android/iOS builds as user-deferred, not passed. Staging install/upgrade/restart/backup/restore remains blocked until performed on an approved node.
- Safety: This exception authorizes local test artifacts only. It does not authorize production deployment, signing, store upload, live credentials, live database changes, or public administrative exposure.

## DEC-020 — Use Floodman workspaces instead of a second RoomFlow account

- Date: 2026-08-14
- Decision: In the integrated browser, replace RoomFlow's upstream Supabase account, company creation, company switcher, shared-job refresh, and logout handlers with Floodman Office-session workspace actions. Keep the original Supabase importer as an explicit authenticated migration tool, not an interactive staff login.
- Reason: The upstream create-company button still checked `state.sessionUser` and displayed “Please Sign In or Create an Account,” even though the user had already authenticated through the unified Floodman ERP login. That made the integrated RoomFlow UI appear unusable and contradicted the single-login contract.
- Safety: Browser workspace creation requires `estimates.manage`; selection requires `estimates.view`; jobs and synchronized estimates are scoped to the selected workspace. No Supabase password, ERP password, access token, or second browser session is persisted.
- Release consequence: Produce server/Pterodactyl v4.6.9 so a host already identifying as v4.6.8 installs the repair. Android/iOS identities and the pinned RoomFlow commit remain unchanged and their builds are deferred.

## DEC-021 — Advance native candidates without changing the Mobile API floor

- Date: 2026-08-14
- Decision: On the user's explicit instruction to update Android/iOS and send Android to be built, advance Android to `0.3.0-alpha12`/build 12 and iOS to `0.1.0-alpha03`/build 3. Keep the server Mobile API at `0.3.0-alpha11`, its minimum Android version at `0.3.0-alpha11`, its minimum iOS version at `0.1.0-alpha02`, and RoomFlow pinned at `1f97817a52b916875e50cc6380c0d284072b8ce8` because the native changes are additive and older validated clients remain compatible.
- Scope: Add the selected Floodman workspace to native RoomFlow customer/property lookup and enforce that workspace boundary on the server. Produce local debug and unsigned release Android artifacts and prepare the unsigned iOS simulator source/workflow. Do not access signing credentials, upload to a store, dispatch TestFlight, deploy to production, or change a live database.
- Dispatch consequence: The checkout has no Git remote and no GitHub CLI, so the Android workflow cannot be sent to an external runner from this environment. The authoritative local Android build remains in scope; workflow dispatch remains BLK-010 until a repository target is configured.
