# API and routes

The generated inventory at `docs/generated/API_ROUTE_INVENTORY.csv` enumerates every FastAPI route decorator found in this handoff. It currently reports 304 route decorators across the five custom Python services.

## Public/native Mobile API

Base path:

```text
/mobile-api/v1
```

Primary groups:

```text
/health, /config
/auth/login, /auth/refresh, /auth/logout, /auth/me
/devices
/dashboard
/customers and customer notes/tags
/properties
/catalog
/estimates and estimate lifecycle/PDF
/invoices and invoice lifecycle/PDF
/payments/card and payments/manual
/documents
/roomflow/bootstrap
/roomflow/workspaces
/roomflow/import/supabase
/roomflow/jobs and layouts
/employees
/calendar, appointments and subscriptions
/tasks
/announcements
/notifications and push tokens
/time/status, clock-in and clock-out
```

The server contract at handoff is:

```text
API version:              0.3.0-alpha11
Minimum Android version: 0.3.0-alpha11
Required capability:     roomflow.workspaces.v1
```

## Floodman Office browser routes

Office exposes authenticated browser pages and form actions for setup, desktop/mobile workspaces, imports, customers, properties, estimates, invoices, payments, documents, staff, tasks, calendar, RoomFlow, competitor intelligence, linking/provider configuration and engineering/admin actions.

Important stable entry routes:

```text
/                         Hub root -> workspace selection
/workspace                adaptive PWA selector
/office/desktop            desktop Floodman workspace
/office/mobile             mobile Floodman workspace
/full-erp                  authentication-aware Full ERP launcher
/floodman-status.html      runtime readiness page
/install-app               PWA install/update page
/roomflow/                 RoomFlow interface
```

## Orchestrator APIs

The orchestrator is internal except for provider webhooks and tokenized customer portal routes. Its major endpoints cover:

- estimate/job synchronization;
- work start, change order and completion;
- document and outbox retries;
- Square and Twilio webhooks;
- AR cases, aging, consent, holds and replies;
- Documenso webhooks;
- customer portal links.

## Competitor Intelligence

Internal endpoints manage targets, reports, target detail and manual scans. External fetches are constrained by the safe-web layer.

## Messaging AI

The service provides health and internal message classification. Keep the provider key server-side.

## Local Lab

Local Lab emulates Gauzy, Square, Documenso, Twilio, payment pages, signing pages, mail, demos and imports for engineering. It must not be publicly exposed as a production payment or signing service.

## Route evolution rule

A route consumed by Android or Apple is a versioned product contract. Breaking changes require:

- a new API/client version;
- explicit server capability;
- mobile compatibility checks;
- migration/release notes;
- old-client behavior or a clear refusal message.
