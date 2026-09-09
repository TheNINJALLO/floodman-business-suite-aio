# Current project status

## Version status

| Component | Version | Source status | Live validation status |
|---|---:|---|---|
| Floodman custom server | 4.7.2 | Signed AI call intake, canonical safe-draft projection, team administration, and multi-channel staff notifications pass the 14-program local server/browser suite | Live Pterodactyl update, provider signing, and end-to-end voice-stack acceptance are in progress |
| Pterodactyl launcher | 4.7.2 | New immutable runtime, launcher, egg, and checksums are prepared without changing v4.7.1 artifacts | Requires backed-up upload, readiness, restart persistence, and signed fictional-intake checks on the intended panel server |
| Android app | 0.4.0-alpha01 (build 13) | Fresh JDK 17/Gradle 8.13 compile, 8/8 tests, lint, APK and AAB gates pass with `https://api.oninetwork.com/mobile-api/` embedded | Debug APK is ready for local testing; release outputs are unsigned and device/store gates remain external |
| Apple app | 0.1.0-alpha03 | Windows source readiness passes after the 44-point RoomFlow close-target update | Current-source Xcode simulator compilation is BLK-015; signing/TestFlight and device gates remain external |
| RoomFlow | `1f97817a52b916875e50cc6380c0d284072b8ce8` | Exact-pin metadata, release assets, native bridges, and import/sync contracts verify | Physical capture and staging synchronization remain BLK-006/BLK-005 |
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
- Signed AI call intake with canonical customer/property/job context, RoomFlow and unpublished estimate drafts, tasks, appointments, staff screen-pop, and email/SMS/mobile-feed alerts.

## Highest-priority next actions

1. Deploy the matched v4.7.2 runtime and launcher using `deployment/pterodactyl/UPDATE-v4.7.2.md`, after a complete Pterodactyl backup.
2. Validate Full ERP login, desktop/mobile workspaces, one signed fictional call intake, screen-pop/queue, notifications, RoomFlow draft linkage, restart persistence, and rollback readiness.
3. Run the final WEB-007 commit through the unsigned Apple simulator workflow to close BLK-015.
4. Install Android alpha01 on approved Depth and non-Depth devices and run the full staging HTTPS acceptance checklist; repeat RoomPlan/LiDAR/ARKit checks on iPhone/iPad.
5. Produce and review a current critical/high container advisory report before any image or production release.
6. Replace JSON Office state with a transactional relational database only after an approved backup/migration/restore plan.
7. Split the AIO container into independent deployable services when moving to the dedicated server.

## Do not assume

- Do not assume the v4.7.2 runtime is live until panel startup and health evidence is captured.
- Do not mix v4.7.2 runtime, launcher, or egg files with any v4.7.1 artifact; v4.7.1 remains rollback evidence.
- Do not assume the locally built Android 0.4.0-alpha01 artifact has passed physical-device or staging acceptance.
- Do not assume Full ERP browser routing is production-ready until it is tested through `https://floodman.oninetwork.com` with the actual HTTPS proxy and staff access policy.
- Do not assume Apple signing is ready merely because source and workflows exist.
- Do not assume payment, email, Twilio, OpenAI, APNs or FCM credentials are configured.
