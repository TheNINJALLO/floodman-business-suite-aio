# Floodman Operations 4.7.2 release notes

## Scope

Floodman Operations 4.7.2 is a server/web/Pterodactyl update that adds the provider-neutral AI call-intake boundary and coordinates safe draft work across Office, Full ERP/Gauzy mappings, RoomFlow, estimates, tasks, appointments, and staff notifications.

Mobile API remains `0.3.0-alpha11`; Android remains `0.4.0-alpha01`; iOS remains `0.1.0-alpha03`; RoomFlow remains pinned to `1f97817a52b916875e50cc6380c0d284072b8ce8`.

## Safety and behavior

- Provider events are signature-verified, size-limited, ordered, and deduplicated.
- Verified phone matches may resolve an existing customer; absent or ambiguous matches create a provisional/review-required context without guessing.
- Call-created estimates are unpublished, unpriced, and zero-dollar.
- Staff receive workspace/role-scoped in-app and mobile-feed alerts, plus configured email and best-effort SMS notices.
- Team accounts support email-as-username, password authentication, roles, disable state, and optional call-alert phone numbers.
- Mutable state remains under `DATA_DIR`, with an idempotent migration and documented backup/rollback procedure.

## Release boundary

This package does not replace the separate Twilio/Asterisk voice runtime. Voice recognition, pacing, interruption/barge-in, spoken-email rendering, selectable voices, and immediate hang-up behavior require separate live voice-stack work and call evidence.

## Deployment

Use the matched v4.7.2 runtime, launcher, and egg only. Preserve the v4.7.1 files for rollback. Create a Pterodactyl backup before upload, then require `FLOODMAN_SUITE_READY`, service health, restart persistence, and fictional signed-intake verification before wider use.
