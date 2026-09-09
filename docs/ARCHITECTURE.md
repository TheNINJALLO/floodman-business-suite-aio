# Architecture

## Logical topology

```text
                         PROTECTED STAFF ACCESS
Approved browser through external HTTPS access policy
        |
        | https://floodman.oninetwork.com
        v
+-----------------------------+
| Floodman Hub / Nginx  :9000 |
| - workspace selector        |
| - desktop/mobile PWA        |
| - Full ERP launcher         |
| - status/health             |
+-----------------------------+
        |                          |                   \ same-origin reverse proxy
        |                            v                     v
Floodman Office :8700      Gauzy web/API :4200/:3000
        |
        +--> RoomFlow local/PWA assets
        +--> custom Office state and files
        +--> Mobile API route handlers

                         PUBLIC NARROW ACCESS
Android / customer browser
        |
        | public HTTPS
        v
api.oninetwork.com through the external HTTPS proxy
        |
        v
API gateway :9004
        |-- /mobile-api/* --> Floodman Office :8700
        |-- /customer/*   --> customer estimates/invoices/payments
        `-- signing root  --> signing service

                         INTERNAL SERVICE BUS
+-----------------+       +------------------+       +-----------------+
| Orchestrator    |<----->| PostgreSQL       |<----->| Competitor Intel|
| jobs/payments   |       | workflow/audit   |       | scans/reports   |
| docs/messages   |       | outbox/AR        |       +-----------------+
+-----------------+       +------------------+
        |                          ^
        v                          |
Gauzy, Documenso, Square, Twilio, messaging AI, Mailpit/local lab
```

## Custom services

### Floodman Office (`server/office-console`)

The primary custom business application. It provides:

- local/Gauzy-linked staff identity;
- customer files, properties, notes, tags and documents;
- imports;
- estimates, invoices, payments and PDFs;
- desktop/mobile PWA workspaces;
- native Mobile API;
- scheduling, tasks, notifications and time clock;
- RoomFlow snapshots, layouts, Supabase migration and workspaces;
- provider integration helpers.

Office currently persists its custom application state in an atomic JSON file plus uploaded documents/layouts on disk.

### Unified browser authentication

The genuine same-origin ERP login is the browser identity entry point for ERP, Office, and integrated RoomFlow. Nginx routes only the ERP login request through Office; Office forwards it to the internal Gauzy API, returns the original Gauzy response to the Angular client, maps the verified user to an Office role, and issues a separate HttpOnly module session. This keeps the ERP token out of Office storage while allowing RoomFlow's Nginx `auth_request` gate to enforce Office permissions. An existing ERP JWT may be exchanged only after Gauzy `/user/me`, tenant, and organization checks. A safe session-storage return marker sends users back to the module they originally requested.

### Orchestrator (`server/orchestrator`)

Coordinates durable workflow state in PostgreSQL:

- estimate/job synchronization;
- document/signature lifecycle;
- Square orders/invoices/payments and webhooks;
- Twilio inbound/status events;
- accounts receivable automation;
- message threads and staff alerts;
- outbox retries, idempotency and audit events;
- customer portal links.

### Messaging AI (`server/messaging-ai`)

Classifies messages and optionally calls an OpenAI-compatible provider. The deterministic provider remains available for controlled testing.

### Competitor Intelligence (`server/competitor-intel`)

Manages targets, safe web retrieval, snapshots, reports, manual runs and scheduled scans.

### Local Lab (`server/local-lab`)

Supplies local mocks and engineering interfaces for Gauzy, Square, Documenso, Twilio, mail and demo lifecycle tests. It is not intended to be public production infrastructure.

## Upstream applications

- **Gauzy**: Full ERP/browser and upstream identity/data integration.
- **Documenso**: document signing.
- **PostgreSQL**: durable orchestrator/workflow database and upstream application databases.
- **Mailpit**: test email capture.
- **Nginx**: same-origin routing and browser gateway.
- **Supervisor**: one-container process management.
- **External HTTPS proxy**: certificates, hostname-to-port routing, HTTPS redirects, and staff access policy.
- **Square**: tokenized card/payment processor.
- **Twilio**: optional messaging transport.

## Ports

| Internal port | Purpose |
|---:|---|
| 9000 | Hub, PWA and Full ERP gateway |
| 9001 | signing |
| 9002 | Mailpit/test mail |
| 9003 | engineering/local lab |
| 9004 | external API gateway and native Mobile API |
| 8700 | internal Floodman Office service |
| 8701 | internal workflow/orchestrator API |
| 3000 | Gauzy API |
| 4200 | Gauzy browser |
| 5432 | embedded PostgreSQL |

## Browser routes

| Route | Intent |
|---|---|
| `/workspace` | automatic desktop/mobile selection |
| `/login` | unified ERP login and requested-module return gateway |
| `/login/local` | explicit installation Owner recovery login |
| `/office/desktop?desktop=1` | dedicated desktop Floodman workspace |
| `/office/mobile?mobile=1` | phone/tablet Floodman workspace |
| `/full-erp` | authentication-aware Gauzy ERP launcher |
| `/floodman-status.html` | Hub and ERP readiness status |
| `/install-app` | PWA installation page |
| `/roomflow/` | RoomFlow workspace |
| `/mobile-api/v1/*` | native application API |

## Native app architecture

Android and Apple are native shells with native navigation, security and operational screens. RoomFlow is the deliberate embedded-web-engine exception because it is a large interactive field/CAD-style application. The native bridge provides:

- current authenticated session;
- selected workspace;
- customer/property context;
- full job bootstrap;
- snapshot sync;
- layout capture;
- estimate/catalog relationships.

The embedded RoomFlow engine must never receive database credentials or service-role keys.

## Release coupling

The native apps and server form a versioned contract. Health/config responses carry API version, minimum client version and capability names. A mobile app should refuse an incompatible server rather than attempt partial operation.

## Incoming AI call vertical slice

The Orchestrator owns the public signed webhook, provider-neutral normalization, event ordering, replay ledger, canonical call IDs, PostgreSQL transaction and outbox. Office owns the local customer/property match, durable staff queue, screen-pop, notifications, replay-safe customer-file call note, RoomFlow job and unpublished estimate. Exact workspace-scoped phone/email matches are the only automatic identity joins; ambiguous or failed calls become review work.

Office is written before any Floodman ERP/Gauzy synchronization. The provider call ID maps to the canonical intake ID; the worker may then create or reuse a Gauzy contact and property project, map those external IDs to the resolved canonical customer and property IDs, and project them back into Office. It never creates a Gauzy estimate from the unpriced call draft. See `AI_CALLING_SETUP.md` for the signed event and approval contract.
