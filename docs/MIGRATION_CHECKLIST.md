# Migration checklist: Pterodactyl to VS Code/Codex and dedicated server

## Source-control bootstrap

- [ ] Create a private repository.
- [ ] Import the handoff without modifications.
- [ ] Run `python3 scripts/verify_repo.py`.
- [ ] Commit and tag `handoff-v4.6.7`.
- [ ] Enable branch protection and required CI.
- [ ] Add a secret scanner and dependency updater.

## Secret extraction

- [ ] Rotate any credentials exposed in screenshots or prior chat copy/paste.
- [ ] Move RoomFlow Supabase URL/public key to environment configuration.
- [ ] Move all Square, Twilio, OpenAI, Documenso and Gauzy credentials to secret stores.
- [ ] Configure Android signing and Apple signing outside the repository.
- [ ] Confirm `.gitignore` and CI scans block customer data and auth keys.

## Reproducible builds

- [ ] Pin upstream image digests.
- [ ] Build the derivative server image from a clean runner.
- [ ] Build the complete AIO image for comparison.
- [ ] Generate SBOMs and vulnerability reports.
- [x] Build Android 0.4.0-alpha01/build 13 locally without release signing.
- [ ] Build Apple alpha03 simulator on macOS/Xcode.
- [ ] Record checksums and runner/tool versions.

## Data inventory

- [ ] Back up embedded PostgreSQL.
- [ ] Back up Office state, uploads, documents and RoomFlow layouts.
- [ ] Back up Gauzy files/imports.
- [ ] Back up Documenso data and signing secrets.
- [ ] Export external mappings and webhook configuration.
- [ ] Count contacts, properties, estimates, invoices, payments, documents and RoomFlow jobs.
- [ ] Test a restore into isolated staging.

## Staging acceptance

- [ ] Clean startup and second restart.
- [ ] `/office-health/live` and `/mobile-api/v1/health` return expected versions.
- [ ] Automatic, desktop and mobile workspaces render correctly.
- [ ] Full ERP signed-out and signed-in routes work through Tailscale `:8443`.
- [ ] Customer search works with 1,000+ records.
- [ ] CSV and ZIP import preview/commit works.
- [ ] Estimate grouped headers are editable.
- [ ] Category project plan populates and remains editable.
- [ ] Real RoomFlow layout appears in PDF.
- [ ] Work authorization signs and attaches to customer/job.
- [ ] Square sandbox online/card-on-file/manual payment paths reconcile.
- [ ] Invoice converts, sends, receives payment and becomes a receipt.
- [ ] Calendar assignments/conflicts/tasks/time clock work.
- [ ] Android repeats core lifecycle without Tailscale.
- [ ] Apple simulator opens and authenticates.

## Dedicated-server cutover

- [ ] Provision separate services and PostgreSQL roles.
- [ ] Configure real reverse proxy and certificates.
- [ ] Establish office/api/sign subdomains.
- [ ] Configure monitoring, backups and alerts.
- [ ] Set a maintenance window and rollback point.
- [ ] Perform final data export/import and reconciliation.
- [ ] Update webhook and mobile API origins.
- [ ] Keep old Pterodactyl deployment read-only until acceptance completes.
- [ ] Document cutover evidence and rollback result.
