# Project history

## Phase 1: clean Windows lab and migration recovery

The first work focused on a local Windows and Docker lab. Gauzy, its browser, PostgreSQL, Documenso, messaging, and supporting services were composed together. Repeated startup failures showed that old migrations and partial database state were causing the new environment to hang. The decision was made to rebuild cleanly rather than keep layering repairs onto uncertain migration state.

The early fixes covered:

- clean database initialization and owner creation;
- duplicate PostgreSQL process and stale `postmaster.pid` handling;
- Gauzy migration ordering and readiness checks;
- owner-account linking and 401 handling;
- preserving data volumes unless a destructive reset was explicitly requested;
- diagnostic bundles rather than silent failure.

## Phase 2: one-unit Pterodactyl deployment

The system was moved into a single Pterodactyl-managed container for mobile-only administration without SSH. The public allocation changed to port 9000, and the full port scheme became 9000 through 9004. The AIO image included embedded PostgreSQL, Gauzy, Documenso, Mailpit, Nginx, Supervisor, and custom Python services.

Pterodactyl-specific fixes included:

- registering runtime UID 988 through NSS wrapping;
- avoiding assumptions about a Linux user existing in `/etc/passwd`;
- writable paths under `/home/container`;
- restart-safe PostgreSQL ownership and lock cleanup;
- root-level ZIP overlay uploads that did not require extraction;
- mobile-friendly launcher replacement and rollback;
- quieted console logs and explicit `FLOODMAN_SUITE_READY` readiness output.

## Phase 3: Floodman identity and operations surface

The interface was rebranded from Gauzy to Floodman, with visible attribution to Josh Aldrich. A custom Floodman Hub and Office surface were added around the full ERP rather than forcing every workflow through the upstream UI.

The Office surface added:

- customer and property records;
- customer notes, pinned notes, tags, and documents;
- CSV and ZIP import;
- signed-document attachment to customer and project files;
- estimates, invoices, payments, receivables, messaging, tasks, and time entries;
- RoomFlow links and project synchronization;
- setup and provider diagnostics.

## Phase 4: PWA, Tailscale, and public customer routes

The staff PWA remained private through Tailscale Serve. The first public gateway experiments exposed customer signing and native-app API routes through Tailscale Funnel. Several routing failures were corrected, including HTML from the signing application being returned to Android instead of JSON, 502 gateway responses, and path mounts that were generated but not loaded by Nginx.

The settled test architecture uses one public loopback gateway. It routes `/mobile-api/*` and `/customer/*` to Floodman Office while keeping the default public path for signing.

## Phase 5: CRM, estimates, invoices, and payments

The customer file was expanded to support more than a contact list. Estimates became a search-first workspace so searching could never accidentally save. New estimates can select or create a customer and service property, then build grouped scope sections using catalog or custom line items.

The approved document design introduced:

- multiple editable headers;
- descriptions and line items under each header;
- quantity, unit, price, tax, optional status, and subtotals;
- category-driven recommended project plans;
- project duration, assumptions, exclusions, protections, and optional upgrades;
- percentage or fixed deposits;
- authorization, payment, scheduling, change-order, invoice, and completion states.

Payments were designed around Square tokenization. Customer online payments, phone card entry, authorized saved payment methods, cash, check, ACH, external card, and other manual methods were added. Floodman does not intentionally store raw card numbers or CVV.

## Phase 6: RoomFlow integration

RoomFlow was first linked into the PWA and later bundled into Android and iOS. The integration maps a RoomFlow job to Floodman customer, service property, job, estimate, catalog, layout, and document records.

The key policy is that the estimate PDF uses an actual saved RoomFlow layout. Historical jobs without a captured image are marked for layout capture. The system must not draw a generic placeholder and present it as measured work.

Original RoomFlow Supabase migration was added later. It authenticates using the original user for a one-time import and migrates the rows visible to that user. Stable source IDs make repeated imports update rather than intentionally duplicate records.

## Phase 7: native Android app

The Android app became a native Kotlin and Jetpack Compose shell with encrypted API access, device enrollment, biometric/device-PIN unlock, and a bundled RoomFlow workspace. Build iterations corrected SDK licensing, Kotlin compiler DSL changes, Square callback overloads, biometric host types, Compose context usage, camera-feature lint, setter collisions, and Android predictive back behavior.

The latest Android source is alpha12. It retains RoomFlow workspaces and Supabase import, scopes native customer/property lookup to the selected Floodman company, and passed the local JDK 17/Gradle 8.13 compiler, unit, lint, APK, and AAB gate. External CI dispatch and physical-device acceptance remain outstanding.

## Phase 8: Apple app

A SwiftUI iPhone/iPad alpha was created with Keychain session storage, API access, dark mode, core module shells, and bundled RoomFlow. The first compile fixes addressed optional binding, actor isolation, and SwiftUI text interpolation. A simulator workflow and guarded TestFlight workflow are included.

The simulator build must turn green before signing or TestFlight work resumes.

## Phase 9: scheduling and team operations

The system added jobs, inspections, estimate appointments, follow-ups, deliveries, meetings, training, employee assignment, lead employee selection, conflict detection, tasks, announcements, notifications, time clock, and read-only calendar subscriptions.

Native push token registration exists, but complete FCM and APNs delivery remains future work. Outlook two-way calendar editing also remains future work.

## Phase 10: desktop/mobile split and Full ERP recovery

The PWA originally launched only into a mobile layout. Later releases created dedicated desktop and mobile workspaces, an adaptive `/workspace` launcher, explicit mode selection, cache recovery, a reliable Office health endpoint, and desktop-safe CSS even on touchscreen computers.

The Full ERP launcher was then repaired so an unsigned-in session opens login instead of a false server-down page. The final v4.6.7 guard also preserves the browser-facing Tailscale HTTPS origin when the internal proxy hop is HTTP.
