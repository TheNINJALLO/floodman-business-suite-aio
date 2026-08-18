# RoomFlow Capture unreleased candidate notes

Date: 2026-08-18

## Summary

Floodman now owns an integrated room-by-room capture workflow inside the authenticated RoomFlow surface. It adds shared schema-v2 geometry, revisioned/idempotent persistence, offline replay, browser manual/review tools, Android ARCore with optional Depth, Apple RoomPlan with ARKit fallback, and network-independent packaging of the unchanged RoomFlow pin.

The source reuses the existing Floodman login, workspace, customer/property/job records, Mobile API, audit trail, estimate quantities, and RoomFlow layout. It does not add a second account or database and does not retain raw camera/depth data.

## Compatibility and identity

- Server remains `4.6.10`; Mobile API remains `0.3.0-alpha11`.
- Android remains `0.3.0-alpha12`; Apple remains `0.1.0-alpha03` during implementation.
- Required capabilities are additive: `roomflow.capture.v2` and `roomflow.capture.offline.v1`.
- RoomFlow remains pinned at `1f97817a52b916875e50cc6380c0d284072b8ce8`.
- Existing capture-less clients remain above the unchanged minimum-client floors.

These identities are not a new release. In particular, the existing `deployment/releases/floodman-operations-runtime-v4.6.10.zip` is intentionally left byte-for-byte unchanged. Publishing new content under an already distributed semantic identity is prohibited.

## Verified locally

- all 12 server/browser smoke programs;
- shared Python and JavaScript geometry fixtures;
- authenticated CRUD, workspace isolation, revisions, idempotency, outbox batch replay, audit redaction, snapshot preservation, and Supabase repeat import;
- responsive/dismissible browser capture at 320/360/390/430 px;
- Android forced compile, 8 unit tests, lint, debug/release APK, and release AAB;
- Apple source/project/workflow readiness and six declared XCTest methods;
- checksum-verified offline RoomFlow release assets and native preparation.

## Remaining release gates

- macOS/Xcode simulator build and XCTest execution;
- Android Depth/guided and Apple RoomPlan/ARKit physical-device acceptance;
- clean install, upgrade, restart, staging HTTPS, backup, and restore;
- current container build/advisory scan on an isolated engine;
- release signing/store credentials and explicit release approval;
- a distinct version assignment, regenerated runtime/native packages, final manifests, checksums, and release verification.

Until those gates pass, this is reviewable source and local Android evidence—not a deployable RoomFlow Capture release.
