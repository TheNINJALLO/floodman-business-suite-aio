# Android 0.4.0-alpha01 release notes

Build 13 pairs with Floodman Operations server 4.7.0 while retaining Mobile API `0.3.0-alpha11` compatibility and the unchanged minimum Android client floor.

## Added

- real ARCore room-corner capture with optional Depth and guided hit-test fallback;
- tracking, confidence, segment length, closure distance, ceiling-height, undo/reset, haptic, optional sound, and discard controls;
- suite-owned schema-v2 review/correction workflow with openings, affected areas, and derived quantities;
- bounded atomic offline capture outbox with stable operation IDs and revision conflict handling;
- network-independent, checksum-verified assets from RoomFlow commit `1f97817a52b916875e50cc6380c0d284072b8ce8`.

Raw camera video/images, depth maps, and point clouds are not stored or uploaded. The debug APK is locally signed for testing. Release APK/AAB files remain unsigned pending the production signing gate.
