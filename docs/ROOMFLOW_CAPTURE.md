# RoomFlow Capture

RoomFlow Capture is the authenticated, room-by-room measurement workflow inside Floodman RoomFlow. It uses the existing Floodman user, workspace, customer, property, job, estimate, audit, and synchronization records. It does not have a separate login or database.

Current source identity is Floodman `4.7.0`, Mobile API `0.3.0-alpha11`, Android `0.4.0-alpha01` (build 13), iOS `0.1.0-alpha03`, and RoomFlow commit `1f97817a52b916875e50cc6380c0d284072b8ce8`. The server/web and Android identities were advanced under a scoped local-test release exception; Xcode, physical-device, staging, container, signing/store, and production gates remain external.

## Staff field guide

1. Sign into Floodman and open the existing customer, service property, and job.
2. Open **RoomFlow**, then **Room capture**.
3. Choose **Scan room with this device**, **Enter room manually**, or **Start from a room template**.
4. Before scanning, confirm the room name, type, level, ceiling height, capture mode, and display units.
5. For guided capture, move slowly and aim the center reticle where the floor meets both walls. Hold steady, then add corners in order.
6. Return near the first corner and choose **Finish room**. Do not add the first corner twice.
7. Review the plan. Drag or enter corner coordinates, correct wall lengths, lock checked walls, rotate the room, and compare the captured and corrected outlines.
8. Add doors, windows, and open-wall sections to the correct wall. Confirm their offset, width, height, and sill height.
9. Select only the affected floor, ceiling, and walls. For walls, choose the entire wall, lower/cut-height strip, rectangular section, or supported freeform area.
10. Review calculated floor, ceiling, perimeter, gross wall, opening deduction, and net wall quantities. Floodman does not silently add chargeable estimate lines.
11. Save the room. A weak connection shows that the operation is saved locally and pending synchronization.
12. Repeat one room at a time. Positioning rooms together on a level remains a manual RoomFlow canvas task.

If tracking is weak, improve lighting, uncover the camera, point at a surface with visible detail, and move more slowly. Manual entry is always available. Closing a partial native scan asks before discarding it. A completed but unsaved review is restored from device storage after an unexpected close.

## Accuracy and privacy notice

Camera, ARCore, ARKit, RoomPlan, and LiDAR dimensions must be checked before final construction, architectural, legal, or insurance use. Floodman is not certified surveying equipment and makes no sub-inch claim.

- Normalized vertices, openings, confidence, corrections, scope, and derived quantities may be saved.
- Raw camera video, camera images, depth maps, and point clouds are not saved or uploaded.
- Native capture buffers are paused or cleared when capture closes or the app backgrounds.
- `scanMetadata.rawCaptureRetained` is always `false`; the server rejects raw-capture fields.
- Original RoomFlow import passwords are transient and unrelated to camera capture.

## Device capability matrix

| Surface | Preferred mode | Fallback | Current verification boundary |
|---|---|---|---|
| LiDAR iPhone/iPad with RoomPlan support | `apple-roomplan` | `apple-arkit-lidar`, then manual | Real implementation and fixture/static checks exist; Xcode and device run are BLK-004/BLK-006. |
| ARKit iPhone/iPad without RoomPlan | `apple-arkit-guided` | Manual | Uses real center-screen estimated-plane raycasts; Xcode/device run remains external. |
| ARCore Android with Automatic Depth | `android-arcore-depth` | Guided ARCore, then manual | Compiles/tests/packages locally; physical depth acceptance remains BLK-006. |
| ARCore Android without Depth | `android-arcore-guided` | Manual | Uses real center-screen ARCore hit tests against valid planes/points. |
| Standard browser | Manual entry and the pinned RoomFlow **Camera Estimate** fallback | Templates/manual | Camera Estimate is explicitly lower-confidence and requires verification. It is not represented as AR or LiDAR. |
| Unsupported/permission-denied device | Manual entry/templates | None required | RoomFlow and existing jobs remain usable. |

