# Data model and persistence

## Embedded PostgreSQL

The AIO container includes PostgreSQL for the upstream ERP, signing service, and Floodman service databases. The Floodman baseline SQL includes workflow jobs, documents, payment attempts, mappings, webhooks, idempotency, audit/outbox records, competitor targets/snapshots/reports, receivables, messages, promises, holds, AI decisions, alerts, and digests.

## Floodman Office operational store

The current Office implementation uses a file-backed JSON store rooted at `OFFICE_CONSOLE_DATA_DIR` and writes `office-state.json`. Its operational collections include:

```text
contacts
properties
estimates
invoices
payments
documents
notes
time_entries
tasks
roomflow_jobs
catalog_items
public_links
payment_attempts
mobile_devices
mobile_refresh_tokens
mobile_audit
appointments
announcements
notifications
push_tokens
calendar_subscriptions
estimate_revisions
invoice_revisions
roomflow_imports
roomflow_workspaces
roomflow_workspace_selections
```

Documents, uploads, imports, and RoomFlow layout assets are stored under persistent file directories.

## Important architectural debt

The JSON store was effective for fast iteration in a single-company test environment, but it is not the ideal long-term system of record. Before multi-user production growth:

1. design versioned PostgreSQL tables;
2. add a migration ledger;
3. write an idempotent JSON-to-PostgreSQL importer;
4. preserve stable IDs and audit history;
5. run dual-read comparison tests;
6. switch writes only after backup and restore tests;
7. retain a rollback path.

Do not perform an ad hoc rewrite of `office-state.json` on the live server.

## Time

Store timestamps in UTC. Render business dates in `America/Detroit`. Calendar feeds and reminders must preserve time-zone offsets and daylight-saving transitions.

## Backups

A complete backup needs:

- PostgreSQL data or logical dumps
- Office data directory
- documents/uploads
- RoomFlow layout assets
- Tailscale state
- configuration without exposing it in source control
- versioned launcher/runtime or image digest

A source ZIP alone is not a backup.
