# Pterodactyl deployment

## Current deployment inputs

```text
Image: ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5
Egg: deployment/pterodactyl/egg-floodman-operations-mobile-v4.7.0.json
Launcher: deployment/releases/mobile-start-v4.7.0.sh
Runtime: deployment/releases/floodman-operations-runtime-v4.7.0.zip
Startup: bash ./mobile-start.sh
Time zone: America/Detroit
```

The 2026-08-18 deployment artifacts are regenerated from the verified current source. The egg installs the matched v4.7.0 launcher but does not embed the runtime ZIP: upload the ZIP to `/home/container` without extracting it before the first start. The package includes suite-owned RoomFlow Capture, unified authentication/workspaces, offline/revision APIs, the stable Supabase importer, and checksum-verified network-independent RoomFlow assets used by Android 0.4.0-alpha01 and future Apple builds. The `release-artifacts/` directory is historical rollback provenance and is not the current upload source.

Current deployable SHA-256 values:

```text
733514138066eab31940c771918dddaf18204c4d26a071daf9a063965f7e967a  floodman-operations-runtime-v4.7.0.zip
f2704055b3d9046b6a403fb886dbdb4cdf3efa769fb4d60a6d50a510dcb17056  mobile-start-v4.7.0.sh
1067346d705862648fc58da7b505213c6c74034fac93db905d56e9ac0f2f8206  egg-floodman-operations-mobile-v4.7.0.json
```

Before a fresh start, set real company/Owner values, replace the Owner password placeholder, assign ports 9000 through 9004, and create `/home/container/config/tailscale-auth-key.txt` with a one-off non-ephemeral Tailscale auth key. The staff system remains private through Tailscale.

To reproduce these artifacts after an approved same-version source repair:

```bash
python scripts/package_pterodactyl_release.py
python scripts/verify_pterodactyl_release.py
```

## Current update procedure

1. Create a full Pterodactyl backup.
2. Stop the server and wait for Offline.
3. Wait at least 20 seconds for processes and PostgreSQL to stop.
4. Rename the current `mobile-start.sh` to a versioned backup.
5. Upload the new runtime ZIP and launcher.
6. Do not extract the runtime ZIP.
7. Rename the new launcher to `mobile-start.sh`.
8. Confirm `bash ./mobile-start.sh` is still the Startup command.
9. Start and wait for `FLOODMAN_SUITE_READY`.
10. Test Office health, Mobile API health, desktop, mobile, Full ERP login, customer portal, signing, one estimate PDF, one invoice PDF, and RoomFlow Save & Sync.

## Persistence

Keep these under persistent Pterodactyl storage:

```text
/home/container/data
/home/container/config
/home/container/logs
/home/container/backups
```

Do not bake live customer data, PostgreSQL files, Tailscale state, payment credentials, or signing records into the image.

## Preferred migration to source-built image

1. Build `containers/derivative/Dockerfile` with the current base image.
2. Tag with an immutable release tag and digest.
3. Deploy to a new staging server, not the live server.
4. Restore a sanitized copy of the data and configuration.
5. Run the full release checklist.
6. Change the production egg/image only after backup and rollback are verified.

## Readiness contract

The launcher should print clear milestones and finish with:

```text
FLOODMAN_SUITE_READY
```

A process staying alive is not enough. Health checks must confirm the Hub, Office, Mobile API, database, and required public/private routes.

## Rollback

- Stop the server.
- Restore the prior `mobile-start.sh`.
- Restore the prior runtime ZIP if the launcher selects releases by filename.
- Restore a Pterodactyl backup only when data was changed and the rollback requires it.
- Start and verify the previous health contract.

Never delete the database volume as a routine rollback step.
