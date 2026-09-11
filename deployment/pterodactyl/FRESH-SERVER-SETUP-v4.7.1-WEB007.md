# Floodman Operations fresh Pterodactyl setup

This handoff installs Floodman Operations server 4.7.1 with Mobile API 0.3.0-alpha11 and the WEB-007 responsive-interface refresh on a **new** Pterodactyl server. It does not migrate an existing live database and does not change Android, Apple, or RoomFlow identities.

## Files in the handoff

Upload/import only the matched files from the WEB-007 handoff:

```text
egg-floodman-operations-mobile-v4.7.1.json     import into Pterodactyl as the egg
floodman-operations-runtime-v4.7.1.zip        upload unchanged to /home/container
mobile-start.sh                               installed by the egg; upload this copy only if the panel did not run the install script
SHA256SUMS                                    verify the three files above before first start
```

Do not extract the runtime ZIP. Do not upload a historical 4.7.1 runtime with the WEB-007 checksums. The launcher rejects an absent, damaged, or mismatched runtime before touching persistent application state.

## 1. Import the egg

1. In the Pterodactyl admin panel, open **Nests** and choose the nest that will hold Floodman.
2. Choose **Import Egg** and select `egg-floodman-operations-mobile-v4.7.1.json`.
3. Confirm the imported image is exactly:

   ```text
   ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5
   ```

4. Leave the startup command as `bash ./mobile-start.sh`.

## 2. Create the server and allocations

Assign enough memory for the AIO services; the egg defaults the Floodman Core Node heap to 4096 MB. Create these allocations on the same node:

```text
9000  primary allocation: Hub, private Office/PWA, Full ERP and narrow public gateway
9001  Documenso signing
9002  Mailpit test mail
9003  Engineering Sandbox
9004  Floodman Mobile API
```

Do not intentionally expose staff Office, Full ERP, signing administration, Mailpit, Engineering, or database services to the public internet. Staff access is private through Tailscale by default. A future public customer/signing/payment hostname must use a reviewed HTTPS reverse proxy that exposes only the narrow public paths.

## 3. Set the Startup values

Replace every example identity before first start:

- Company Name
- Owner First Name
- Owner Last Name
- Owner Email
- Owner Password: at least 12 characters and not `REPLACE_ME_12345!`
- Time Zone: keep `America/Detroit`
- Tailscale Hostname: a unique DNS-safe name such as `floodman-operations`

Keep the 9001–9004 port values matched to the allocations. Leave both AI providers on `deterministic` unless a separately reviewed provider setup is authorized. Do not paste an OpenAI key or any other secret into logs or support messages.

## 4. Upload and verify the runtime

1. Let the egg installation finish. It creates the persistent `data/`, `config/`, `backups/`, `diagnostics/`, and `logs/` directories and installs `mobile-start.sh`.
2. Upload `floodman-operations-runtime-v4.7.1.zip` to the server root so its full path is:

   ```text
   /home/container/floodman-operations-runtime-v4.7.1.zip
   ```

3. If `/home/container/mobile-start.sh` is missing, upload the handoff copy with that exact name. Do not rename the runtime ZIP.
4. Compare the uploaded files with `SHA256SUMS`. Current WEB-007 component hashes are:

   ```text
   2775227e411ae5ecbc80d9eee88509864971d5988f1510af77e4fdc9bce9b989  floodman-operations-runtime-v4.7.1.zip
   bc3adee529c84e79ab1db03ff169b89e40339e22970eea4873e4650768a3d0fd  mobile-start.sh
   d1e8b08e7793f8d659c310362795a17cb89040ea3f27f58762e207c1e1c4931f  egg-floodman-operations-mobile-v4.7.1.json
   ```

## 5. Add the Tailscale key

Create `/home/container/config/tailscale-auth-key.txt` containing one newly generated, one-off, non-ephemeral Tailscale auth key. Treat this file as a secret. Never commit it, include it in a backup shared with support, or paste it into console output.

The launcher deletes the key file after successful enrollment. Existing Tailscale state is retained under persistent server storage for later restarts.

## 6. First start

Start the server and leave the console attached. A first boot can take a substantial amount of time while databases and applications initialize. The successful terminal marker is:

```text
FLOODMAN_SUITE_READY
```

If startup stops, copy only the non-secret error lines. Do not delete `data/`, `config/`, database directories, or Tailscale state as a repair step.

## 7. Acceptance checks

From the private Tailscale address:

1. Open the Hub on port 9000 and sign in with the Owner email/password.
2. Open Desktop Workspace, Mobile Workspace, Full ERP, and RoomFlow; RoomFlow must not request a separate account.
3. Open Settings & Setup and confirm cards, menus, and buttons are not obscured at phone and desktop widths.
4. Check `/health/live`, `/office-health/live`, and `/mobile-api/v1/health` through the intended gateway.
5. Create only fictional test records. Verify one estimate PDF starts with `%PDF-` and reports `application/pdf`.
6. Stop and restart once. Confirm `FLOODMAN_SUITE_READY` returns and the fictional record remains.
7. Create the first Pterodactyl backup after the clean-install/restart checks, then test restore only on an approved isolated server.

Live payment, signing, email/SMS, Xactimate, Supabase, customer, backup/restore, and production acceptance are not included in the local build evidence.

## Rollback and support boundary

On a brand-new server, stop after a failed first boot and preserve the console plus `diagnostics/`. Do not copy an older launcher over this runtime unless it is paired with its own checksum-addressed runtime. Never repair startup by deleting persistent databases.

Created by Josh Aldrich.
