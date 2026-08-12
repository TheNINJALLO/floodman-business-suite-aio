# Floodman Operations complete project and source handoff

Current baseline: server v4.6.7, Android 0.3.0-alpha11, iOS 0.1.0-alpha02.

This document is the complete narrative handoff. The source archive contains the editable code, build files, inventories, deployment files, and reference documents.

## Table of contents

1. Executive handoff
2. Project history
3. Current architecture
4. Feature inventory
5. Pterodactyl deployment
6. Local development in VS Code and Codex
7. Android application
8. iPhone and iPad application
9. RoomFlow integration
10. Data model and persistence
11. Security model
12. Open issues and next steps
13. Version history
14. Third-party and source boundaries
15. Configuration and secrets
16. Testing and release
17. Codex starter prompt
18. API inventory
19. Release checklist

---

# Executive handoff

## What was built

Floodman Operations is a single-company field-service and business-operations suite for waterproofing, foundation repair, restoration, mold work, demolition, inspections, and related projects. The system started as a clean all-in-one Gauzy test environment and grew into a Floodman-branded platform with its own Office workspace, customer records, estimating, invoicing, payments, document signing, RoomFlow field measurement, scheduling, receivables, messaging, competitor intelligence, PWA, Android app, and early iPhone/iPad app.

The current custom server baseline is v4.6.7. Android is v0.3.0-alpha11. iOS is v0.1.0-alpha02. RoomFlow is pinned to commit `1f97817a52b916875e50cc6380c0d284072b8ce8`.

## Business outcomes

The target workflow is one connected project record:

```text
Lead or imported customer
  -> customer file and service property
  -> inspection or scheduled job
  -> RoomFlow measurements and field layout
  -> grouped Floodman estimate
  -> electronic work authorization
  -> deposit and scheduling
  -> work, photos, notes, and change orders
  -> invoice and payments
  -> completion documents, warranty, and retained customer history
```

The approved estimate is a four-page Floodman document with customer/property details, a recommended project plan, grouped scope, actual RoomFlow layout, assumptions, exclusions, deposit, and approval path. The approved invoice is a two-page document with amount due, service property, estimate/job reference, contract activity, payment history, linked documents, and completion notes.

## Deployment model

The testing deployment is one Pterodactyl server using ports 9000 through 9004. Staff web surfaces are private through Tailscale. Public customer signing, payment pages, and the narrow native-app API are exposed through an HTTPS gateway. Native apps do not require Tailscale on every phone.

## Important status boundary

This handoff contains the complete Floodman custom source and current build files, not the live database. It does not establish that Android alpha11, iOS alpha02, or server v4.6.7 have passed a fresh end-to-end release on a clean node. Those are the first release gates to repeat in VS Code and Codex.

## Recommended migration strategy

1. Put this folder into a new private Git repository.
2. Tag the untouched handoff as `handoff-v4.6.7`.
3. Run all static verification before editing.
4. Build the derivative server image on the current AIO base.
5. Run the Android workflow and physical-device acceptance test.
6. Run the iOS simulator workflow.
7. Create a clean staging Pterodactyl server and restore a sanitized backup.
8. Only after staging passes should the live server move from overlay ZIP deployment to a source-built image.

---

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

The latest Android source is alpha11. It adds RoomFlow workspaces and organization selection after the Supabase import. The final Gradle workflow still needs to be run again in the new repository.

## Phase 8: Apple app

A SwiftUI iPhone/iPad alpha was created with Keychain session storage, API access, dark mode, core module shells, and bundled RoomFlow. The first compile fixes addressed optional binding, actor isolation, and SwiftUI text interpolation. A simulator workflow and guarded TestFlight workflow are included.

The simulator build must turn green before signing or TestFlight work resumes.

## Phase 9: scheduling and team operations

The system added jobs, inspections, estimate appointments, follow-ups, deliveries, meetings, training, employee assignment, lead employee selection, conflict detection, tasks, announcements, notifications, time clock, and read-only calendar subscriptions.

Native push token registration exists, but complete FCM and APNs delivery remains future work. Outlook two-way calendar editing also remains future work.

## Phase 10: desktop/mobile split and Full ERP recovery

The PWA originally launched only into a mobile layout. Later releases created dedicated desktop and mobile workspaces, an adaptive `/workspace` launcher, explicit mode selection, cache recovery, a reliable Office health endpoint, and desktop-safe CSS even on touchscreen computers.

The Full ERP launcher was then repaired so an unsigned-in session opens login instead of a false server-down page. The final v4.6.7 guard also preserves the browser-facing Tailscale HTTPS origin when the internal proxy hop is HTTP.

