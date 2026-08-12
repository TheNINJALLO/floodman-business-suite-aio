# Source inventory

## Editable current source

- `server/`: Floodman server v4.6.7 custom source
- `apps/android/`: Android 0.3.0-alpha11
- `apps/ios/`: iOS 0.1.0-alpha02
- `provenance/base-aio-v3.1.1/`: original AIO source and provenance
- `containers/`: current complete and derivative image builds
- `launcher/`: current launcher source

## External pinned source

- RoomFlow repository and commit are recorded under `vendor/roomflow/`.
- Gauzy, Documenso, Mailpit, Square, Tailscale, Apple, and Google components remain external.

## Generated inventories

- `docs/generated/SOURCE_MANIFEST.csv`
- `docs/generated/SOURCE_STATS.json`
- `docs/generated/API_ROUTE_INVENTORY.csv`
- `docs/generated/ENVIRONMENT_VARIABLES.csv`

## Exclusions

No live customer export, server database, production secret, logs, screenshots, signing records, or payment records are included.
