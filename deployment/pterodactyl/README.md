# Pterodactyl deployment

The live test deployment uses one Pterodactyl server allocation with Floodman's all-in-one image, a cumulative runtime overlay ZIP, and `mobile-start.sh`.

## Current matched release

```text
Server:  Floodman Operations 4.6.7
Android: 0.3.0-alpha11
Apple:   0.1.0-alpha02 development source
```

## Startup

```bash
bash ./mobile-start.sh
```

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

The included egg is historical and should be reviewed before reuse. The current system evolved beyond that egg through cumulative launchers and runtime overlays.