---

# Current architecture

## Logical components

```text
Users and devices
  |-- Private browser/PWA over Tailscale
  |-- Android over public HTTPS Mobile API
  |-- iPhone/iPad over public HTTPS Mobile API
  |-- Customers over public tokenized links

Pterodactyl AIO container
  |-- Nginx Floodman Hub and gateway
  |-- Floodman Office FastAPI service
  |-- Gauzy API and Gauzy browser
  |-- Documenso signing runtime
  |-- Embedded PostgreSQL
  |-- Mailpit
  |-- Orchestrator API and worker
  |-- Messaging AI
  |-- Competitor Intelligence API and scheduler
  |-- Local Lab / engineering support service
  |-- RoomFlow web assets and integration bridge
  |-- Supervisor process manager
```

## Internal ports

| Port | Purpose |
|---:|---|
| 8700 | Floodman Office loopback service |
| 9000 | Floodman Hub, Office/PWA routing, guarded Full ERP |
| 9001 | Documenso/signing |
| 9002 | Mailpit test mail |
| 9003 | Local Lab and engineering surface |
| 9004 | Floodman API and orchestrator-facing routes |
| 9010 | Loopback public gateway used by Funnel |

## Private Tailscale ports

| HTTPS port | Internal target |
|---:|---|
| 8443 | 9000 |
| 8444 | 9001 |
| 8445 | 9004 |
| 8446 | 9002 |
| 8447 | 9003 |

## Public gateway

The test public gateway is intentionally narrow:

```text
/mobile-api/* -> Floodman native-app API
/customer/*   -> tokenized customer pages, documents, and payments
/              -> signing service
```

The staff PWA, Full ERP, engineering tools, Mailpit, and databases are not intended to be public.

## Server services

### Floodman Office

Primary custom operations application. It contains the web UI, customer portal, Mobile API, authentication, customer import, estimate/invoice PDFs, project plans, RoomFlow assets/import, provider adapters, scheduling, documents, payments, and the operational store.

### Orchestrator

Coordinates internal jobs, synchronization, messaging, webhooks, and estimate/job workflows. It has both API and worker processes.

### Messaging AI

Provides deterministic or configured provider-backed message drafting. Customer messaging must remain approval-controlled.

### Competitor Intelligence

Stores targets, snapshots, reports, scan results, and scheduled scan work. External TLS and site failures should be reported per target rather than crash the suite.

### Local Lab

Provides engineering/test functions, local provider mocks, import helpers, and support utilities.

## UI surfaces

| Route | Surface |
|---|---|
| `/workspace` | Adaptive PWA launcher |
| `/office/desktop?desktop=1` | Desktop Floodman Office |
| `/office/mobile?mobile=1` | Phone/tablet Floodman Office |
| `/full-erp` | Authentication-aware full Gauzy ERP |
| `/floodman-status.html` | Runtime diagnostics |
| `/roomflow/` | RoomFlow workspace in the web suite |
| `/mobile-api/v1/*` | Native app API |
| `/customer/*` | Public tokenized customer routes |

## Build model

Two server image paths are included:

1. `containers/derivative/Dockerfile` layers the current source onto the existing Floodman AIO base image. Use this first.
2. `containers/base-aio/Dockerfile` rebuilds the complete AIO image by composing Gauzy, Documenso, Mailpit, PostgreSQL, and Floodman custom source.

The complete AIO Dockerfile currently references mutable upstream image tags in places. Pin them by immutable digest before production.

---

# Feature inventory

## Customers and properties

- Searchable customer directory
- Customer file with company, contact, mailing, phone, and email information
- Multiple service properties
- Notes, pinned notes, tags, and status
- Customer documents and signed documents
- Estimate, invoice, payment, and job history
- CSV and ZIP import
- Blank import template included in `reference/`
- RoomFlow customer/property mapping

## Estimates

- Search existing estimates without saving
- Create new customer and property inside the estimate flow
- Multiple editable scope headers
- Header descriptions and subtotals
- Reusable catalog search
- Custom line items saved to the catalog
- Quantity, unit, price, tax, optional item, and order controls
- Project category and recommended plan
- Duration, assumptions, exclusions, protections, and optional upgrades
- Percentage or fixed deposit
- Draft, send, resend, authorize, accept, activate deposit, pay, convert, revise, and eligible-delete actions
- Customer portal and PDF
- Actual RoomFlow layout embedding

## Invoices

