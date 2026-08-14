# Complete development rundown

This document consolidates the work performed throughout the Floodman Operations conversation. It is a technical project history, not a verbatim transcript. It records the goals, architecture decisions, successive repairs, deliverables, unresolved boundaries, and the latest source baseline carried into VS Code and Codex.

## 1. Starting point: a Windows local business-suite lab

The project began as a Windows-hosted, Docker-based internal business suite that attempted to combine Gauzy, document signing, messaging, competitor intelligence, office operations, and supporting services. Startup repeatedly stalled around migrations and initialization.

The early screenshots showed several classes of failure:

- Gauzy API health starting but database verification failing.
- Orchestrator migrations exiting with status 1.
- A clean-business verification query failing after partial initialization.
- Owner-linking calls returning HTTP 401.
- PostgreSQL/container identity mismatches.
- Permission errors such as inability to create `ormlogs.log`.
- Supporting services attempting to reach PostgreSQL before it was ready.
- Certificate-hostname mismatches while competitor scanning external sites.

The important decision was to stop layering patches over a partially migrated lab and rebuild around a clean, cumulative release model. Every later package was intended to preserve data while replacing the application/runtime layer.

## 2. Rebuild and brand direction

The rebuild established these product rules:

- The user-facing product is **Floodman Operations**.
- Normal interfaces should not show Gauzy branding.
- Creator credit should identify **Josh Aldrich**.
- Gauzy can remain the ERP engine, but it should sit behind Floodman branding and routing.
- Documenso can remain the signing engine, but signed documents must attach to the correct Floodman customer file and job.
- Customer import must accept the company's existing client list.
- Estimates, invoices, payments, documents, RoomFlow, customer files, and communications must form one linked record rather than separate islands.

The approved estimate and invoice examples became the visual and data contract for later PDF work. Estimates were designed around prepared-for details, service property, recommended project plan, project investment, deposit, duration, grouped scope, RoomFlow plan, assumptions, exclusions, authorization, and payment. Invoices were designed around amount due, customer/property/project references, contract activity, payment history, completion record, signed documents, and final balance.

## 3. Pterodactyl as the first hosting target

The user needed to test the complete system as one Pterodactyl unit before moving to a dedicated server. Several practical constraints shaped the implementation:

- The work had to be possible from a mobile browser.
- There was no SSH access.
- Uploads had to work through the Pterodactyl file manager.
- The container had one allocated public port, with a requested `9000`-series scheme rather than port `8080`.
- The server had to preserve its data between image updates.

A single-container AIO image was created around the following allocation plan:

```text
9000  Floodman Hub and browser gateway
9001  signing
9002  Mailpit/test mail
9003  engineering/local lab
9004  Floodman API
```

The initial AIO image reused the Gauzy API image as the main runtime, copied in the Gauzy web browser, Documenso, Mailpit, PostgreSQL, Nginx, Supervisor, and the custom Floodman Python services.

## 4. Pterodactyl runtime identity and filesystem repairs

Pterodactyl executed the container under a runtime identity that did not match assumptions inside PostgreSQL and Node services. Early errors included:

- `initdb: could not look up effective user ID 988`
- missing passwd entries
- permission failures writing logs
- duplicate/stale PostgreSQL lock files
- multiple Supervisor attempts to launch PostgreSQL

The runtime evolved to use `nss_wrapper`, explicit ownership repair, restart-safe PostgreSQL startup, stale lock validation, and persistent paths under `/home/container/data`.

The critical rule established here was that a lock file must not be deleted simply because startup failed. The launcher first determines whether it belongs to a real process, an orphan, or an unrelated PID. This protected the database from a “fix” that could have corrupted a live cluster.

## 5. Floodman Hub, health and browser gateway

A branded Hub was added on port 9000 to provide one entry point for the suite. It evolved from a startup/status screen into a same-origin gateway capable of routing:

- the private PWA;
- Floodman Office;
- the Full ERP browser;
- signing/customer links;
- the public Mobile API path;
- RoomFlow;
- health and status pages.

Repeated browser issues exposed the difference between “the server is running” and “the browser is receiving the correct service.” Several fixes addressed:

- a Hub that returned HTTP 200 while the upstream browser never finished opening;
- customer-signing HTML being returned to Android's JSON login call;
- a public gateway that existed but pointed to the wrong Nginx template;
- false offline status caused by `navigator.onLine` on private Tailscale routes;
- Full ERP links that opened the dashboard when the user was signed out;
- mixed-content and wrong-origin URLs caused by an internal HTTP hop behind external HTTPS.

