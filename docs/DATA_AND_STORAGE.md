# Data and storage

## Persistent host paths

The one-container Pterodactyl runtime uses `/home/container` as its persistent root.

| Path | Purpose |
|---|---|
| `/home/container/data/postgres` | embedded PostgreSQL cluster |
| `/home/container/data/office` | Floodman Office state and import metadata |
| `/home/container/data/documents` | customer/job documents and generated files |
| `/home/container/data/lab-state` | local engineering/mock state |
| `/home/container/data/mailpit` | captured test mail |
| `/home/container/data/gauzy-files` | Gauzy file storage |
| `/home/container/data/gauzy-import` | Gauzy import staging |
| `/home/container/data/documenso` | signing persistence |
| `/home/container/data/roomflow/current` | prepared RoomFlow runtime/source |
| `/home/container/config` | private configuration and auth-key files |
| `/home/container/logs` | runtime logs |
| `/home/container/backups` | controlled backups |

These directories are not included in the source handoff.

## Orchestrator PostgreSQL schema

`server/database/init/00-floodman-baseline.sql` defines durable workflow tables for:

- `workflow_jobs`
- `workflow_documents`
- `workflow_payments`
- `external_mappings`
- `webhook_events`
- `idempotency_keys`
- `audit_events`
- `outbox_events`
- competitor targets/snapshots/reports
- portal access log
- communication consents
- AR cases
- message threads/events
- payment promises and collection holds
- AI message decisions
- staff alerts and digest runs
- schema version information

Payments and totals use integer cents where represented in custom application state. Provider IDs are mappings, not replacements for internal record IDs.

## Floodman Office state

`server/office-console/app/store.py` currently maintains an atomic JSON document. Operational collections include:

```text
contacts, properties, estimates, estimate revisions, invoices, invoice revisions,
payments, payment attempts, documents, notes, time entries, tasks,
appointments, announcements, notifications, push tokens, calendar subscriptions,
customer threads and customer messages,
RoomFlow jobs, imports, workspaces and workspace selections,
mobile devices, refresh tokens and audit events,
public links and catalog items.
```

Writes use a temporary file followed by atomic replacement. This protects against many partial-write failures but does not provide relational constraints or robust multi-process concurrency. Moving Office state to PostgreSQL is a high-priority dedicated-server task.

Customer conversations use stable contact-plus-property thread IDs; when a document has no property, the individual document is the fallback scope. Customer-message request IDs, processor-payment IDs, and per-user notification IDs are created through a locked create-if-absent operation so browser retries and processor callbacks do not duplicate records. Messages are plain text with a 3,000-character limit. Public capability tokens remain on the estimate/invoice records and are not copied into conversation records.

## External systems

- Gauzy stores ERP identity and upstream business records.
- Documenso stores signing records and audit material.
- Square stores card data and processor customer/payment-method records.
- Supabase is the original RoomFlow source being migrated; source IDs are retained for idempotent matching.

## Import safety

Import flows should always follow:

```text
upload -> parse -> preview -> validate -> commit -> reconcile -> audit
```

Do not commit a partially parsed archive. Validate file paths against traversal and limit upload sizes. The included templates are safe samples; live customer CSVs must stay outside Git.

## Backup and migration recommendation

Before the dedicated-server move:

1. Stop writes or enter a documented maintenance window.
2. Back up the full Pterodactyl data directory and database separately.
3. Record image/runtime versions and checksums.
4. Restore to staging.
5. Verify record counts and random customer/job/payment/document samples.
6. Verify signed-document hashes and external mappings.
7. Run the complete lifecycle acceptance test.
8. Only then cut over DNS/Tailscale clients.