- Direct invoice creation or estimate conversion
- Grouped editable headers and lines
- Contract total, changes, prior payments, and current balance
- Send/resend, payment, void, and eligible-delete actions
- Customer portal and PDF
- Payment and completion history
- Linked signed documents and project notes

## Payments

- Customer online checkout
- Card by phone using Square tokenization
- Processor-managed saved payment method authorization
- Cash, check, ACH/bank transfer, external card, and other manual methods
- Payment attempts and audit records
- No intended raw card or CVV storage

## Documents and signing

- Documenso-backed signing
- Work authorization
- Change order
- Completion of service
- Warranty and project document linkage
- Signed documents attached to customer and project files
- Public tokenized signing routes

## RoomFlow

- 2D room and custom-shape sketching
- Levels, walls, openings, doors, windows, pumps, drainage, cracks, reinforcement, utilities, and annotations
- Measurements and material quantities
- 3D and supported camera/AR flows
- Internal costing and customer pricing
- Catalog items and grouped estimate scope
- Full job snapshot synchronization
- Actual layout capture
- Original Supabase migration
- Multiple company/workspace support

## Scheduling and workforce

- Jobs and inspections
- Estimate appointments, follow-ups, deliveries, meetings, and training
- Multiple assigned employees
- Lead employee
- Conflict detection and controlled override
- Status, location, internal notes, and customer notes
- Tasks, announcements, notifications, and time clock
- Read-only external calendar subscriptions

## Communications and intelligence

- Mailpit test email
- SMTP provider configuration
- Twilio configuration and local mock support
- Deterministic or configured AI message drafting
- Receivables scheduler and outreach workflow
- Competitor targets, scans, snapshots, reports, and scheduler

## Clients

### PWA

- Private Tailscale access
- Separate desktop and mobile layouts
- Adaptive launcher and explicit mode switching
- Dark/light/system preference data
- Installable PWA and service worker

### Android

- Native Compose shell
- Encrypted API, device enrollment, refresh rotation, secure storage, and biometric/PIN unlock
- Customer, property, estimate, invoice, payment, document, schedule, task, notification, time, and RoomFlow modules
- Bundled local RoomFlow engine
- Dark/light/system modes

### iOS

- Native SwiftUI shell
- Keychain storage and Mobile API client
- iPhone and iPad target
- Core operations module shells
- Bundled RoomFlow engine
- Dark/light/system modes
- Simulator and guarded TestFlight workflows

---

# Pterodactyl deployment

## Current deployment inputs

```text
Image: ghcr.io/theninjallo/floodman-business-suite-aio:3.2.0
Launcher: deployment/releases/mobile-start-v4.6.7.sh
Runtime: deployment/releases/floodman-operations-runtime-v4.6.7.zip
Startup: bash ./mobile-start.sh
Time zone: America/Detroit
```

The source handoff also contains Dockerfiles for replacing the overlay method with a source-built image.

## Current update procedure

1. Create a full Pterodactyl backup.
2. Stop the server and wait for Offline.
3. Wait at least 20 seconds for processes and PostgreSQL to stop.
4. Rename the current `mobile-start.sh` to a versioned backup.
5. Upload the new runtime ZIP and launcher.
6. Do not extract the runtime ZIP.
7. Rename the new launcher to `mobile-start.sh`.
8. Confirm `bash ./mobile-start.sh` is still the Startup command.
9. Start and wait for `FLOODMAN_SUITE_READY`.
10. Test Office health, Mobile API health, desktop, mobile, Full ERP login, customer portal, signing, one estimate PDF, one invoice PDF, and RoomFlow Save & Sync.

## Persistence

Keep these under persistent Pterodactyl storage:

```text
/home/container/data
/home/container/config
/home/container/logs
/home/container/backups
```

Do not bake live customer data, PostgreSQL files, Tailscale state, payment credentials, or signing records into the image.

## Preferred migration to source-built image

1. Build `containers/derivative/Dockerfile` with the current base image.
2. Tag with an immutable release tag and digest.
3. Deploy to a new staging server, not the live server.
4. Restore a sanitized copy of the data and configuration.
5. Run the full release checklist.
6. Change the production egg/image only after backup and rollback are verified.

## Readiness contract

The launcher should print clear milestones and finish with:

```text
FLOODMAN_SUITE_READY
```

A process staying alive is not enough. Health checks must confirm the Hub, Office, Mobile API, database, and required public/private routes.

## Rollback

- Stop the server.
- Restore the prior `mobile-start.sh`.
- Restore the prior runtime ZIP if the launcher selects releases by filename.
- Restore a Pterodactyl backup only when data was changed and the rollback requires it.
- Start and verify the previous health contract.

