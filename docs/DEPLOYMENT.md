# Deployment guide

## Current Pterodactyl test model

The server currently runs as a single Pterodactyl allocation. This is a controlled internal test architecture, not the recommended final dedicated-server topology.

### Startup sequence

`mobile-start.sh` prepares the selected cumulative runtime, persistent directories, permissions, Tailscale, Nginx/Supervisor configuration, upstream services, health checks and final readiness marker.

The current files in `deployment/releases/` provide the distinct v4.7.1 runtime and launcher. Upload `floodman-operations-runtime-v4.7.1.zip` and `mobile-start-v4.7.1.sh` (renamed to `mobile-start.sh` on the panel) and use the matched v4.7.1 egg when importing a new Pterodactyl definition. Verify `SHA256SUMS` before upload. The frozen v4.7.0 files remain rollback evidence. This local package result is not a claim that staging install/upgrade/restart, backup/restore, live routes, or production deployment passed.

Expected terminal marker:

```text
FLOODMAN_SUITE_READY
```

### Required verification URLs

Private, while connected to Tailscale:

```text
https://<node>.ts.net:8443/workspace?workspace=auto
https://<node>.ts.net:8443/office/desktop?desktop=1
https://<node>.ts.net:8443/office/mobile?mobile=1
https://<node>.ts.net:8443/full-erp?target=login
https://<node>.ts.net:8443/roomflow/
https://<node>.ts.net:8443/office-health/live
https://<node>.ts.net:8443/floodman-status.html
```

`/roomflow/` and `/office/*` use the main ERP login. On first access while signed out, Floodman records the local return target, opens the genuine ERP login, establishes the narrower Office/RoomFlow cookie after Gauzy accepts the credentials, and returns to the requested module. `/login/local` is reserved for installation-owner recovery.

Public test, with Tailscale off on the client:

```text
https://<node>.ts.net/mobile-api/v1/health
```

Signing/payment links should be tested only with generated tokenized test records.

## Dedicated-server target

Recommended eventual decomposition:

```text
reverse proxy / ingress
  |-- Floodman Hub/PWA
  |-- Floodman Office/Mobile API
  |-- Gauzy API
  |-- Gauzy web
  |-- Documenso
  |-- Orchestrator API/worker/schedulers
  |-- Competitor intelligence
  |-- Messaging AI
  |-- Mail capture only in nonproduction
PostgreSQL with separate databases/roles
object/file storage
central logging and backups
```

Do not move by copying only the container image. Migrate:

- database dumps;
- Office state/uploads/documents/layouts;
- Gauzy files/imports;
- Documenso data;
- external mapping records;
- encryption/signing secrets;
- Tailscale or new DNS/TLS configuration;
- payment/webhook callback URLs;
- mobile API origin.

## Main website and DNS

The main marketing website can remain on PebbleHost/cPanel. The operations system should use dedicated application subdomains once proper reverse-proxy/TLS control exists, for example:

```text
office.floodman.com
api.floodman.com
sign.floodman.com
```

An `.htaccess` redirect can send users to another origin, but it cannot replace a reverse proxy or terminate HTTPS for a different backend port.

## Rollback

A valid rollback includes:

- previous image/runtime checksum;
- previous launcher;
- data backup taken before migration;
- database downgrade/migration plan;
- mobile client compatibility assessment.

Do not roll back application code across an irreversible database migration without restoring or explicitly reversing the data migration.
