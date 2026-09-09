# Deployment guide

## Current Pterodactyl test model

The server currently runs as a single Pterodactyl allocation. This is a controlled internal test architecture, not the recommended final dedicated-server topology.

### Startup sequence

`mobile-start.sh` prepares the selected cumulative runtime, persistent directories, permissions, externally proxied Nginx/Supervisor configuration, upstream services, health checks and final readiness marker. It does not download or launch Tailscale.

The current files in `deployment/releases/` provide the distinct v4.7.2 runtime and launcher. The matched v4.7.2 egg installs `mobile-start.sh` and downloads the missing runtime from an immutable GitHub commit with SHA-256 verification. Existing servers can use the backed-up procedure in `deployment/pterodactyl/UPDATE-v4.7.2.md`. All v4.7.1 files remain rollback evidence. A package result alone is not live installation or acceptance evidence.

Expected terminal marker:

```text
FLOODMAN_SUITE_READY
```

### Required verification URLs

Through the external HTTPS proxy with staff access granted:

```text
https://floodman.oninetwork.com/workspace?workspace=auto
https://floodman.oninetwork.com/office/desktop?desktop=1
https://floodman.oninetwork.com/office/mobile?mobile=1
https://floodman.oninetwork.com/full-erp?target=login
https://floodman.oninetwork.com/roomflow/
https://floodman.oninetwork.com/office-health/live
https://floodman.oninetwork.com/floodman-status.html
```

`/roomflow/` and `/office/*` use the main ERP login. On first access while signed out, Floodman records the local return target, opens the genuine ERP login, establishes the narrower Office/RoomFlow cookie after Gauzy accepts the credentials, and returns to the requested module. `/login/local` is reserved for installation-owner recovery.

Public native API test:

```text
https://api.oninetwork.com/mobile-api/v1/health
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
- DNS, TLS, reverse-proxy routing, and access-policy configuration;
- payment/webhook callback URLs;
- mobile API origin.

## Main website and DNS

The main marketing website can remain on PebbleHost/cPanel. The operations system should use dedicated application subdomains once proper reverse-proxy/TLS control exists, for example:

```text
floodman.oninetwork.com
api.oninetwork.com
sign.oninetwork.com
lab.oninetwork.com
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