Never delete the database volume as a routine rollback step.

---

# Local development in VS Code and Codex

## Recommended host

Use Linux, WSL2, or a VS Code Dev Container. Docker is required for the full AIO runtime. Android needs JDK 17 and Android SDK 36. iOS compilation requires macOS and Xcode.

## Baseline setup

```bash
git init
git add .
git commit -m "Floodman v4.6.7 source handoff baseline"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r server/requirements-dev.txt
python scripts/generate_inventory.py
python scripts/verify_repo.py
```

On Windows PowerShell:

```powershell
git init
git add .
git commit -m "Floodman v4.6.7 source handoff baseline"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r server/requirements-dev.txt
python scripts/generate_inventory.py
python scripts/verify_repo.py
```

## Fetch RoomFlow

```bash
bash scripts/fetch-roomflow.sh
```

```powershell
./scripts/fetch-roomflow.ps1
```

The fetched source lands under `vendor/roomflow/source` at the pinned commit.

## Server development

The current custom server source is in `server/`. The main services are ordinary Python packages, but the full runtime expects the AIO network and environment. For isolated work:

- set service-specific `PYTHONPATH` values;
- copy `deployment/env/floodman.env.example` to a local untracked `.env`;
- use Mailpit and local provider modes;
- keep Square in Sandbox;
- use a disposable database and disposable Office data directory.

## Docker paths

Derivative image:

```bash
docker build -f containers/derivative/Dockerfile -t floodman-operations:4.6.7 .
```

Complete AIO image:

```bash
docker build -f containers/base-aio/Dockerfile -t floodman-business-suite-aio:4.6.7 .
```

The complete build composes upstream images. Pin each upstream image by digest before a release.

## Suggested branch plan

```text
main                  verified releases only
develop               integrated next release
feature/<name>        one feature or repair
release/<version>     release stabilization
hotfix/<version>      urgent cumulative fix
```

## First Codex task

Open `docs/16-CODEX-STARTER-PROMPT.md` and give it to Codex from the repository root. Ask Codex to report its plan before changing files.

---

# Android application

## Current release

```text
Version: 0.3.0-alpha11
Package: com.floodman.operations
Minimum Android: API 28 / Android 9
Compile and target SDK: 36
JDK: 17
Gradle: 8.13
Android Gradle Plugin: 8.13.2
Kotlin: 2.3.20
```

## Architecture

The app is a native Jetpack Compose staff application. RoomFlow runs from local packaged web assets inside a secure Android app-assets origin and communicates with Kotlin through a narrow bridge. The app does not need the Tailscale Android client because it uses the public HTTPS Mobile API.

## Security

- HTTPS only; cleartext disabled
- device enrollment
- short-lived access tokens
- rotating refresh tokens
- encrypted local session storage backed by Android Keystore
- biometric or device-PIN unlock
- device revocation
- capability/version check during login
- PDF content-type and `%PDF-` signature validation

## Build

Copy `local.properties.example` to `local.properties` and configure the Mobile API URL and Square Sandbox application ID.

```bash
cd apps/android
gradle --no-daemon :app:compileDebugKotlin
gradle --no-daemon :app:testDebugUnitTest :app:lintDebug
gradle --no-daemon :app:assembleDebug :app:assembleRelease :app:bundleRelease
```

The authoritative workflow is `deployment/github-actions/build-android-alpha11.yml`.

## Required acceptance test

1. Sign in with Tailscale disabled on the phone.
2. Confirm server capability negotiation succeeds.
3. Search and open customers and properties.
4. Create, edit, send, authorize, accept, pay, and convert an estimate.
5. Create, edit, send, pay, void, and open an invoice PDF.
6. Open RoomFlow, select a workspace, open an imported job, edit the layout, and Save & Sync.
7. Confirm grouped estimate headers and line items update without duplication.
8. Confirm the actual RoomFlow layout appears in the estimate PDF.
9. Test calendar assignment, tasks, documents, time clock, notifications, and dark mode.
10. Revoke the device and confirm refresh fails.

## Known status

No final green alpha11 GitHub Actions log is included in this conversation handoff. Treat the current source as a release candidate until the complete workflow passes and a physical-device test is recorded.

---

# iPhone and iPad application

## Current release

```text
Version: 0.1.0-alpha02
Bundle ID: com.floodman.operations
UI: SwiftUI
Project generation: XcodeGen
Build target: iPhone and iPad
```

## Included foundation

