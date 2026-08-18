# Apple RoomFlow Capture readiness — unreleased

Evidence date: 2026-08-18

The alpha03 source candidate now contains a real RoomPlan path, a guided ARKit fallback, the shared capture result model, and a private offline-operation outbox. It keeps the existing Floodman login, selected workspace/job, Mobile API, and bundled exact-pin RoomFlow engine.

Windows-available verification passes:

- 11 Swift files and all 18 app-icon slots;
- project, plist, YAML, JavaScript, Python, and local-asset contracts;
- bridge-v2 `{version, sessionId, type, requestId, payload}` validation and 256-KB bound;
- RoomPlan wall graph conversion plus door/window/open-wall parent mapping;
- guided ARKit raycasts, stabilization, LiDAR mesh capability, tracking/relocalization guidance, undo/reset, and lifecycle cleanup;
- schema-v2 geometry/privacy model and atomic file-protected 200-operation outbox;
- six deterministic XCTest methods covering rectangle/privacy output, crossing and short-wall rejection, missing scope, closed/open RoomPlan fixtures, and the bridge envelope;
- checksum-verified network-independent RoomFlow preparation at commit `1f97817a52b916875e50cc6380c0d284072b8ce8`.

The authoritative macOS workflow now generates the project, performs the unsigned simulator build, boots an available iPhone simulator, runs `xcodebuild test`, and publishes both logs and checksums.

Actual Swift/Xcode compilation and execution of those six tests remain blocked by BLK-004 because this host is Windows. LiDAR/RoomPlan and ARKit physical-device acceptance, signing, archive, and TestFlight remain BLK-006/BLK-007. No compiler, simulator, device, signing, or store pass is claimed.