The latest v4.6.7 source contains an authentication-aware `/full-erp` launcher, ERP boot guard, same-origin health probes, HTTPS-origin rewriting, separate desktop/mobile workspaces, and a status page. The final live validation of that v4.6.7 route was not reported back before this handoff.

## 6. Customer files, contacts and imports

The contacts area was expanded into customer files instead of a flat list. The custom Office system now represents:

- a complete customer/contact record;
- multiple service properties;
- tags;
- notes, including pinned notes;
- documents and signed PDFs;
- estimates and invoices;
- payment history and saved processor payment-method metadata;
- RoomFlow jobs;
- related tasks and appointments.

The import system evolved from expecting a packaged ZIP to accepting individual CSVs as well as ZIP archives. It includes templates, upload preview, validation, commit, import details, and mapping to customers/properties/estimates/invoices/payments/documents/notes.

The live `Clients.csv` was deliberately excluded from this source handoff. The included `Floodman-Customer-Import-Template.csv` is safe to commit.

## 7. Estimate workspace redesign

The estimate flow was rebuilt because a search button could trigger save behavior and because large customer/property lists were unusable as ordinary dropdowns.

The resulting design separates:

```text
Search/open an existing estimate
Create a new estimate
```

A new estimate then walks through:

1. Existing or new customer.
2. Existing customer property or a new property.
3. Project/category/deposit/terms details.
4. Grouped scope and pricing.

Key behavior added over successive releases:

- searchable customer and property selectors;
- customer-specific property filtering;
- explicit draft-save boundary;
- prevention of accidental Enter-key submission;
- multiple editable scope headers;
- header descriptions and ordering;
- shared catalog search;
- custom line items that persist to the catalog;
- quantities, units, pricing, tax status and optional lines;
- percentage or fixed deposits, including 50-percent workflows;
- category-driven recommended project plans;
- estimate PDF, send/resend, authorization, acceptance, deposit activation, payment, conversion and eligible deletion;
- native Android parity endpoints.

Recommended plans were added for basement waterproofing, crawlspace encapsulation, mold remediation, foundation repair, water-damage restoration, drainage/sump systems, demolition/rebuild, inspection/testing, and general restoration. Generated language remains editable for the actual job.

## 8. Invoice and payment workflow

Invoices were expanded beyond simple line items to carry the complete project and payment story:

- customer and property;
- estimate/project reference;
- approved scope and change orders;
- deposit and progress payments;
- current balance;
- payment history;
- completion details and linked signed records;
- branded customer payment action;
- paid-state receipt behavior.

Square remains the processor behind Floodman branding. The intended payment modes are:

- customer online payment;
- card payment taken over the phone through a processor-secure component;
- authorized saved payment method;
- cash;
- check;
- ACH/external payment;
- other manually documented payment.

Floodman is designed to store processor tokens and masked card metadata, never a raw card number or CVV.

## 9. Documents and signing

Documenso was retained as the signing engine, while Floodman added lifecycle and customer-file integration around it. The orchestrator includes signing webhooks and document-state handling. The Office layer includes customer-file attachment, downloads, document records, mobile document upload/download, signature request actions, and linked project records.

The public signing/customer experience was deliberately separated from private staff access. Customer links use scoped tokens, while staff systems require authenticated sessions and device/role checks.

## 10. PWA and Tailscale access

The PWA was introduced to make the system usable on mobile devices before native apps existed. It gained:

- install manifest and icons;
- service worker and offline/startup handling;
- private Tailscale staff access;
- separate phone/tablet and desktop workspaces;
- dark/light/system appearance data;
- workspace selection and cache/version repair.

The current private mapping is:

```text
Tailscale HTTPS :8443 -> Hub/PWA/Full ERP gateway 9000
Tailscale HTTPS :8444 -> signing 9001
Tailscale HTTPS :8445 -> API 9004
Tailscale HTTPS :8446 -> Mailpit 9002
Tailscale HTTPS :8447 -> engineering 9003
```

The user did not have conventional reverse-proxy control through the existing web host, so Tailscale became the private HTTPS fabric. Public customer signing and the Android Mobile API were routed through a narrowly scoped public gateway rather than exposing the complete staff ERP.

## 11. Competitor intelligence and messaging automation