- Floodman login and Mobile API client
- Keychain session storage
- rotating refresh-token proof
- Face ID, Touch ID, or device passcode flow
- dashboard and core module shells
- dark/light/system appearance
- bundled RoomFlow engine and local asset server
- customer/property/job/layout synchronization scaffolding

## Simulator build

Use the unsigned simulator workflow first:

```text
deployment/github-actions/build-ios-simulator-alpha02.yml
```

It requires the `FLOODMAN_API_BASE_URL` repository variable but no Apple signing secrets.

## TestFlight

Run the guarded TestFlight workflow only after the simulator build is green. It requires:

```text
APPLE_TEAM_ID
IOS_DISTRIBUTION_CERTIFICATE_BASE64
IOS_DISTRIBUTION_CERTIFICATE_PASSWORD
IOS_PROVISIONING_PROFILE_BASE64
APP_STORE_CONNECT_KEY_ID
APP_STORE_CONNECT_ISSUER_ID
APP_STORE_CONNECT_PRIVATE_KEY_BASE64
```

Never commit those values. Store them only as GitHub Actions secrets or in a dedicated secret manager.

## Known status

The last TestFlight attempt in the session failed before compilation because Apple signing secrets were missing. The alpha02 source includes the Swift fixes from the first compiler pass, but a new simulator build is still required. Native estimate, invoice, payment, scheduling, and employee-assignment depth must be verified against Android before calling the Apple app feature-complete.

---

# RoomFlow integration

## Pin

```text
Repository: https://github.com/TheNINJALLO/roomflow.git
Commit: 1f97817a52b916875e50cc6380c0d284072b8ce8
```

The repository is not duplicated in this source archive. Fetch it through the provided scripts. This keeps provenance clear and prevents an accidental unreviewed update.

## Data contract

A RoomFlow synchronization can carry:

- workspace/company
- customer and service property
- job identity
- levels, rooms, walls, openings, fixtures, utilities, and annotations
- measurements
- project category
- internal costing snapshot
- customer estimate sections and lines
- catalog references and custom items
- linked estimate
- actual layout JPEG

## Original Supabase migration

The migration authenticates using the original RoomFlow user. Supabase row-level security determines which organizations and records can be read. The credentials are used for the request and are not intended to be stored by Android or Floodman.

Stable source identifiers make migration idempotent. A repeated import should update mapped records rather than create intentional duplicates.

## Workspaces

v4.6.3 introduced persistent Floodman RoomFlow workspaces. Imported organizations become selectable workspaces. Jobs, customers, properties, estimates, and catalog items retain workspace linkage. A safe default workspace can be created when no organization has been imported.

## Actual layout policy

The project-plan page of the estimate must use the actual captured RoomFlow layout. Imported historical geometry without a saved image is marked as needing capture. Open the job and run Save & Sync once to create the real layout image.

## Bridge rules

- Native shells supply the authenticated Floodman session and selected customer/property/workspace.
- RoomFlow must not receive a service-role key.
- RoomFlow must not bypass the Mobile API to perform privileged Floodman writes.
- Bridge event schemas must be versioned before breaking changes.
- Advancing the RoomFlow commit requires Android, iOS, server, snapshot restoration, catalog, layout, and estimate regression tests.

---

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

---

# Security model

## Exposure model

- Staff PWA and Full ERP: private Tailscale access
- Native app API: public HTTPS, narrow route set
- Customer estimates/invoices/payments: public tokenized links
- Signing: public customer surface
- Engineering, Mailpit, database, Supervisor, and administrative internals: private only

## Native device security

- per-device enrollment
- encrypted session storage
- short access-token lifetime
- rotating refresh tokens
- device-specific proof
- remote revocation
- HTTPS-only network policy
- biometric/device-PIN local unlock
- server capability and minimum-version negotiation

## Payment security

- use Square-hosted or native tokenization
- never store PAN, CVV, track data, or full card-entry payloads
- store only processor IDs and masked metadata when needed
- verify webhooks and make them idempotent
- use Sandbox until acceptance tests pass
- restrict payment logs

## Customer-link security

- use random, unguessable tokens
- store token hashes when feasible
- set expiration and revocation rules
- scope a link to one document or action
- record access and completion events
- do not expose internal IDs as authorization

## Internal service security

- use HMAC-authenticated internal requests
- enforce timestamp windows and replay protection
- rotate keys with key IDs
- separate AI provider keys from internal service keys
- run deterministic AI mode when customer-message approval is not configured

## Secrets

Never commit:

