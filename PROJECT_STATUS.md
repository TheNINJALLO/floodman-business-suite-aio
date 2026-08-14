# Current project status

## Version status

| Component | Version | Source status | Live validation status |
|---|---:|---|---|
| Floodman custom server | 4.6.9 | RoomFlow company-workspace repair packaged and locally verified | Live v4.6.9 upgrade and Full ERP/RoomFlow route validation not yet performed |
| Pterodactyl launcher | 4.6.9 | Deterministic launcher/egg/runtime artifacts built and checksummed | Must be tested on Wings after backup |
| Android app | 0.3.0-alpha11 | Included; unchanged | Build explicitly deferred for the v4.6.9 server-only test package; prior local alpha11 evidence remains historical |
| Apple app | 0.1.0-alpha02 | Included | Xcode simulator/TestFlight acceptance not recorded; parity incomplete |
| RoomFlow | pinned commit | Fetch metadata and native bridges included | Separate repository source must be fetched |
| Gauzy | upstream image | Composed, not vendored | Existing live ERP had intermittent browser/server-down routing issues |
| Documenso | upstream image | Composed, not vendored | Signing integration exists; production configuration must be revalidated |

## Working product scope represented in source

- Branded Floodman Hub, PWA, desktop workspace, mobile workspace and Full ERP launcher.
- Customer files, notes, tags, properties, documents and signed-file attachment.
- CSV and ZIP import workflows with preview/commit behavior.
- Estimates with searchable customers/properties, multiple editable headers, shared catalog, custom items, deposits, send/authorize/accept/payment/convert lifecycle and branded PDFs.
- Invoices with grouped lines, payment history, manual/card payment paths, send/void/delete lifecycle and branded PDFs.
- Square tokenized payments and card-on-file metadata.
- RoomFlow native/PWA integration, full snapshot synchronization, original Supabase import, workspace/company selection and actual layout capture.
- Calendar, jobs, inspections, assigned employees, conflict detection, tasks, announcements, notifications and time clock.
- Public encrypted Mobile API with device enrollment, rotating refresh tokens and revocation.
- Android native operations shell with bundled RoomFlow engine.
- Apple SwiftUI development shell with bundled RoomFlow engine.
- Competitor intelligence, messaging AI, receivables automation, customer portal, signing webhooks and local engineering lab.

## Highest-priority next actions

1. Put this handoff into a private Git repository and tag the untouched baseline.
2. Move all secrets and the RoomFlow Supabase defaults to environment configuration.
3. Build the derivative server image from a clean CI runner.
4. Restore a sanitized copy of live data into a staging Pterodactyl server.
5. Validate the v4.6.7-to-v4.6.9 test upgrade, Full ERP login, desktop, mobile, signing, payments, PDFs, RoomFlow import, restart, backup, and restore behavior.
6. Build Android alpha11 from the monorepo and run the complete acceptance checklist.
7. Build Apple alpha02 in Xcode, then close the feature-parity gap before TestFlight.
8. Replace JSON Office state with a transactional relational database before multi-user production scale.
9. Split the AIO container into independent deployable services when moving to the dedicated server.

## Do not assume

- Do not assume the latest v4.6.9 runtime was installed successfully.
- Do not assume the Android artifact currently on a phone exactly matches alpha11.
- Do not assume Full ERP browser routing is fixed until it is tested through the actual Tailscale `:8443` URL.
- Do not assume Apple signing is ready merely because source and workflows exist.
- Do not assume payment, email, Twilio, OpenAI, APNs or FCM credentials are configured.
