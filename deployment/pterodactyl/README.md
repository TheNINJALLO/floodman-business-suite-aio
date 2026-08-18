# Pterodactyl deployment

The live test deployment uses one Pterodactyl server allocation with Floodman's all-in-one image, a cumulative runtime overlay ZIP, and `mobile-start.sh`.

## Current matched release

```text
Server:  Floodman Operations 4.7.0
Android local release: 0.4.0-alpha01 / build 13
Apple source candidate: 0.1.0-alpha03
```

The files in `deployment/releases/` are the distinct v4.7.0 RoomFlow Capture release. They do not overwrite the v4.6.10 identity.

## Startup

```bash
bash ./mobile-start.sh
```

Import `egg-floodman-operations-mobile-v4.7.0.json`, then upload the two current files from `deployment/releases/` to `/home/container`:

```text
mobile-start-v4.7.0.sh -> mobile-start.sh
floodman-operations-runtime-v4.7.0.zip (do not extract)
```

The egg installs the same current launcher automatically on a fresh server. The ZIP remains a separate upload so its SHA-256 can be verified before startup. Set a non-placeholder Owner password and create `config/tailscale-auth-key.txt` with a one-off non-ephemeral auth key before the first start.

## Allocations

```text
9000 Hub / private PWA / Full ERP gateway
9001 signing
9002 test mail
9003 engineering and local lab
9004 Floodman API
```

## Upgrade discipline

1. Create a Pterodactyl backup.
2. Stop and wait for Offline.
3. Preserve the current launcher with a versioned backup name.
4. Upload the new runtime ZIP and launcher without extracting the ZIP.
5. Rename the new launcher to `mobile-start.sh`.
6. Start and wait for `FLOODMAN_SUITE_READY`.
7. Verify `/mobile-api/v1/health`, `/office-health/live`, private desktop/mobile routes, signing, and one PDF.
8. Roll back the launcher and runtime only if the matching release fails. Never delete data directories as a repair shortcut.

The v4.7.0 egg, launcher, ZIP, internal manifest, and deployment checksums are regenerated together by `scripts/package_pterodactyl_release.py` and checked by `scripts/verify_pterodactyl_release.py`. Historical copies under `release-artifacts/` and Git history are rollback provenance, not the current upload source.
