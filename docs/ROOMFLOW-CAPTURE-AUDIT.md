# RoomFlow Capture implementation audit

Date: 2026-08-18

Branch: `feature/roomflow-capture`

Base: `7aa4bfd` (`build: prepare web release 4.6.10`)

This audit records the inputs used to begin the integrated RoomFlow Capture build. It does not claim implementation or device acceptance.

## Source and release identity

- The main worktree was clean before the feature branch was created. At audit time there was no configured Git remote or GitHub CLI, so publication remained BLK-010; authenticated HTTPS publication and CI later resolved that blocker under DEC-028/CI-001.
- Canonical editable source is already extracted under `server/`, `apps/android/`, and `apps/ios/`. There is no `floodman-source.zip` in the current handoff. Historical ZIPs are not editing sources.
- Current identities are server `4.6.10`, Mobile API `0.3.0-alpha11`, Android `0.3.0-alpha12`, iOS `0.1.0-alpha03`, and RoomFlow commit `1f97817a52b916875e50cc6380c0d284072b8ce8`.
- The ignored nested checkout at `vendor/roomflow/source` resolves to the required commit but has pre-existing deleted Gradle build intermediates and Windows long-path warnings. Those artifacts are not part of the main worktree. They will not be reset, deleted, or used as mutable release source.

## RoomFlow source and packaging

- `server/roomflow/prepare-roomflow.py` currently accepts a local archive or downloads the pinned GitHub archive, validates archive paths, copies browser assets into `/home/container/data/roomflow/current`, and applies suite-owned compatibility overlays.
- Android and iOS preparation scripts similarly construct tracked app bundles from the exact pin and suite-owned patches.
- Production startup must no longer require GitHub. The implementation will package a deterministic checksum-verified snapshot from the pinned Git object while preserving the current target layout, non-root ownership, persistent data paths, and rollback provenance.
- The upstream pin will not advance and the standalone RoomFlow repository will not be changed.

## Authentication and tenancy

- `/office/roomflow` already requires the unified ERP/Office session and `estimates.view` permission. Nginx protects `/roomflow/` through the same-origin Office auth subrequest and rejects anonymous or forbidden access.
- RoomFlow workspaces are already Floodman-owned and selected server-side. New capture routes must derive workspace and job ownership from authenticated records rather than accept a client-provided tenant override.
- Existing browser and native routes cover bootstrap, workspace/customer/property lookup, job snapshot/layout save, estimates, and the stable-ID Supabase importer. Capture APIs will extend these contracts additively.

## Persistence and synchronization

- The current Office service persists operational records in `office-state.json` through `OfficeStore`. Repository policy requires an approved migration plan before moving long-term state to PostgreSQL, so this feature will use new versioned record kinds in the existing store and will not touch a live database.
- Existing browser/native RoomFlow code preserves some pending snapshots, but there is no durable revisioned operation outbox. Capture needs stable room and operation identifiers, idempotent receipts, optimistic revisions, ordered replay, explicit conflict responses, and redacted audit records.
- Raw camera images, AR frames, and depth maps are not business records and must never be uploaded or persisted. Only user-reviewed geometry, feature metadata, provenance, and bounded quality summaries are retained.

## Browser workflow

- The pinned browser bundle already renders RoomFlow layouts and contains WebXR/camera estimation code. Floodman currently injects suite-owned workspace and save controls through `floodman-panel.js` and `floodman-roomflow.js`.
- The embedded capture workflow must add manual entry, native capability selection, measurement progress, review/edit/correction, openings, affected-area scope, save/sync state, keyboard support, and reliable dismiss paths. It must never label inferred or placeholder geometry as measured field data.
- A versioned bridge with request IDs and structured success/error envelopes is required so browser, Android, and Apple clients share one contract.

## Android

- The app is Kotlin/Compose and hosts RoomFlow in a trusted app-assets WebView. It requests camera permission and has a Floodman bridge, but it does not currently depend on ARCore or expose a real `RoomFlowNativeAR` implementation.
- Required work includes ARCore install/support checks, plane/raycast boundary collection, optional supported Depth sampling, lifecycle/permission handling, deterministic fake providers, bridge v2, and a durable local outbox.
- Local JDK/Gradle/SDK compile, unit, lint, APK, and AAB gates are available. Real-device ARCore/depth acceptance remains BLK-006 and signing remains BLK-007.

## Apple

- The SwiftUI app hosts the pinned web bundle through a loopback server and WKWebView. Camera usage text exists, but there is no RoomPlan/ARKit capture implementation and the current message-handler name does not satisfy the bundle's native AR bridge contract.
- Required work includes RoomPlan support detection and capture, ARKit raycast fallback, semantic opening mapping, lifecycle/permission/error handling, deterministic fixtures, bridge v2, and a durable local outbox.
- Windows can validate source, schema fixtures, project inputs, and workflow guards. Actual simulator compilation requires macOS/Xcode (BLK-004); physical LiDAR/fallback acceptance remains BLK-006.

## CI, containers, and external gates

- Current workflows cover repository verification, Android build/package, iOS simulator, guarded TestFlight, and server-image publishing. New capture paths and tests must be wired into validation; publishing must remain behind successful release gates.
- Dockerfiles are pinned and the current derivative image contract is proven historically, but the local Docker daemon is stopped. It will not be started because unrelated containers may restart; the fresh image gate remains BLK-009.
- Staging install/upgrade/restart/backup/restore is BLK-005. Device tests are BLK-006, signing/store operations BLK-007, and advisory scanning is BLK-008. Remote CI was BLK-010 at audit time and later completed under CI-001; no pull request was required for the explicitly authorized `main` publication.

## Implementation order

1. Shared schema, migrations, geometry engine, deterministic fixtures, and cross-language tests.
2. Authenticated persistence, revisions, idempotent operation replay, conflicts, and audit records.
3. Embedded browser manual/review/affected-area workflow and native bridge v2.
4. Android ARCore/depth implementation, offline queue, and complete local build gates.
5. Apple RoomPlan/ARKit implementation and every locally available gate, leaving Xcode/device results blocked until run.
6. Network-independent pinned source packaging, CI path updates, full regression, manifests, checksums, release notes, and candidate packaging.
