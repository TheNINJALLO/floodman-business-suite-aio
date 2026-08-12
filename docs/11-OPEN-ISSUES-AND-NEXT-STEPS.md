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
