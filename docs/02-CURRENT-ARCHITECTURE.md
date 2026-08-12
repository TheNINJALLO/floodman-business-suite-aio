# Current architecture

## Logical components

```text
Users and devices
  |-- Private browser/PWA over Tailscale
  |-- Android over public HTTPS Mobile API
  |-- iPhone/iPad over public HTTPS Mobile API
  |-- Customers over public tokenized links

Pterodactyl AIO container
  |-- Nginx Floodman Hub and gateway
  |-- Floodman Office FastAPI service
  |-- Gauzy API and Gauzy browser
  |-- Documenso signing runtime
  |-- Embedded PostgreSQL
  |-- Mailpit
  |-- Orchestrator API and worker
  |-- Messaging AI
  |-- Competitor Intelligence API and scheduler
  |-- Local Lab / engineering support service
  |-- RoomFlow web assets and integration bridge
  |-- Supervisor process manager
```

## Internal ports

| Port | Purpose |
|---:|---|
| 8700 | Floodman Office loopback service |
| 9000 | Floodman Hub, Office/PWA routing, guarded Full ERP |
| 9001 | Documenso/signing |
| 9002 | Mailpit test mail |
| 9003 | Local Lab and engineering surface |
| 9004 | Floodman API and orchestrator-facing routes |
| 9010 | Loopback public gateway used by Funnel |

## Private Tailscale ports

| HTTPS port | Internal target |
|---:|---|
| 8443 | 9000 |
| 8444 | 9001 |
| 8445 | 9004 |
| 8446 | 9002 |
| 8447 | 9003 |

## Public gateway

The test public gateway is intentionally narrow:

```text
/mobile-api/* -> Floodman native-app API
/customer/*   -> tokenized customer pages, documents, and payments
/              -> signing service
```

The staff PWA, Full ERP, engineering tools, Mailpit, and databases are not intended to be public.

## Server services

### Floodman Office

Primary custom operations application. It contains the web UI, customer portal, Mobile API, authentication, customer import, estimate/invoice PDFs, project plans, RoomFlow assets/import, provider adapters, scheduling, documents, payments, and the operational store.

### Orchestrator

Coordinates internal jobs, synchronization, messaging, webhooks, and estimate/job workflows. It has both API and worker processes.

### Messaging AI

Provides deterministic or configured provider-backed message drafting. Customer messaging must remain approval-controlled.

### Competitor Intelligence

Stores targets, snapshots, reports, scan results, and scheduled scan work. External TLS and site failures should be reported per target rather than crash the suite.

### Local Lab

Provides engineering/test functions, local provider mocks, import helpers, and support utilities.

## UI surfaces

| Route | Surface |
|---|---|
| `/workspace` | Adaptive PWA launcher |
| `/office/desktop?desktop=1` | Desktop Floodman Office |
| `/office/mobile?mobile=1` | Phone/tablet Floodman Office |
| `/full-erp` | Authentication-aware full Gauzy ERP |
| `/floodman-status.html` | Runtime diagnostics |
| `/roomflow/` | RoomFlow workspace in the web suite |
| `/mobile-api/v1/*` | Native app API |
| `/customer/*` | Public tokenized customer routes |

## Build model

Two server image paths are included:

1. `containers/derivative/Dockerfile` layers the current source onto the existing Floodman AIO base image. Use this first.
2. `containers/base-aio/Dockerfile` rebuilds the complete AIO image by composing Gauzy, Documenso, Mailpit, PostgreSQL, and Floodman custom source.

The complete AIO Dockerfile currently references mutable upstream image tags in places. Pin them by immutable digest before production.
