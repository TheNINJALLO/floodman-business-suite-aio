# iOS 0.1.0-alpha03 build readiness

Evidence date: 2026-08-14

This candidate advances build metadata and aligns native RoomFlow customer/property lookup with the selected Floodman v4.6.9 company workspace. It retains HTTPS-only Mobile API access, device-bound Keychain storage, rotating refresh-token coordination, strict PDF validation, cancellable overlays, and loopback-only RoomFlow navigation/media permissions.

The prepared RoomFlow bundle must carry Floodman `4.6.9`, attribution `Created by Josh Aldrich`, time zone `America/Detroit`, and exact commit `1f97817a52b916875e50cc6380c0d284072b8ce8`.

Local Windows verification covers source, plist, assets, project configuration, bridge syntax, pinned RoomFlow preparation, and workflow ordering. Actual unsigned simulator compilation remains blocked until `.github/workflows/build-ios-simulator.yml` runs on macOS 26/Xcode 26. TestFlight signing/upload is not authorized by this candidate update.

## Recorded local result

- `scripts/verify_ios_readiness.py` passed 7 Swift files, all 18 icon slots, alpha03/build 3 identity, HTTPS/capability/PDF/Keychain contracts, workspace-aware RoomFlow queries, and the simulator/TestFlight workflow guards.
- The plist and all native workflow/project YAML parsed successfully.
- Both native bridge scripts passed `node --check`; both preparation scripts passed Git Bash syntax.
- `scripts/verify_roomflow_pin.py` verified the clean 1,032-file source checkout at the exact pin and agreement among server, Android, iOS, schema/RLS, and importer contracts.
- The freshly prepared iOS bundle passed native local-dependency validation and carries Floodman 4.6.9 metadata plus bridge cache version 3.
- All 10 source server smoke programs and all 9 portable runtime smoke programs passed after the workspace-boundary change.

Outcome: Windows-available source/workflow readiness is `PASS`. Unsigned Xcode simulator compilation remains `BLOCKED` by BLK-004; no compiler, signing, archive, TestFlight, or device pass is claimed.
