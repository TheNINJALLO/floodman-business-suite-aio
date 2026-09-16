# Version and milestone history

The releases below are the major cumulative milestones represented by the conversation. Many small hotfixes existed between them; the latest source supersedes them unless provenance is specifically needed.

## Windows lab era

- **v1.x-v2.x**: local Windows Docker lab, Gauzy/Documenso/orchestrator bring-up, company/owner bootstrap and migration diagnostics.
- Main lessons: migrations needed bounded readiness checks; owner linking required authenticated identity; database cleanup had to be explicit and non-destructive.

## Pterodactyl AIO era

- **v3.0**: fresh clean baseline after abandoning the partially migrated lab.
- **v3.1.x**: first one-container Pterodactyl AIO composition; ports 9000-9004; persistent directories.
- **v3.2.x**: runtime UID/nss_wrapper and Pterodactyl compatibility repairs.
- **v3.3.x**: Floodman rebrand, customer files, signed-document attachment, CSV import, public gateway/browser TLS repairs.
- **v3.4.x**: large customer import handling and mobile-friendly Office views.
- **v3.5.x**: installable PWA.
- **v3.6.x**: Tailscale private staff access, quieter console, restart behavior.
- **v3.7.x**: CRM expansion, tokenized Square payment methods, card-on-file and AutoPay controls.
- **v3.8.x**: RoomFlow integration, public signing/Funnel, customer-facing overlays.
- **v3.9.0**: shared estimate/catalog work.

## Operations parity era

- **v4.0.x**: branded estimate/invoice/payment templates and online/manual payments.
- **v4.1.x**: explicit estimate workspace, searchable customer/property flow, grouped headers, PostgreSQL restart safety.
- **v4.2.x**: public encrypted Mobile API, Android app foundation, device enrollment, same-origin public gateway and routing repairs.
- **v4.3.x**: workspace/readiness and continued native operations work.
- **v4.4.0**: broad native parity source, calendar, employee assignment, dark mode, actual RoomFlow PDF layout and category project plans.
- **v4.5.0**: bundled native RoomFlow engine for Android/iOS; pinned upstream commit and native bridges.

## RoomFlow migration and workspace era

- **v4.6.0**: original RoomFlow Supabase import and Android alpha10 contract; initial package failed on missing Pillow in the runtime.
- **v4.6.1-v4.6.2**: dependency-free PDF image handling and active-runtime/old-overlay corrections.
- **v4.6.3**: RoomFlow organization/workspace persistence, automatic selection, create/select APIs and Android alpha11.
- **v4.6.4-v4.6.5**: desktop/mobile workspace split, adaptive PWA launcher and real desktop layout.
- **v4.6.6**: same-origin health-based online status and service-worker startup behavior.
- **v4.6.7**: Full ERP authentication-aware launcher, browser boot guard and HTTPS-origin repair.
- **v4.6.8**: Unified ERP/Office/RoomFlow login plus a distinct server-only Pterodactyl test-update identity.
- **v4.6.9**: RoomFlow company workspaces use the existing Floodman ERP session; legacy Supabase account prompts are neutralized, native lookups are company-scoped, and Android alpha12/iOS alpha03 are prepared.
- **v4.6.10**: Guided CRM and RoomFlow settings, server-validated safe defaults, dismissible four-step help, owner-only original RoomFlow import, and a distinct server/Pterodactyl update identity; native and Mobile API identities remain unchanged.
- **v4.7.0**: Integrated suite-owned RoomFlow Capture with authenticated revisions, offline replay, web review/corrections, Android ARCore/Depth capture, prepared Apple RoomPlan/ARKit source, checksum-addressed exact-pin assets, and distinct Pterodactyl test artifacts.
- **v4.7.1**: Licensed pricing preview/import plus secure property-scoped customer conversations and durable payment/message administrator alerts in a distinct server/Pterodactyl package.

## Android alpha compiler history

- **0.1.0-alpha01**: native app/Mobile API foundation.
- **alpha02-alpha04**: workflow/Kotlin DSL/source/lint repairs.
- **0.2.0-alpha05**: estimate/invoice/calendar/dark-mode parity source.
- **0.3.0-alpha06**: bundled RoomFlow engine.
- **alpha07-alpha09**: Compose imports, JVM setter collision and predictive-back repairs.
- **alpha10**: Supabase import/bootstrap and document-content validation.
- **alpha11**: RoomFlow workspaces/company selection.
- **alpha12**: v4.6.9 company-scoped RoomFlow lookup/save isolation and refreshed unsigned packages.
- **0.4.0-alpha01**: build 13 adds ARCore capture with optional Depth, guided fallback, bridge v2, review/correction metadata, and bounded durable offline operations.

## Apple alpha history

- **0.1.0-alpha01**: initial SwiftUI shell and simulator workflow.
- **0.1.0-alpha02**: Swift compile repairs, local RoomFlow asset server hardening, app icons and guarded TestFlight workflow.
- **0.1.0-alpha03**: v4.6.9 company-scoped RoomFlow lookup and refreshed simulator/TestFlight workflow identities.