The system captures one room per session. Whole-house SLAM, automatic room joining, multi-floor alignment, point-cloud upload, and photorealistic reconstruction are not part of this release.

## Architecture and ownership

```text
Floodman authenticated job
  -> embedded pinned RoomFlow web UI
     -> shared capture schema and geometry
     -> review, affected scope, estimates, persistence
     -> native bridge when available
        -> Android ARCore + optional Depth
        -> Apple RoomPlan or guided ARKit
  -> Office/Mobile API capture service
     -> workspace/job authorization
     -> room revisions + idempotency receipts + redacted audit
```

Floodman-owned code lives in:

- `server/roomflow/capture/` — schema, geometry, UI, and browser fixtures
- `server/office-console/app/roomflow_capture.py` — migration and geometry validation
- `server/office-console/app/roomflow_capture_service.py` — persistence, revisions, idempotency, and audit
- `apps/android/.../roomflow/capture/` — ARCore renderer/session, models, and durable outbox
- `apps/ios/FloodmanOperations/RoomFlow/` — RoomPlan, ARKit, models, and durable outbox

The upstream RoomFlow repository is unchanged. Production preparation uses the checksummed snapshot in `server/roomflow/release-assets/`; it does not download or patch source when the Pterodactyl server starts. `scripts/verify_roomflow_release_assets.py` verifies every bundled input before preparation.

## Capture schema

The canonical schema is `server/roomflow/capture/roomflow-capture-schema-v2.json`. Application-boundary distances are decimal feet; native engines convert from meters. A room contains stable session/job/workspace/level/room IDs, ordered polygon vertices, openings, affected areas, compatibility `w/l/h`, scan metadata, and derived measurements.

Legacy rectangle rooms migrate idempotently. Existing room IDs, openings, snapshots, estimates, proposals, invoices, work orders, custom items, rentals, equipment deployments, and customer/property links are preserved. Irregular area uses the polygon, never `w * l`.

## Native bridge protocol

Every web-to-native message uses this bounded, platform-neutral envelope:

```json
{
  "version": 2,
  "sessionId": "uuid",
  "type": "capabilitiesRequested",
  "requestId": "uuid",
  "payload": {}
}
```

The 256 KB maximum is enforced in web and native code. Unknown versions/types return structured errors. Replies echo `version`, `sessionId`, and `requestId`; stale or mismatched sessions are ignored. Required capture messages include capability, session, tracking/reticle, point, reset, height, opening, completion, cancellation, and failure events. Additive persistence messages request rooms, queue an operation, and replay the outbox.

Android exposes the bridge only to its packaged `appassets.androidplatform.net` RoomFlow origin. Apple exposes it only to the loopback RoomFlow origin and blocks arbitrary navigation. Both serialize JSON before invoking JavaScript; user content is not concatenated as executable source.

## API and synchronization

ERP-session endpoints are under:

```text
GET    /office/api/roomflow/jobs/{job_id}/capture/rooms
GET    /office/api/roomflow/jobs/{job_id}/capture/rooms/{room_id}
POST   /office/api/roomflow/jobs/{job_id}/capture/rooms
PUT    /office/api/roomflow/jobs/{job_id}/capture/rooms/{room_id}
DELETE /office/api/roomflow/jobs/{job_id}/capture/rooms/{room_id}
POST   /office/api/roomflow/jobs/{job_id}/capture/operations
```

Native clients use the equivalent `/mobile-api/v1/roomflow/...` routes with the existing short-lived Floodman token and rotating refresh flow. The server resolves workspace/job ownership; client workspace IDs are never authorization by themselves.

Each write has a stable operation ID and expected room revision. Exact retries return the stored receipt, stale revisions return a conflict, and an older offline operation cannot overwrite a newer room. Android and Apple persist at most 200 reviewed operations in private app storage using atomic replacement; the browser uses origin-scoped storage. A newly completed native result is also retained as an unsaved review draft until it is queued or synchronized.

Audit records summarize room creation, correction/rescan, opening/scope changes, and deletion without retaining tokens, raw capture, or full sensitive payloads.

## Build and test

