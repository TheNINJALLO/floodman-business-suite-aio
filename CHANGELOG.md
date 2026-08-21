# Floodman Operations condensed changelog

This changelog summarizes the major cumulative milestones reconstructed from the session artifacts. Some intermediate packages were diagnostic or failed build attempts and were never intended as final production releases.

## 4.7.1

- Added safe PLX recognition and an authorized CSV preview/confirm workflow for stable, non-duplicating insurance pricing updates.
- Preserved insurance item codes and supported source metadata through catalog search, RoomFlow selection, estimates, and PDFs.
- Added property-scoped customer portal conversations, staff replies, customer/staff read controls, and retry-safe deduplication.
- Added durable payment-administrator and customer-message alerts with optional privacy-bounded email notices and existing mobile notification-feed delivery.
- Produced a distinct deterministic 205-file Pterodactyl runtime, launcher, egg, internal manifest, and checksums without changing native versions, Mobile API compatibility, minimum clients, or the RoomFlow pin.
- Preserved the frozen v4.7.0 runtime and launcher as byte-identical rollback evidence. Staging, devices, advisory scanning, signing/store, backup/restore, and production deployment remain external gates.

## 4.7.0

- Added suite-owned RoomFlow Capture with shared schema-v2 geometry, authenticated room revisions, idempotent offline replay, and redacted audit records.
- Added a low-training browser capture/review workflow with manual/templates/native entry, corrections, openings, affected-area quantities, undo/redo, dismissible dialogs, and mobile layout coverage.
- Added Android 0.4.0-alpha01/build 13 with real ARCore capture, optional Depth, guided fallback, lifecycle/permission handling, bridge v2, and a bounded private outbox.
- Prepared Apple RoomPlan/ARKit/LiDAR capture source without claiming the unavailable Xcode or device gates; the Apple identity remains 0.1.0-alpha03.
- Packaged checksum-verified offline assets from the unchanged RoomFlow pin and produced deterministic v4.7.0 Pterodactyl runtime, launcher, egg, manifests, and checksums.
- Kept Mobile API `0.3.0-alpha11` and minimum-client floors unchanged. Physical-device, staging, container, signing/store, backup/restore, and production gates remain external.
- Corrected the v4.7.0 launcher after the first Wings attempt exposed a stale RoomFlow section-editor heading assertion; the runtime ZIP remains unchanged and package verification now checks launcher overlay assertions against packaged source.

## 4.6.10

- Added one ordered Settings & Setup home for business details, team access, services/prices, RoomFlow, payments, signing, imports, and advanced connections.
- Reworked CRM and RoomFlow settings with plain labels, safe Detroit-time defaults, server validation, progressive disclosure, and dismissible help/feedback for low-training use.
- Added the owner-only browser path for importing original RoomFlow Supabase data through the existing stable-ID, update-without-duplication importer; supplied passwords are not persisted.
- Added four-step RoomFlow guidance across the web and the unchanged Android alpha12/iOS alpha03 source candidates.
- Advanced only the server/web/Pterodactyl identity so hosts already recognizing v4.6.9 can install the update. Mobile API, native app versions, minimum-client versions, and the exact RoomFlow pin remain unchanged.

## 4.6.9

- Advanced the unsigned native candidates to Android `0.3.0-alpha12` and iOS `0.1.0-alpha03` after explicit authorization; Mobile API and minimum-client versions remain backward compatible.
- Scoped native RoomFlow customer/property lookup and saves to the selected company workspace and prevented cross-company job/estimate reuse.
- Replaced the remaining RoomFlow Supabase account/company prompt with company workspace controls authorized by the existing Floodman ERP session.
- Added browser APIs to list, create, and select RoomFlow company workspaces without storing another password or token.
- Scoped browser RoomFlow customer/property lookup, job lists, saved snapshots, and synchronized estimates to the selected Floodman company workspace, including collision-safe IDs when two companies use the same upstream identifiers.
- Added a browser regression proving the legacy create-company handler is removed and the separate account overlay cannot cover the integrated RoomFlow workspace.
- The initial server-only v4.6.9 repair kept Android alpha11/iOS alpha02 unchanged; the later explicit native authorization produced the alpha12/alpha03 candidates above without advancing Mobile API compatibility or the RoomFlow pin.

## 4.6.8

- Unified the genuine ERP login with Office and integrated RoomFlow browser sessions.
- Added verified existing-ERP-session exchange and safe return to the originally requested Floodman module.
- Corrected RoomFlow authentication subrequests to return 401/403 instead of an unusable redirect response.
- Added a distinct server/Pterodactyl test-release identity so hosts already running v4.6.7 can install the cumulative update.
- Kept Android `0.3.0-alpha11`, iOS `0.1.0-alpha02`, Mobile API `0.3.0-alpha11`, and the pinned RoomFlow commit unchanged. Native rebuilds were explicitly deferred for this server-only test package and are not claimed as passes.

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
