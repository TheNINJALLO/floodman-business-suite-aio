# Source contents and provenance

## Active current source

- `server/`: custom Floodman server v4.7.2 release source.
- `apps/android/`: Android 0.4.0-alpha01.
- `apps/ios/`: Apple 0.1.0-alpha03.
- `launcher/`: current Pterodactyl launcher.
- `containers/`: source-oriented image builds.
- `deployment/`: environment and hosting examples.
- `.github/workflows/`: direct monorepo CI.

## External/pinned source

RoomFlow is not duplicated. Fetch its exact pinned commit using `scripts/fetch-roomflow.sh`.

Gauzy and Documenso source repositories are not copied. The AIO Dockerfile composes upstream images. This keeps provenance and licensing boundaries visible but means a fully offline build needs separately mirrored upstream images/source.

## Historical/provenance material

`provenance/` contains:

- the original Android and Apple release workflows;
- latest release notes and validation reports;
- the historical v3.1.1 AIO source package and Dockerfile;
- third-party notices;
- older Pterodactyl build documentation.

`release-artifacts/` contains the exact latest packaged runtime/source ZIPs used before the monorepo handoff. These are immutable comparison/rollback material, not editable source.

## Safe reference files

`reference/` includes the approved estimate and invoice PDF examples and a blank/synthetic customer import template. Live business records are excluded.