```text
Tailscale auth keys
Square access or webhook keys
OpenAI keys
Twilio credentials
SMTP passwords
Apple certificates, profiles, or App Store Connect keys
Android signing keys
mobile token secrets
HMAC secrets
production database passwords
```

Use `.env.example` only as a field catalog.

## Immediate hardening tasks

- pin upstream images by digest
- run container and dependency vulnerability scanning
- add rate limiting and abuse controls to public endpoints
- centralize secrets
- add structured audit export
- add backup encryption and restore drills
- review Documenso/Gauzy licenses and public-source obligations
- complete a payment and customer-data threat model

---

# Open issues and next steps

## Release-critical

1. Run the complete Android alpha11 GitHub workflow.
2. Run a physical Android device test against a staging v4.6.7 server.
3. Run the iOS alpha02 simulator workflow.
4. Verify v4.6.7 on a clean staging Pterodactyl node.
5. Verify Full ERP login, desktop, mobile, PWA cache updates, and Tailscale HTTPS behavior.
6. Test estimate and invoice PDF generation with and without RoomFlow layout images.
7. Test backup, restore, and rollback.

## Infrastructure

- Pin Gauzy, Documenso, Mailpit, and the Floodman base image by immutable digest.
- Replace temporary Funnel exposure with a conventional Floodman-owned HTTPS domain and gateway.
- Add central logs, metrics, alerts, and crash reporting.
- Add automatic encrypted backups and restore verification.
- Separate staging and production credentials.

## Data

- Move the Office JSON operational store to PostgreSQL through a versioned migration.
- Add explicit database migrations for every custom service.
- Add referential integrity for customer, property, RoomFlow job, estimate, invoice, payment, and document records.
- Add export/restore tools that do not rely on the runtime UI.

## Native apps

- Confirm complete Android feature parity after alpha11.
- Finish iOS parity for estimate/invoice/payment lifecycle and scheduling.
- Implement FCM and APNs push delivery.
- Add background upload queues and encrypted offline assigned-job cache.
- Add camera/document scanning and resilient photo upload.
- Add production signing, Play internal testing, and TestFlight.

## Business integrations

- Complete Square production onboarding and webhook validation.
- Complete SMTP production configuration.
- Complete Twilio compliance and opt-out handling before production SMS.
- Implement Outlook two-way calendar synchronization if required. Current feed work is read-only.
- Review customer terms, work authorization, change order, warranty, payment consent, privacy, and retention rules with counsel.

## Product cleanup

- Decide whether the full Gauzy ERP remains a long-term user-facing dependency or becomes a background subsystem.
- Replace large generated HTML strings with versioned templates/components.
- Generate OpenAPI clients for Android and iOS.
- Add end-to-end browser and native test suites.
- Consolidate historical release packaging into one reproducible release pipeline.

---

# Version history

## Server milestones

| Version | Main purpose |
|---|---|
| 3.1.1 | First buildable Pterodactyl AIO source package |
| 3.2.x | Mobile/Pterodactyl port, UID, database, and runtime fixes |
| 3.3.x | Floodman rebrand, mobile egg, and browser TLS fixes |
| 3.4.x to 3.6.x | PWA, Tailscale, console, and private/public access work |
| 3.7.0 | Customer CRM and Square foundation |
| 3.8.0 | RoomFlow integration |
| 3.9.0 | Shared estimate catalog |
| 4.0.0 | Branded payments and estimate/invoice templates |
| 4.1.0 | Search-first estimate workspace and grouped scope |
| 4.1.1 | Restart-safe PostgreSQL launcher |
| 4.2.0 | Mobile API and Android enrollment |
| 4.2.1 to 4.2.3 | Enrollment and public gateway fixes |
| 4.4.0 | Native parity, scheduling, dark mode, and actual RoomFlow PDF logic |
| 4.5.0 | Native RoomFlow packaging for Android and iOS |
| 4.6.0 | Original RoomFlow Supabase migration and API compatibility contract |
| 4.6.1 to 4.6.2 | Removed hard Pillow dependency |
| 4.6.3 | RoomFlow organizations/workspaces |
| 4.6.4 to 4.6.6 | Dedicated desktop/mobile PWA and false-offline repairs |
| 4.6.7 | Authentication-aware Full ERP routing and HTTPS boot guard |

## Android milestones

