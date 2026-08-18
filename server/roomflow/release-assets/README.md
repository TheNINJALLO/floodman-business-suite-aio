# RoomFlow release assets

This directory is the network-independent RoomFlow packaging input for the Floodman server, Android app, and Apple app. `upstream/` is exported from the exact commit in `vendor/roomflow/PINNED_COMMIT`; `vendor/` contains the approved, version-pinned browser libraries named in `ASSET-SOURCES.json`.

Every file except `SHA256SUMS` is covered by that manifest. Run `python scripts/verify_roomflow_release_assets.py` before preparing any RoomFlow runtime. Do not edit exported upstream files in place or advance the pin without the RoomFlow release gates.
