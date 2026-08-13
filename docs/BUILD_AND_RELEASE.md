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

The v4.6.7 base is fixed in both the Dockerfile and `vendor/UPSTREAMS.lock.json` as:

```text
ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5
```

Build the reviewed path with:

```bash
python3 scripts/verify_container_inputs.py
docker build --pull --no-cache -f containers/derivative/Dockerfile -t floodman-operations:4.6.7 .
```

The Docker context is deny-by-default. It includes the two active Dockerfiles and reviewed `server/` source while excluding environment files, Office state, customer CSVs, databases, uploads, logs, backups, runtime volumes, and prepared RoomFlow checkouts. Each service install uses its committed file under `server/requirements/constraints/`.

Advantages:

- minimal system-runtime change;
- easier comparison to the existing node;
- quicker rollback;
- lower chance of Node/PostgreSQL/Documenso ABI surprises.

### Complete AIO image

Use `containers/base-aio/Dockerfile` when the derivative image is stable. It reconstructs the AIO from upstream images and this repository's Floodman source.

The Gauzy API/web, Documenso, and Mailpit sources are also fixed by registry digest in the Dockerfile and upstream lock. Before release:

- run a clean build without layer cache;
- inspect the generated SBOM and obtain a completed critical/high advisory report (BLK-008 is currently open);
- test startup, restart and restore;
- verify required license notices.

The server-image workflow is fixed to reviewed action commits and publishes v4.6.7 plus commit-specific tags. Its build evidence contains the registry digest and SHA-256 values for the Docker context policy, derivative Dockerfile, server manifest, and upstream lock. Publishing is a release action and does not replace staging acceptance.

## Runtime overlay release

The Pterodactyl workflow supports a cumulative runtime ZIP plus `mobile-start.sh`. Current installable/upload artifacts live in `deployment/releases/` and are regenerated from reviewed tracked source with:

```bash
python3 scripts/package_pterodactyl_release.py
python3 scripts/verify_pterodactyl_release.py
```

The packager produces a stable ZIP, an internal source manifest, synchronized launcher, matched egg installer, and deployment `SHA256SUMS`. The exact handoff-era v4.6.7 artifacts retained in `release-artifacts/` are immutable comparison/rollback provenance and are not silently overwritten.

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
