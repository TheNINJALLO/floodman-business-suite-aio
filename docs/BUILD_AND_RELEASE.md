# Build and release

## Source verification

```bash
python3 scripts/generate_inventory.py
python3 scripts/generate_source_manifests.py
python3 scripts/verify_repo.py
python3 scripts/generate_checksums.py
```

`verify_repo.py` performs static Python, JSON, XML, plist, shell and JavaScript checks; verifies checked-in manifests; scans for several high-risk secret formats; and validates version-contract strings. It is not a replacement for platform builds or live service tests.

## Server image options

### Derivative image

Use `containers/derivative/Dockerfile` first. It builds the latest custom Floodman layer over the existing AIO base image used during Pterodactyl testing.

The v4.7.1 derivative continues to use the immutable reviewed base fixed in both the Dockerfile and `vendor/UPSTREAMS.lock.json` as:

```text
ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5
```

Build the reviewed path with:

```bash
python3 scripts/verify_container_inputs.py
docker build --pull --no-cache -f containers/derivative/Dockerfile -t floodman-operations:4.7.1 .
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

The server-image workflow is fixed to reviewed action commits and is configured to publish v4.7.3 plus commit-specific tags after an explicitly authorized main-branch update. Its build evidence contains the registry digest and SHA-256 values for the Docker context policy, derivative Dockerfile, server manifest, and upstream lock. A feature-branch push or draft pull request does not publish this image, and image publication does not replace staging acceptance.

## Runtime overlay release

The Pterodactyl workflow supports a cumulative runtime ZIP plus `mobile-start.sh`. Current installable/upload artifacts live in `deployment/releases/` and are regenerated from reviewed tracked source with:

```bash
python3 scripts/package_pterodactyl_release.py
python3 scripts/verify_pterodactyl_release.py
```

The packager produces a stable ZIP, an internal source manifest, synchronized launcher, matched egg installer, and deployment `SHA256SUMS`. The exact handoff-era v4.6.7 artifacts retained in `release-artifacts/` are immutable comparison/rollback provenance and are not silently overwritten.

The 2026-08-28 WEB-007 request additionally authorizes a same-identity v4.7.1 package for a **new** Pterodactyl server. Its source/runtime distinction and the previously published v4.7.1 hashes are recorded in `docs/UI-LAYOUT-HARDENING.md` and `deployment/releases/SHA256SUMS-v4.7.1-published-20260821`. Build the operator handoff only after the ordinary packager/verifier passes:

```bash
python3 scripts/package_fresh_server_handoff.py
```

That deterministic outer ZIP contains `mobile-start.sh`, the exact runtime filename, the egg, the setup guide, and its own component checksums. It does not authorize an in-place production update.

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

The build verifies `server/roomflow/release-assets/SHA256SUMS` and prepares the exact-pin local app assets without a network checkout. `scripts/package_roomflow_release_assets.py` is used only after an approved pin/source review; ordinary builds use `scripts/verify_roomflow_release_assets.py`. Required repository variables:

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

## RoomFlow Capture v4.7.0 boundary

The user's 2026-08-18 scoped exception authorizes distinct local web/Pterodactyl v4.7.0 and Android 0.4.0-alpha01 artifacts for testing. It does not authorize production deployment, live data changes, signing/store upload, or claims for the unavailable Xcode, physical-device, staging, container, clean install/upgrade/restart, or backup/restore gates. Never overwrite the frozen v4.6.10 artifact with v4.7.0 contents.

## Pricing and customer communications v4.7.1 boundary

The user's 2026-08-21 release approval authorizes the distinct local v4.7.1 server/web/Pterodactyl artifacts, release commit, feature-branch publication, and draft pull request. Android, iOS, Mobile API, minimum-client, and RoomFlow-pin identities remain unchanged. The exception does not authorize a production deployment, live provider/data access, container-image publication, signing/store upload, or claims for staging, devices, backup/restore, or advisory scanning. Never overwrite the frozen v4.7.0 artifacts with v4.7.1 bytes.

## Business Suite usability v4.7.3 boundary

The user's 2026-09-10 panel-deployment request authorizes a distinct v4.7.3 server/web/Pterodactyl release and deployment to the intended Floodman server after a complete backup. The release simplifies the daily workspace and enforces customer-first property filtering while retaining Mobile API `0.3.0-alpha11`, Android `0.4.0-alpha01`, iOS `0.1.0-alpha03`, minimum clients, and the exact RoomFlow pin. Preserve all v4.7.2 files as rollback artifacts and use the v4.7.3 runtime, launcher, egg, and checksum row as one matched set.

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
