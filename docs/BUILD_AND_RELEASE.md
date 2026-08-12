# Build and release

## Source verification

```bash
python3 scripts/generate_inventory.py
python3 scripts/verify_repo.py
python3 scripts/generate_checksums.py
```

`verify_repo.py` performs static Python, JSON, XML, plist, shell and JavaScript checks; verifies checked-in manifests; scans for several high-risk secret formats; and validates version-contract strings. It is not a replacement for platform builds or live service tests.

## Server image options

### Derivative image

Use `containers/derivative/Dockerfile` first. It builds the latest custom Floodman layer over the existing AIO base image used during Pterodactyl testing.

Advantages:

- minimal system-runtime change;
- easier comparison to the existing node;
- quicker rollback;
- lower chance of Node/PostgreSQL/Documenso ABI surprises.

### Complete AIO image

Use `containers/base-aio/Dockerfile` when the derivative image is stable. It reconstructs the AIO from upstream images and this repository's Floodman source.

Before release:

- pin upstream images by digest;
- run a clean build without layer cache;
- inspect SBOM and vulnerabilities;
- test startup, restart and restore;
- verify required license notices.

## Runtime overlay release

The original Pterodactyl workflow also supports a cumulative runtime ZIP plus `mobile-start.sh`. The exact v4.6.7 artifacts are retained in `release-artifacts/` for reproducibility and rollback comparison.

New development should prefer versioned container images from source, with overlays reserved for emergency patches.

## Android

Build prerequisites:

```text
JDK 17
Android SDK 36
Build Tools 36
Gradle 8.13
AGP 8.13.2
Kotlin 2.3.20
```

The build fetches the pinned RoomFlow repository and prepares local app assets before compiling. Required repository variables:

```text
FLOODMAN_API_BASE_URL
SQUARE_APPLICATION_ID
```

Release signing should use a stable private keystore stored as a CI secret, not an ephemeral debug key.

## Apple

The simulator build uses XcodeGen and Xcode on a macOS runner. TestFlight requires:

```text
APPLE_TEAM_ID
IOS_DISTRIBUTION_CERTIFICATE_BASE64
IOS_DISTRIBUTION_CERTIFICATE_PASSWORD
IOS_PROVISIONING_PROFILE_BASE64
APP_STORE_CONNECT_KEY_ID
APP_STORE_CONNECT_ISSUER_ID
APP_STORE_CONNECT_PRIVATE_KEY_BASE64
```

Run the unsigned simulator build first. Only enable TestFlight after the simulator build and native acceptance tests are green.

## Version synchronization

A release must update:

- root `VERSION`/handoff metadata as appropriate;
- `server/VERSION`;
- `server/overlay.json`;
- health/config API responses;
- Android `VERSION`, version name/code and server requirement;
- Apple `VERSION`, marketing/build numbers and server requirement;
- workflows, docs and artifact names;
- source manifests and SHA-256 lists.

## Acceptance gates

### Server

- source/static checks;
- image build;
- clean startup;
- restart without stale PostgreSQL loops;
- health/readiness;
- desktop/mobile/Full ERP routes;
- import and search;
- estimate/invoice PDFs;
- signing and customer files;
- Square sandbox payment;
- RoomFlow import/sync/layout;
- backup/restore.

### Android

- compile, unit tests, lint, APK/AAB;
- clean install and upgrade behavior;
- login/device enrollment;
- every primary module;
- RoomFlow select/create/sync;
- real PDF open/content validation;
- offline/reconnect behavior;
- theme and rotation/tablet checks.

### Apple

- Swift/Xcode build;
- iPhone and iPad layout;
- login/session/biometrics;
- parity checklist;
- RoomFlow local server and sync;
- TestFlight installation;
- push/signing capabilities where configured.
