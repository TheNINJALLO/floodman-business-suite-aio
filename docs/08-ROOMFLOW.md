# RoomFlow integration

## Pin

```text
Repository: https://github.com/TheNINJALLO/roomflow.git
Commit: 1f97817a52b916875e50cc6380c0d284072b8ce8
```

The repository is not duplicated in this source archive. Fetch it through the provided scripts. This keeps provenance clear and prevents an accidental unreviewed update.

The 2026-08-12 source, feature, package, and Supabase evidence is recorded in `ROOMFLOW-PIN-AUDIT.md`.

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
- Android and iOS package the complete pinned estimator runtime, but replace the upstream Supabase/Townsquare browser session layers with the authenticated Floodman Mobile API.