| Version | Main purpose |
|---|---|
| 0.1.0 | First native Android alpha and Mobile API client |
| 0.1.1 | Android SDK license workflow fix |
| 0.1.2 | Kotlin compiler options migration |
| 0.1.3 | Source compile fixes for Square, biometric, Compose, and API calls |
| 0.1.4 | Camera manifest lint fix |
| 0.2.0 | Operations parity, scheduling, and dark mode expansion |
| 0.3.0-alpha06 | Bundled native RoomFlow release candidate |
| alpha07 | Compose import and source fixes |
| alpha08 | ViewModel setter collision fix |
| alpha09 | Predictive back navigation fix |
| alpha10 | Supabase migration, snapshot preservation, PDF validation, and version contract |
| alpha11 | Persistent RoomFlow workspaces and organization selection |

## iOS milestones

| Version | Main purpose |
|---|---|
| 0.1.0-alpha01 | Initial SwiftUI iPhone/iPad shell and RoomFlow bundle |
| 0.1.0-alpha02 | First Xcode compiler repairs and guarded TestFlight workflow |

## Status note

Version existence does not guarantee deployment or a green platform build. Historical packages include experiments, diagnostics, and superseded hotfixes. The editable source baseline in this handoff is server v4.6.7, Android alpha11, and iOS alpha02.

---

# Third-party and source boundaries

## Included source

This archive includes the complete Floodman-authored custom server overlay, Android application, iOS application, AIO integration source, launchers, tests, and deployment scaffolding available in the session.

## RoomFlow

RoomFlow is maintained in a separate repository and pinned by commit. Fetch scripts are provided. Its license and repository history should remain attached to that source.

## Gauzy and Documenso

The AIO image composes Gauzy and Documenso runtime images. Their repositories are not copied into this handoff. Before distributing a source-built image, review their current licenses, notices, modification/source obligations, and network-use terms with counsel. Keep visible third-party notices where required, even while the customer-facing UI is fully Floodman branded.

## Mailpit, Tailscale, Square, Twilio, Apple, and Google

These are external runtimes or services. Their SDKs, APIs, account terms, and distribution rules remain separate from Floodman source ownership.

## Mutable tags

The current full-image Dockerfile still uses some mutable `latest` tags. Production builds must replace them with immutable digests and record those digests in `vendor/UPSTREAMS.lock.json`.

## Meaning of full source in this handoff

“Full source” means the full custom Floodman source and all build/deployment material created in the session. It does not mean copies of every upstream open-source repository, proprietary payment processor, hosted service, or live customer dataset.

---

# Configuration and secrets

## Configuration files

- `deployment/env/floodman.env.example`
- `deployment/env/floodman-payments.env.example`
- `deployment/env/tailscale.env.example`
- `deployment/env/apple-testflight-secrets.example`
- Android `local.properties.example`

Examples are field catalogs only. Copy them to untracked local files and replace placeholders.

## Major configuration groups

- company and owner identity
- time zone
- ports and public/private URLs
- PostgreSQL databases and passwords
- internal HMAC keys
- mobile token secret and lifetimes
- Square environment, application, token, location, version, and webhook configuration
- Documenso URLs and webhook secret
- SMTP and Twilio
- AI provider and API key
- Tailscale hostname and auth/bootstrap state
- Apple and Android signing

## Secret handling

Recommended hierarchy:

1. local `.env` files ignored by Git for development;
2. GitHub Actions secrets for CI signing and provider tests;
3. Pterodactyl encrypted variables or mounted secret files for staging;
4. a dedicated secret manager for production.

Rotate any secret that was ever pasted into a chat, console screenshot, public issue, or committed file.

## Environment inventory

`docs/generated/ENVIRONMENT_VARIABLES.csv` contains the variable names referenced by the custom source. It intentionally does not contain values.

---

# Testing and release

## Static checks

```bash
python scripts/generate_inventory.py
python scripts/verify_repo.py
```

These check version pins, Python syntax, shell syntax, JavaScript syntax, structured files, source manifests, sensitive-file exclusions, and key API contract strings.

## Server smoke tests

The current server source includes smoke tests for:

- Mobile API authentication and operations
- RoomFlow native sync
- RoomFlow Supabase migration
- RoomFlow workspaces
- PDF runtime without Pillow
- desktop/mobile workspace routing
- Full ERP routing

Run them in an environment containing the service dependencies and expected `PYTHONPATH`.

## Android gate

A release is not complete until all of these pass on a clean GitHub runner:

```text
compileDebugKotlin
testDebugUnitTest
lintDebug
assembleDebug
assembleRelease
bundleRelease
```

Then complete a physical-device test over public HTTPS with Tailscale disabled.

## iOS gate

1. Generate the Xcode project.
2. Build an unsigned simulator target.
3. Run simulator acceptance tests.
4. Configure Apple signing.
5. Archive and upload through the guarded TestFlight workflow.
6. Test on at least one iPhone and one iPad class device.