Prepare native assets without a network checkout:

```bash
python scripts/verify_roomflow_release_assets.py
apps/android/scripts/prepare-roomflow-assets.sh
apps/ios/scripts/prepare-roomflow-assets.sh
```

Run shared/server/browser checks:

```bash
python server/tests/roomflow_capture_geometry_smoke.py
node server/roomflow/capture/tests/geometry.test.cjs
python server/tests/roomflow_capture_api_smoke.py
python server/tests/web_ui_smoke.py
python scripts/verify_roomflow_pin.py
```

Run Android with JDK 17, Gradle 8.13, and SDK 36:

```bash
cd apps/android
gradle --no-daemon :app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug
gradle --no-daemon :app:assembleDebug :app:assembleRelease :app:bundleRelease
```

Run Apple on macOS 26/Xcode 26:

```bash
cd apps/ios
xcodegen generate
xcodebuild -project FloodmanOperations.xcodeproj -scheme FloodmanOperations \
  -destination 'generic/platform=iOS Simulator' CODE_SIGNING_ALLOWED=NO build
# The workflow selects and boots an available iPhone simulator, then runs xcodebuild test.
```

The authoritative workflows are `.github/workflows/build-android.yml` and `.github/workflows/build-ios-simulator.yml`. Signing and store workflows remain separate approval gates.

## Manual acceptance checklist

- [ ] Android supported device installs/updates ARCore only after scan is selected.
- [ ] Android Depth-supported and guided non-Depth devices both capture real hit-test coordinates.
- [ ] LiDAR Apple device uses RoomPlan and returns walls/openings/height.
- [ ] Apple guided ARKit fallback pins floor-wall corners from raycasts and relocalizes.
- [ ] Permission denial and unsupported devices keep manual RoomFlow usable.
- [ ] Back/Close on partial capture confirms discard; backgrounding stops the session.
- [ ] Reticle, tracking, confidence, segment length, closure distance, undo, reset, height, haptic, sound, and safe-area controls work outdoors/in dim/feature-poor rooms as applicable.
- [ ] Rectangle, L-shape, angled, and custom rooms remain geometrically correct.
- [ ] Drag/add/remove corner, wall correction/lock, rotation, compare, undo/redo, opening placement, and affected scopes survive save/reload.
- [ ] Completed unsaved review survives app interruption; offline save shows pending and later synchronizes once.
- [ ] Retrying the same operation creates no duplicate; concurrent edits show a revision conflict.
- [ ] Another authorized device restores the room under the same workspace/customer/property/job.
- [ ] Estimate quantities and work-order inputs match polygon/wall/opening math; no charge is added without confirmation.
- [ ] Existing layout, estimate, proposal, invoice, work order, customer import, and document PDF workflows still pass.
- [ ] Raw video/depth/point-cloud data is absent from app files, requests, server state, logs, and audits.

## Troubleshooting

- **Scan button disabled:** save/open the active Floodman job, select its company workspace, and allow the app to complete capability negotiation.
- **ARCore unavailable:** install/update Google Play Services for AR when prompted. Unsupported phones use manual entry.
- **Tracking limited:** improve light and visible texture, move slowly, and revisit a previously scanned corner.
- **RoomPlan unavailable:** use guided ARKit or manual entry. RoomPlan support is a runtime device capability.
- **Room will not close/save:** capture at least three distinct corners, remove crossed walls, keep every segment at least 0.25 ft, and verify openings fit their walls and ceiling.
- **Sync pending:** keep the app signed in and reopen the job after connectivity returns. Do not recreate the room; the stable operation ID is designed for retry.
- **Revision conflict:** reload the newer room, compare it with the local review, then intentionally reapply corrections.
- **Apple build unavailable locally:** run the unsigned macOS simulator workflow; a Windows static check is not an Xcode pass.
- **Release packaging:** use only the distinct v4.7.0 runtime/launcher/checksums for this capture build; never relabel or overwrite v4.6.10. Complete device, staging, container, clean upgrade/restart, backup/restore, signing/store, and production gates before wider release.
