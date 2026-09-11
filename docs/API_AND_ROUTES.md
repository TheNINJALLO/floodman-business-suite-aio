# API and routes

The generated inventory at `docs/generated/API_ROUTE_INVENTORY.csv` enumerates every FastAPI route decorator found in this handoff. It currently reports 340 route decorators across the custom Python services and route-bearing test fixtures.

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
/roomflow/jobs/{job_id}/capture/rooms
/roomflow/jobs/{job_id}/capture/rooms/{room_id}
/roomflow/jobs/{job_id}/capture/operations
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
Minimum iOS version:     0.1.0-alpha02
Required capabilities:   roomflow.workspaces.v1
                         roomflow.capture.v2
                         roomflow.capture.offline.v1
```

Capture writes require the existing bearer token, resolve workspace/job ownership on the server, use stable operation IDs and optimistic room revisions, and reject raw camera/depth fields. Browser Office sessions expose equivalent `/office/api/roomflow/jobs/{job_id}/capture/...` routes.

## Floodman Office browser routes

Office exposes authenticated browser pages and form actions for setup, desktop/mobile workspaces, imports, customers, properties, estimates, invoices, payments, documents, staff, tasks, calendar, RoomFlow, competitor intelligence, linking/provider configuration and engineering/admin actions.

The customer capability portal exposes only token-scoped document, PDF, payment, receipt, message-send, and message-read routes under `/customer/`. Estimate and invoice links for the same customer and service property share one conversation. Staff read and reply through authenticated `/office/messages`; payment and message alerts appear in authenticated `/office/alerts` and the existing Mobile API notification feed. Customer and administrator email notices contain a secure link and summary only, never message text or payment credentials.

Browser authentication is unified at the genuine ERP login. Nginx sends `POST /api/auth/login` to the Office identity bridge, which validates the credentials with the internal Gauzy API, returns Gauzy's original login payload to the ERP browser, and issues the HttpOnly Office/RoomFlow session. `GET /login` records the requested local return path and opens the ERP login; `/login/local` is an explicit Owner recovery path. `POST /login/erp-session` accepts an existing same-origin ERP bearer token only long enough to validate `/user/me` and never persists it.

Important stable entry routes:

```text
/                         Hub root -> workspace selection
/workspace                adaptive PWA selector
/login                    unified ERP login and safe module-return gateway
/login/local              installation Owner recovery login
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