## Server release gate

- build from clean source
- pin upstream digests
- create SBOM and vulnerability scan
- test fresh install
- test upgrade from previous release
- test restart after abrupt stop
- test backup and restore
- test all health endpoints and public/private routes
- test PDFs and document signing
- test Square Sandbox and webhook idempotency
- record image digest, source commit, release archive checksum, and database migration level

## Compatibility

The server publishes capability and minimum-version information for native apps. Do not remove a capability or change a payload shape without a versioned migration and client release plan.

---

# Codex starter prompt

Use this from the repository root:

```text
You are taking over the Floodman Operations source handoff.

Before editing anything:
1. Read README.md, AGENTS.md, docs/00-EXECUTIVE-HANDOFF.md, docs/02-CURRENT-ARCHITECTURE.md, docs/10-SECURITY.md, and docs/11-OPEN-ISSUES-AND-NEXT-STEPS.md.
2. Read server/overlay.json, apps/android/README.md, apps/ios/README.md, and vendor/UPSTREAMS.lock.json.
3. Run python scripts/generate_inventory.py and python scripts/verify_repo.py.
4. Report the current versions, source boundaries, failed or unverified release gates, and the files you intend to change.
5. Do not access or import live customer data or secrets.
6. Do not reset any database or modify release artifacts.
7. Preserve the existing Floodman brand, America/Detroit business time zone, payment tokenization boundary, Tailscale private surfaces, public customer/mobile route boundary, and actual RoomFlow layout requirement.

First task:
Create a clean staging build plan for server v4.6.7, Android 0.3.0-alpha11, and iOS 0.1.0-alpha02. Identify reproducibility gaps, mutable dependencies, missing tests, and likely migration risks. Make no code changes until the plan is approved.
```

Suggested second task after the baseline is committed:

```text
Make the Android alpha11 workflow reproducible and green. Do not weaken lint. Preserve the API capability contract and RoomFlow pinned commit. Produce exact build artifacts and checksums, then write an acceptance checklist for a physical Android device.
```

---

# API inventory

The generated scanner found 304 FastAPI route decorators in the custom source:

| Service | Route decorators |
|---|---:|
| Floodman Office | 219 |
| Local Lab | 46 |
| Orchestrator | 27 |
| Competitor Intelligence | 10 |
| Messaging AI | 2 |

The complete machine-readable list is in:

```text
docs/generated/API_ROUTE_INVENTORY.csv
```

Major route families include:

```text
/mobile-api/v1/*       native Android and iOS operations
/office/*              staff Office pages and actions
/customer/*            public tokenized customer actions
/internal/v1/*         signed internal service calls
/api/*                  provider and service APIs
/health/*               readiness and liveness
```

Do not assume every decorator is public. Nginx and Tailscale gateway rules define the exposure boundary.

---

# Release checklist

## Source

- [ ] Untouched handoff baseline committed and tagged
- [ ] Release branch created
- [ ] Version files updated consistently
- [ ] RoomFlow commit reviewed and pinned
- [ ] Upstream image digests pinned
- [ ] Generated inventories refreshed
- [ ] No live data or secrets included

## Server

- [ ] Python, shell, JavaScript, JSON, XML, plist, and YAML checks pass
- [ ] Server smoke tests pass
- [ ] Fresh AIO build succeeds
- [ ] Fresh install succeeds
- [ ] Upgrade succeeds
- [ ] Restart and PostgreSQL recovery succeed
- [ ] Desktop, mobile, Full ERP, health, RoomFlow, signing, and customer routes pass
- [ ] Estimate and invoice PDFs pass
- [ ] Backup and restore pass

## Android

- [ ] Compile, unit tests, lint, APK, and AAB pass
- [ ] Debug and release signatures recorded
- [ ] Public HTTPS login works without Tailscale
- [ ] Estimate/invoice/payment lifecycle passes
- [ ] RoomFlow workspace, import, layout, and sync pass
- [ ] Device revocation passes

## iOS

- [ ] Simulator build passes
- [ ] Core feature parity verified
- [ ] Signing secrets configured outside Git
- [ ] Archive and TestFlight upload pass
- [ ] iPhone and iPad testing pass

## Security and operations

- [ ] Vulnerability scan and SBOM produced
- [ ] Secret scan passes
- [ ] Square Sandbox and webhook tests pass
- [ ] Public route abuse and rate-limit tests pass
- [ ] Logs and alerts configured
- [ ] Rollback package and instructions verified
- [ ] Checksums and release notes published

---