The custom source contains:

- competitor target management;
- safe page fetching and extraction;
- snapshots and reports;
- scheduled scans;
- optional AI analysis;
- message classification;
- receivables cases and aging;
- reminders, holds and payment promises;
- Twilio inbound/status webhooks;
- staff alerts and manual replies;
- customer portal links;
- audit and outbox processing.

External-site failures such as certificate hostname mismatches are expected to be recorded as target-specific scan failures rather than crashing the complete suite.

## 12. RoomFlow integration

RoomFlow grew from a separate field-estimating project into a first-class Floodman module. The integration supports:

- guided estimating;
- 2D sketches and custom shapes;
- multiple building levels;
- doors, windows, openings, drainage, pumps, dehumidifiers, cracks and reinforcement annotations;
- camera/AR tools where supported;
- 3D review;
- measurements and material quantities;
- internal costing and customer pricing;
- scope headers and estimate lines;
- customer/property linking;
- complete project snapshot synchronization;
- actual layout-image capture;
- estimate creation/update;
- original Supabase migration;
- company/workspace selection.

The RoomFlow source remains in its own Git repository at the pinned commit recorded under `vendor/roomflow/`. Android and Apple fetch that exact source during their build and inject platform bridges.

### Supabase migration sequence

The first native RoomFlow build bundled the UI but intentionally removed direct Supabase credentials from the mobile WebView. That left old RoomFlow organizations/jobs absent until a corresponding server-side importer was added.

The importer now authenticates as the original RoomFlow user for one request, reads only records visible through existing Supabase policies, copies organizations/customers/jobs/snapshots/catalog/estimates/lines into Floodman, preserves source IDs, and is intended to be idempotent.

A later repair added persistent Floodman workspaces so imported organizations can be selected inside the native RoomFlow engine. Jobs, catalog items, customer/property links and estimates remain scoped to the selected workspace.

### PDF layout rule

The estimate's measured-work-area page must use a real saved RoomFlow image. Imported geometry alone is not represented as a fake diagram. A historical imported job should be opened and saved once so the app captures the actual canvas. Without that capture, the PDF must clearly state that no saved RoomFlow layout is attached.

## 13. Android native application

The Android app was designed as a real native staff shell rather than a wrapped PWA. It connects through public encrypted HTTPS and does not require Tailscale on the phone.

Its security model includes:

- device registration;
- short-lived access tokens;
- rotating refresh tokens;
- device proof;
- Android Keystore-backed local encryption;
- biometric/device-PIN unlock;
- remote revocation;
- cleartext HTTP disabled;
- no direct database connection.

The app includes native dashboards and operations for customers, properties, estimates, invoices, payments, documents, tasks, announcements, notifications, scheduling, RoomFlow jobs and time clock. The complete RoomFlow field engine is the deliberate local WebView exception, served from Android's secure app-assets origin and bridged to the native authenticated shell.

### Android build repair history

The first builds uncovered a sequence of normal compiler/toolchain issues:

- broken-pipe handling while accepting Android licenses;
- Kotlin `kotlinOptions.jvmTarget` migration to compiler options;
- Square Kotlin overloads;
- `FragmentActivity` requirement for biometrics;
- constructor/lambda ambiguity;
- Material experimental API opt-in;
- Compose context capture;
- optional camera feature declaration;
- missing Compose imports;
- JVM setter/function name collision;
- predictive-back lint migration.

Each correction produced a new alpha source/workflow. The handoff contains alpha11, which includes RoomFlow workspace/company repair. A clean build in the new monorepo is still required to create the authoritative APK/AAB record.

## 14. Apple application

The Apple app began after the Android architecture stabilized. The current SwiftUI alpha includes:

- login and encrypted Mobile API client;
- Keychain session storage;
- rotating refresh-token proof;
- Face ID/Touch ID/passcode unlock path;
- dashboard and basic operational sections;
- bundled RoomFlow engine through a local asset server;
- system/light/dark appearance support;
- iPhone/iPad project definition and app icons.

Early Xcode issues around optional binding, actor isolation and `Any` text interpolation were repaired in alpha02. The source still needs a clean Xcode simulator build in the new repository and does not yet have full native feature parity with Android/PWA. TestFlight additionally requires Apple Developer membership, an explicit bundle ID, distribution certificate, provisioning profile, App Store Connect API key, team ID and signing secrets.

## 15. Calendar, jobs and staff assignment

