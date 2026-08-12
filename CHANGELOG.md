# Floodman Operations condensed changelog

This changelog summarizes the major cumulative milestones reconstructed from the session artifacts. Some intermediate packages were diagnostic or failed build attempts and were never intended as final production releases.

## 4.6.7

- Added authentication-aware Full ERP routing.
- Treated an HTTP 200 response containing `false` as signed-out rather than server failure.
- Injected the ERP browser boot guard and preserved HTTPS origin rewriting through Tailscale.
- Added runtime status and recovery routes.

## 4.6.4 through 4.6.6

- Split desktop and mobile Office workspaces.
- Added adaptive PWA selection and explicit desktop/mobile overrides.
- Fixed touchscreen desktop misclassification, stale PWA assets, false offline status, and slow provider startup behavior.

## 4.6.0 through 4.6.3

- Added original RoomFlow Supabase migration through the encrypted Mobile API.
- Added idempotent customer, job, snapshot, catalog, estimate, and line migration.
- Removed the hard Pillow dependency and added direct JPEG layout embedding.
- Added persistent RoomFlow workspaces, automatic organization selection, and workspace-aware records.

## 4.5.0

- Added native RoomFlow packaging for Android and iOS.
- Added actual layout capture and synchronization into Floodman estimates.
- Added Android and iOS GitHub build workflows.

## 4.4.0

- Expanded native parity for estimates, invoices, payments, scheduling, documents, tasks, notifications, and dark mode.
- Added category-driven project plans and actual RoomFlow layout PDF behavior.

## 4.2.0 through 4.2.3

- Introduced the encrypted Mobile API, device enrollment, refresh-token rotation, and public gateway.
- Corrected enrollment validation and `/mobile-api` routing through Tailscale Funnel.

## 4.1.0 through 4.1.1

- Rebuilt estimates as a search-first workspace.
- Added customer/property creation inside the estimate flow.
- Added grouped headers, catalog items, deposits, draft boundaries, and PostgreSQL restart safety.

## 4.0.0

- Added branded estimate/invoice templates and online payment workflow.
- Added Square tokenization plus cash, check, ACH, external, and manual payment recording.

## 3.7.0 through 3.9.0

- Added CRM customer files, properties, notes, tags, document links, CSV/ZIP import, RoomFlow integration, and reusable estimate catalog items.

## 3.3.0 through 3.6.1

- Completed the Floodman rebrand and mobile Pterodactyl packaging.
- Added Tailscale private access, PWA scaffolding, quieter console behavior, public signing, and a public mobile/customer gateway.

## 3.1.1 through 3.2.x

- Established the single-container AIO design around Gauzy, Documenso, Mailpit, embedded PostgreSQL, Nginx, and custom Python services.
- Added Pterodactyl UID/NSS compatibility, restart-safe PostgreSQL behavior, port migration to 9000 through 9004, and browser TLS fixes.
