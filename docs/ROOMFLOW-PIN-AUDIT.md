# RoomFlow pinned-source and package audit

Audit date: 2026-08-12

## Identity and provenance

- Repository: `https://github.com/TheNINJALLO/roomflow.git`
- Required and verified commit: `1f97817a52b916875e50cc6380c0d284072b8ce8`
- Verified checkout: 1,032 tracked files, no deleted tracked files, clean worktree
- Release identities are Floodman server `4.6.10`, Android `0.3.0-alpha12`, and iOS `0.1.0-alpha03`. The web-only server bump does not rebuild or relabel the native candidates; they retain their recorded v4.6.9 preparation metadata and the exact RoomFlow pin. Android build evidence remains historical while iOS compilation remains a macOS gate.
- The pin was not advanced. The checkout remains ignored and is not copied into source control.

`scripts/fetch-roomflow.ps1` now enables Git long-path handling, checks every Git exit code, refuses to overwrite an unknown directory or a dirty checkout, and verifies the resulting commit and file set. This corrects the previous Windows behavior where a failed checkout could still print a success message.

## Feature and packaging matrix

| Pinned RoomFlow capability | Embedded server | Android | iOS | Floodman integration behavior |
|---|---|---|---|---|
| Guided estimator and jobs dashboard | Included | Included | Included | Shared jobs are restored into the upstream local job model. |
| 2D rooms, custom shapes, walls, openings, fixtures, utilities, and measurements | Included | Included | Included | The upstream `app.js` and `spatial-engine.js` are preserved. |
| Camera/manual measurements and WebAR workflow | Included | Included | Included | Native shells grant camera capture to the local trusted RoomFlow origin; manual fallback remains upstream. |
| 3D review | Included | Included | Included | Pinned Three.js and OrbitControls are vendored in native packages. |
| Material catalog, scope, quantities, costing, margin, tax, and commission | Included | Included | Included | Floodman catalog records are mapped into the upstream catalog model. |
| Proposal, invoice, work order, and document workflow | Included | Included | Included | Native Save sends grouped estimate sections and the actual captured layout to the Mobile API. |
| Jobs, recovery/trash, diagnostics, user guide, and regression helpers | Included | Included | Included | `cost-tests.js`, previously omitted from both native copy lists despite being referenced by `index.html`, is now required and packaged. |
| Original Supabase organizations, customers, jobs, layouts, pricing, snapshots, catalog, estimates, and lines | Import supported | Import UI and bridge | Import UI | The one-time importer authenticates as the original user and lets Supabase RLS determine readable rows. Durable native operation then uses Floodman's Mobile API. |
| Upstream Supabase login/sync in the web application | Disabled in embedded mode | Replaced | Replaced | Staff keep one Floodman session. No service-role key or second durable native data store is introduced. |
| Townsquare browser automation, Tracker, Zapier, and OutreachGenius infrastructure | Source retained; legacy auto-load disabled | Not embedded | Not embedded | These are external integration surfaces, not estimator engine prerequisites. Floodman native shells use the authenticated Mobile API and do not ship upstream credentials or browser automation. |

All three preparation paths now validate every required core module and every local `src`/`href` reference. The server bundle carries `.floodman-roomflow.json`; native bundles carry package-visible `floodman-roomflow.json`. Both record release, pin, attribution, and time-zone metadata.

## Reviewed compatibility overlay

The pinned `app.js` contains two top-level functions named `renderJobsList`: one renders the toolbar job database and the later function renders the dashboard. Chromium executes the pinned source and its upstream browser smoke passes, but Node's syntax gate rejects the duplicate declaration and the later declaration prevents explicit refresh of both surfaces.

Floodman keeps the upstream checkout untouched and applies a deterministic package-time overlay:

- the toolbar implementation becomes `renderLegacyJobsList`;
- callers that need a general refresh use `refreshJobLists`, which renders both the toolbar list and dashboard;
- the dashboard keeps `renderJobsList` and `window.renderRoomFlowJobsList` compatibility.

The overlay is idempotent, rejects an unexpected source layout, passes `node --check`, and passed a local Edge test that populated, opened, rendered, and closed the legacy job database.

## Original Supabase import contract

The importer reads the pinned schema's RLS-protected data using the signed-in user's Bearer token:

- `organization_members` and `organizations`
- organization-scoped `customers`, `jobs`, `estimate_catalog_items`, `estimates`
- `job_project_snapshots` and `job_costing_snapshots`
- job-scoped legacy `job_layouts` and `job_pricing`
- estimate-scoped `estimate_lines`

The schema audit verified these tables and their RLS enablement at the pin. A mocked HTTP contract test verified auth, membership filtering, organization filtering, user-token propagation, layout import, and the estimate-line query without live credentials. The password and returned access token were absent from the persisted Office snapshot. A changed second dataset updated the same source-mapped customer, job, catalog, estimate, and workspace records without duplicates while retaining local-only customer fields.

Imported geometry is not represented as an actual field-layout image. Historical records remain marked `layout_capture_required`; opening and saving the job captures the real canvas image for estimate PDFs.

## Recorded evidence

- `python scripts/verify_roomflow_pin.py` — passed pin, clean checkout, 1,032 tracked files, package inputs, schema/RLS, and importer contract.
- `python scripts/validate_roomflow_web.py` — passed source, embedded-server, Android, and iOS bundles.
- Upstream Node suite — 35/35 passed across lead normalization, Townsquare core/security/station, idempotency, mappings, and protected credential behavior.
- Upstream local Edge suite — 9/9 passed: core browser, estimate builder, header/mobile layout, leads, More layout, shared jobs/download/upload, Tracker deletion, and user guide.
- Prepared compatibility overlay — Node syntax passed and local Edge rendered/closed both job-list surfaces without a JavaScript error.
- `server/tests/roomflow_supabase_import_smoke.py` — passed repeat update, workspace linkage, current and legacy snapshots, actual-layout policy, query scoping, and credential non-persistence.
- 2026-08-14 native candidate refresh — Android alpha12 and iOS alpha03 bundles were regenerated from the same clean pin with Floodman 4.6.9 metadata. Native customer/property lookup now sends the selected Floodman workspace, the server isolation regression passed, and Android APK/AAB inspection verified the embedded pin.

Live Supabase acceptance remains an operator action because no user credential was supplied or stored. The deterministic import and HTTP contract are locally verified; a production login is not claimed.