Scheduling requirements added a shared calendar model for:

- jobs;
- inspections;
- estimate appointments;
- follow-ups;
- deliveries;
- training;
- meetings.

Events can carry customer, property, start/end, multiple assigned employees, lead employee, status, location, internal/customer notes, and estimate/invoice/RoomFlow references. The source contains conflict detection, controlled override, tasks, announcements, notifications, push-token registration, time clock, and read-only calendar subscription feeds.

Actual APNs/FCM delivery still requires provider configuration.

## 16. Desktop/mobile split and Full ERP routing

The PWA originally launched directly into mobile mode. Touch-capable Windows devices were misclassified, and later desktop routes were only mobile layouts stretched across a larger viewport.

The source evolved to provide:

```text
/workspace             automatic selector
/office/desktop        true desktop Floodman workspace
/office/mobile         phone/tablet workspace
/full-erp              authentication-aware Gauzy ERP launcher
/floodman-status.html  runtime status
```

Further fixes replaced unreliable browser-online state with server health probes and added startup-aware service-worker handling.

The final chat issue was that Full ERP still showed its server-down recovery page. v4.6.7 adds signed-in/signed-out routing, an injected browser boot guard, and HTTPS-origin rewriting. Local validation passed, but the user had not yet reported a successful live v4.6.7 test at the moment of this source handoff.

## 17. Data persistence model

The Pterodactyl test runtime persists under `/home/container`, including:

```text
/home/container/data/postgres
/home/container/data/office
/home/container/data/documents
/home/container/data/lab-state
/home/container/data/mailpit
/home/container/data/gauzy-files
/home/container/data/gauzy-import
/home/container/data/documenso
/home/container/data/roomflow/current
/home/container/config
/home/container/logs
/home/container/backups
```

The custom orchestrator uses PostgreSQL tables for workflow jobs, documents, payments, mappings, webhooks, idempotency, audits, outbox events, competitor data, receivables, messaging and alerts.

Floodman Office currently stores its custom operational state in an atomic JSON file, `office-state.json`, with dictionaries for contacts, properties, estimates, invoices, payments, documents, notes, tasks, mobile devices/tokens, appointments, notifications, RoomFlow jobs/imports/workspaces and revisions. That design simplified the one-container prototype, but it should be migrated to a relational database before heavier multi-user production.

## 18. Source handoff decision

The final request was to move the system into VS Code and Codex. This handoff therefore consolidates:

- the latest cumulative custom server source;
- native Android and Apple source;
- the Pterodactyl launcher;
- source-oriented image builds;
- deployment examples;
- original release provenance;
- RoomFlow pin/fetch scripts;
- approved estimate/invoice references;
- static inventories;
- security and data rules;
- a Codex agent contract;
- known issues and roadmap.

Upstream Gauzy and Documenso repositories are not silently copied into the archive. RoomFlow remains pinned and fetched. Live business data and secrets are excluded.

## 19. Current recommended migration path

1. Create a private Git repository from this exact handoff.
2. Tag it `handoff-v4.6.7` before changes.
3. Move all secrets and environment-specific constants out of source.
4. Build the derivative image first, because it stays closest to the proven Pterodactyl base.
5. Restore a sanitized backup in staging.
6. validate every route and lifecycle on staging, especially Full ERP and RoomFlow import.
7. Preserve the successful local Android alpha12 evidence, dispatch its CI workflow after a remote is configured, and run Apple alpha03 on the unsigned Xcode simulator workflow from the same commit.
8. Move the production deployment to a dedicated server only after backup, restore and rollback drills pass.
9. Decompose the one-container test system into separate services and migrate Office state to PostgreSQL.

## 20. Definition of “complete” after the handoff

A true production launch should not be declared until all of the following are evidenced:

- clean reproducible server image build;
- clean startup and restart on the target host;
- database backup and restore drill;
- Full ERP sign-in through the real private URL;
- separate desktop and mobile workspace acceptance;
- customer import reconciliation;
- estimate create/edit/send/sign/deposit/convert flow;
- invoice send/online payment/manual payment/paid receipt flow;
- signed documents attached to customer/job;
- actual RoomFlow layout in PDF;
- Android build and field-device acceptance;
- Apple simulator, physical TestFlight and parity acceptance;
- Square sandbox and then production validation;
- messaging consent and Twilio policy review;
- third-party license and source-availability review;
- monitoring, alerting and recovery runbooks.
