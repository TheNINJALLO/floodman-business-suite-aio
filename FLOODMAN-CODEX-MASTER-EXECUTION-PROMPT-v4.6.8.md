# Floodman Codex master execution prompt v4.6.8

## Mission

Continue the checked-in Floodman Operations handoff without restarting completed work. Work through the highest-priority unblocked item in `docs/TASK-STATUS.md`, preserve release identity and safety boundaries, and leave reproducible evidence in the task, test, blocker, decision, checksum, and Git records.

The active release identities are:

- server `4.6.8`
- Mobile API and Android `0.3.0-alpha11`
- iOS `0.1.0-alpha02`
- RoomFlow commit `1f97817a52b916875e50cc6380c0d284072b8ce8`
- business time zone `America/Detroit`, with persisted timestamps in UTC

`AGENTS.md` is authoritative. This file narrows execution behavior but does not relax any repository instruction.

### Scoped v4.6.8 test-release authorization

On 2026-08-13 the user explicitly authorized the server/Pterodactyl v4.6.8 test build while deferring Android and iOS builds. This authorization permits the distinct server identity and local non-native artifacts only. Android remains `0.3.0-alpha11`, iOS remains `0.1.0-alpha02`, and their deferred compiler/device gates must remain recorded as `BLOCKED` or `NOT RUN`. It does not authorize production deployment, signing, store upload, live-data access, or a claim that the full release gates passed.

## Task selection and evidence

1. Read `AGENTS.md`, this file, `docs/TASK-STATUS.md`, `docs/CODEX-EXECUTION-PLAN.md`, `docs/BLOCKERS.md`, `docs/TEST-MATRIX.md`, and `docs/DECISIONS.md` before editing.
2. Inspect Git status and recent history. Preserve unrelated or pre-existing work.
3. Select the lowest priority number and then the earliest task whose state is `FAILED`, `IN PROGRESS`, or `NOT STARTED`, provided it has no unresolved blocking dependency.
4. Do not rerun a completed task unless a dependency changed or its recorded evidence is insufficient. Record the reason before reopening it.
5. A test is `PASS` only when its command and result were observed in the current repository or an immutable CI record is linked. Historical prose is not a fresh pass.
6. Use `BLOCKED` only for an unavailable external system, credential, platform, device, approval, or live-data boundary. Continue with other unblocked tasks.
7. Keep release identities unchanged unless every release gate in `AGENTS.md` has passed and a version change is explicitly approved.

## Current product acceptance target

- All custom web pages load without uncaught runtime errors in their supported routes and viewport classes.
- Navigation, forms, tables, public customer flows, desktop/mobile workspaces, and PWA states remain usable and consistently branded.
- Dialogs, drawers, popovers, menus, notices, loading masks, and error overlays do not permanently cover actionable content. Every persistent overlay has an obvious close/cancel route, Escape handling where appropriate, focus behavior, and a bounded responsive layout.
- RoomFlow uses the pinned upstream commit, preserves its available field workflow, and crosses the versioned Floodman bridge without privileged direct writes.
- Supabase import authenticates with the original RoomFlow user, respects row-level security, uses stable source identifiers, and updates rather than duplicates on repeat import.
- Android is ready for the recorded clean Gradle gates and physical-device acceptance.
- iOS is ready for Xcode project generation and unsigned simulator compilation; signing and TestFlight remain separate guarded gates.

## Mandatory safety boundaries

Pause and request explicit approval before any of the following:

- deleting, resetting, recreating, migrating, or writing a live database;
- importing or inspecting live customer, payment, signing, Tailscale, or production-log data;
- changing RoomFlow away from its pinned commit;
- changing a release version or minimum native-app version;
- exposing a staff, administration, database, engineering, Mailpit, or internal-service surface publicly;
- weakening HTTPS, token rotation, device proof, webhook verification, rate limits, row-level security, or payment tokenization;
- using production payment, messaging, email, AI, Apple, Android-signing, or Tailscale credentials;
- deploying to production, uploading TestFlight/Play artifacts, publishing images, pushing Git branches, or opening a pull request;
- modifying historical ZIPs or representing synthetic RoomFlow geometry as measured field data.

Safe local source edits, tests with fictional or temporary data, dependency inspection, pinned-source fetching, unsigned builds, and documentation/commit updates continue automatically.

## Milestone discipline

For each coherent milestone:

1. update the task state and evidence;
2. update `docs/TEST-MATRIX.md` with exact commands and outcomes;
3. update blockers and decisions when facts change;
4. refresh generated inventories and component manifests/checksums affected by source changes;
5. run proportionate verification;
6. review the diff for secrets and unintended files;
7. create an intentional local commit.

Never claim live-node, device, macOS, signing, provider, or production acceptance from source inspection alone.
