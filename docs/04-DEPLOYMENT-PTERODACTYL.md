# Pterodactyl deployment

## Current deployment inputs

```text
Image: ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5
Egg: deployment/pterodactyl/egg-floodman-operations-mobile-v4.6.9.json
Launcher: deployment/releases/mobile-start-v4.6.9.sh
Runtime: deployment/releases/floodman-operations-runtime-v4.6.9.zip
Startup: bash ./mobile-start.sh
Time zone: America/Detroit
```

The 2026-08-14 deployment artifacts are regenerated from the verified current source. The egg installs the matched v4.6.9 launcher but does not embed the runtime ZIP: upload the ZIP to `/home/container` without extracting it before the first start. This server-only test package removes the separate RoomFlow account/company blocker. Android and iOS versions are unchanged and their builds were explicitly deferred. The `release-artifacts/` directory is historical rollback provenance and is not the current upload source.

Current deployable SHA-256 values:

```text
4de395a578c08be96e7e330d1e9cee2fef44c855356761556691595871622a2e  floodman-operations-runtime-v4.6.9.zip
01c01658d86b6afc199c03227e75da1ef4c28dda85174d4ee9d380120e7ac6a3  mobile-start-v4.6.9.sh
de57da3ecaf56c9b04acaabdb0fbf22005175eeb76818dfcea8ec40c15f4e79d  egg-floodman-operations-mobile-v4.6.9.json
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
