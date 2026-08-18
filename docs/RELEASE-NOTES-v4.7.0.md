# Floodman Operations 4.7.0 release notes

Date: 2026-08-18

## Summary

Floodman now owns an integrated room-by-room capture workflow inside the authenticated RoomFlow surface. It adds shared schema-v2 geometry, revisioned/idempotent persistence, offline replay, browser manual/review tools, Android ARCore with optional Depth, Apple RoomPlan with ARKit fallback, and network-independent packaging of the unchanged RoomFlow pin.

The source reuses the existing Floodman login, workspace, customer/property/job records, Mobile API, audit trail, estimate quantities, and RoomFlow layout. It does not add a second account or database and does not retain raw camera/depth data.

## Compatibility and identity

- Server/Pterodactyl advances to `4.7.0`; Mobile API remains `0.3.0-alpha11`.
- Android advances to `0.4.0-alpha01`/build 13; Apple remains `0.1.0-alpha03`.
- Required capabilities are additive: `roomflow.capture.v2` and `roomflow.capture.offline.v1`.
- RoomFlow remains pinned at `1f97817a52b916875e50cc6380c0d284072b8ce8`.
- Existing capture-less clients remain above the unchanged minimum-client floors.

The distinct identities prevent an installed v4.6.10/alpha12 system from treating this new content as an already-applied update. Minimum Android/iOS client versions remain unchanged because the server changes are additive.

## Verified locally

- all 12 server/browser smoke programs;
- shared Python and JavaScript geometry fixtures;
- authenticated CRUD, workspace isolation, revisions, idempotency, outbox batch replay, audit redaction, snapshot preservation, and Supabase repeat import;
- responsive/dismissible browser capture at 320/360/390/430 px;
- Android forced compile, 8 unit tests, lint, debug/release APK, and release AAB;
- Apple source/project/workflow readiness and six declared XCTest methods;
- checksum-verified offline RoomFlow release assets and native preparation.
- two byte-identical v4.7.0 Pterodactyl builds, 203 packaged runtime files, internal hashes, and 11/11 portable packaged smoke programs.

## Remaining release gates

- Android Depth/guided and Apple RoomPlan/ARKit physical-device acceptance;
- clean install, upgrade, restart, staging HTTPS, backup, and restore;
- current container critical/high advisory scan;
- release signing/store credentials and explicit release approval;
- production deployment approval.

The v4.7.0 Pterodactyl files are deployable test artifacts; Android packages and the Apple simulator package are pre-signing artifacts. Device, staging, signing/store, advisory, backup/restore, and production acceptance are not claimed.

## Pterodactyl launcher repair — 2026-08-18

The first observed Wings startup stopped before Supervisor with `Could not install the integrated RoomFlow section editor`. The v4.7.0 runtime already contained the editor under its new low-training label; the launcher alone still asserted the retired pre-capture heading. The corrected same-release launcher checks the stable `fm-rf-estimate-scope` element. The runtime ZIP remains byte-identical, while the launcher and egg receive new checksums. Package verification now validates all 87 fixed overlay preflight markers against the exact tracked source before release.

## GitHub publication and remote build evidence

- The complete readable source was published to `TheNINJALLO/floodman-business-suite-aio` over authenticated HTTPS. The legacy unrelated repository history is retained as a merge parent; no force push was used and the legacy `floodman-source.zip` is not present in the current tree.
- Android workflow run `32197176293` passed and uploaded artifact `9346411488` (`sha256:f99d289071b2a1880d979139c3ab681f0b75e2d9a68d8d3ca3d9bd3e4aa4b382`) containing the debug APK, unsigned release APK, release AAB, test/lint reports, and package checksums.
- Apple simulator workflow run `32197870130` passed on macOS 26/Xcode 26.6 after the plist executable contract was repaired. All 6 capture tests passed, and artifact `9346645878` has digest `sha256:4e135c2929c1a08cebca809e913ece03863baf75ab1d53b9b8eb082caac5a2ef`.
- Server-image workflow run `32197176318` passed and published `ghcr.io/theninjallo/floodman-operations:4.7.0` at digest `sha256:f1dc722dc9326b6642bc1d981186ec87dce34de1d73c02efcca267aa7c5f75e6`.
- Source-verification runs `32197176330` and `32197870225` passed on Linux. Physical devices, signing/TestFlight/store upload, live staging, backup/restore, advisory scanning, and production deployment remain open safety gates.
