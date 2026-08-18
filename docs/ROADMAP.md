# Roadmap

## Stage 0: preserve and reproduce

- Create a private Git repository from this handoff.
- Tag the untouched baseline `handoff-v4.6.7`.
- Add branch protection and required CI.
- Move secrets/environment identifiers out of source.
- Build the derivative image and both native apps from clean runners.
- Record live/staging versions and checksums.

## Stage 1: stabilize the current test product

- Resolve and verify Full ERP login/browser routing on the real node.
- Add structured startup summary and suppress repetitive expected logs.
- Add end-to-end tests for public gateway routing and content types.
- Add database/file backup automation and restore verification.
- Finish Android 0.4.0-alpha01 physical-device Depth/guided-mode and staging acceptance.
- Get Apple simulator green and close parity gaps.

## Stage 2: data-platform migration

- Design a relational Floodman Office schema.
- Migrate JSON records to PostgreSQL with idempotent migration IDs.
- Add transactions, foreign keys, revision tables and row-level authorization.
- Move documents/layouts to managed object storage or a backed-up file service.
- Add reconciliation dashboards for Gauzy, Square, Documenso and Supabase mappings.

## Stage 3: dedicated-server decomposition

- Split the AIO into independently health-checked services.
- Use a proper reverse proxy and standard HTTPS subdomains.
- Run PostgreSQL as a managed/independent service.
- Add queues for outbox, imports, documents and background media uploads.
- Add centralized logs, metrics, tracing and alerts.
- Retain Tailscale for administrative/private access, not as the only production ingress.

## Stage 4: native product completion

### Android

- Native camera/document scanning and background upload queue.
- Robust offline assigned-job cache and conflict resolution.
- Push notifications through FCM.
- Staff device administration.
- Play internal testing and production signing.

### Apple

- Complete native estimate, invoice, payment, calendar and employee assignment parity.
- iPad-specific RoomFlow and desktop-style layouts.
- APNs notifications.
- TestFlight, App Store review and managed staff distribution.

## Stage 5: production governance

- Third-party license/legal review.
- Payment security and privacy review.
- Messaging consent/A2P policy.
- Disaster-recovery objectives and drills.
- Role/permission audit.
- Change management, release notes and customer-facing document approval process.
