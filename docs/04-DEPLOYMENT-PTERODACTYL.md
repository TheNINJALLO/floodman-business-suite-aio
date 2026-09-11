# Pterodactyl deployment

## Current deployment inputs

```text
Image: ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5
Egg: deployment/pterodactyl/egg-floodman-operations-mobile-v4.7.3.json
Launcher: deployment/releases/mobile-start-v4.7.3.sh
Runtime: deployment/releases/floodman-operations-runtime-v4.7.3.zip
Startup: bash ./mobile-start.sh
Time zone: America/Detroit
```

The v4.7.3 egg installs the matched launcher and downloads the missing runtime ZIP from immutable GitHub commit `0f9bc8553d776270267d7f2b7df6f857f6011bfe`, verifying SHA-256 before moving it into `/home/container`. An existing matching ZIP is retained; a mismatch stops installation without overwriting the file. The package simplifies the daily Business Suite, reduces page clutter, and makes Properties strictly customer-scoped while retaining the complete v4.7.2 call-intake, team, and notification feature set. All v4.7.2 artifacts remain frozen rollback evidence.

Current deployable SHA-256 values:

```text
f72e0894ddeb90665d04de878a59502b2d4ab81863f00c0409bbe46acbdd0839  floodman-operations-runtime-v4.7.3.zip
511a87e9b771ef733c6937000db577a18c5313438495533db5fcb6add2855124  mobile-start-v4.7.3.sh
a836789d63fd7d0c1be742e4ae1a28c9d470f3e568a79e9b2d8b89aa1143923e  egg-floodman-operations-mobile-v4.7.3.json
```

The current launcher retains the 2026-08-18 startup-preflight repair and verifies every fixed `$overlay_root` assertion against the exact source packaged in the ZIP. Do not combine a launcher, runtime, or egg from different version rows.

Before a fresh start, set real company/Owner values, replace the Owner password placeholder, assign ports 9000 through 9004, and configure the six `https://` URL fields for `oninetwork.com`. The external proxy must protect staff, signing administration, API documentation, and Engineering routes. No overlay-network key is required.

To reproduce these artifacts from the approved v4.7.3 source:

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

Do not bake live customer data, PostgreSQL files, retired network-overlay state, payment credentials, or signing records into the image.

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
