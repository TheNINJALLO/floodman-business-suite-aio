# Pterodactyl deployment

The live test deployment uses one Pterodactyl server allocation with Floodman's all-in-one image, a cumulative runtime overlay ZIP, and `mobile-start.sh`.

## Current matched release

```text
Server:  Floodman Operations 4.7.1
Android local release: 0.4.0-alpha01 / build 13
Apple source candidate: 0.1.0-alpha03
```

The current upload files in `deployment/releases/` are the user-authorized WEB-007 fresh-server build of v4.7.1. They retain the server identity because this is a new-server handoff, not an in-place version update. The originally published 2026-08-21 v4.7.1 hashes are preserved in `SHA256SUMS-v4.7.1-published-20260821` and release commit `ca9cd35`; do not mix those bytes with the current runtime checksum. The frozen v4.7.0 runtime and launcher remain beside them as rollback evidence.

## Startup

```bash
bash ./mobile-start.sh
```

Import `egg-floodman-operations-mobile-v4.7.1.json`, then upload the two current files from `deployment/releases/` to `/home/container`:

```text
mobile-start-v4.7.1.sh -> mobile-start.sh
floodman-operations-runtime-v4.7.1.zip (do not extract)
```

The egg installs the same current launcher automatically on a fresh server. The ZIP remains a separate upload so its SHA-256 can be verified before startup. Set a non-placeholder Owner password and create `config/tailscale-auth-key.txt` with a one-off non-ephemeral auth key before the first start.

For a new node, use `FRESH-SERVER-SETUP-v4.7.1-WEB007.md` or extract `floodman-operations-new-server-v4.7.1-web007-20260828.zip`. The outer handoff already contains the launcher named `mobile-start.sh`, the exact runtime filename, the egg, setup guide, and matched component checksums.

### 2026-08-18 launcher repair

If startup stops at `ERROR: Could not install the integrated RoomFlow section editor.`, the runtime ZIP is not the problem. Keep the existing `floodman-operations-runtime-v4.7.0.zip`, upload the corrected `mobile-start-v4.7.0.sh` as `mobile-start.sh`, and restart. Its SHA-256 is `38687babc4bc418d99bddca7a72760e430d724d3fe1d1b382ed71229d3c0c6b4`. The failed log also showed the server pulling AIO `3.2.0`; the reviewed egg specifies the pinned `3.2.2` digest, so reconcile that image setting during a backed-up maintenance window.

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

The v4.7.1 egg, launcher, ZIP, internal manifest, and deployment checksums are regenerated together by `scripts/package_pterodactyl_release.py` and checked by `scripts/verify_pterodactyl_release.py`. The v4.7.0 files, `release-artifacts/`, and Git history are rollback provenance, not the current upload source.
