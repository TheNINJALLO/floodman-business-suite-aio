# RoomFlow server-side integration for Floodman Operations

RoomFlow remains the field estimator and property-layout tool. Version 3.0.0 sends its approved server-owned snapshot through the Floodman Orchestrator and into the Floodman ERP API.

## Resulting native Floodman ERP records

- RoomFlow customer -> Floodman ERP customer contact
- RoomFlow service property/job -> Floodman ERP service project
- RoomFlow estimate -> Floodman ERP estimate
- RoomFlow estimate lines -> Floodman ERP invoice items linked to the project
- Square/manual payment -> Floodman ERP payment linked to invoice, contact, and project

This gives the property/job a native Floodman ERP home for tasks, assigned employees, time logs, invoice items, payments, expenses, and reporting.

## Keep the security boundary

Do not call the Floodman Orchestrator from browser JavaScript or the public GitHub Pages build. Use the existing authenticated Supabase Edge Function boundary.

The server-side function must:

1. Validate the Supabase bearer token.
2. Load the user and verify organization membership.
3. Require the existing proposal/estimate capability.
4. Reload the saved customer, property, job, estimate, and line items from the database.
5. Recalculate totals in integer cents.
6. Build the canonical payload with `buildFloodmanEstimate()`.
7. HMAC-sign the request with `floodman-orchestrator-client.mjs`.
8. Store the returned `job_id` and `portal_url`.
9. Poll `getJob(job_id)` until the provider IDs are available.
10. Store `gauzy_contact_id`, `gauzy_project_id`, `gauzy_estimate_id`, later invoice IDs, and Square IDs in RoomFlow's external mapping tables.

## Supabase secrets

```text
FLOODMAN_ORCHESTRATOR_URL=https://api.floodman.com
FLOODMAN_ORCHESTRATOR_KEY_ID=v1
FLOODMAN_ORCHESTRATOR_HMAC_SECRET=<base64 secret from INTERNAL_HMAC_KEYS without the v1: prefix>
```

For the local Windows lab exposed through an approved HTTPS tunnel, use that exact tunnel origin. The HMAC secret must still stay in Supabase secrets.

## Integration example

```javascript
import { buildFloodmanEstimate } from './build-floodman-payload.mjs';
import { syncEstimate, getJob } from './floodman-orchestrator-client.mjs';

const payload = buildFloodmanEstimate(serverOwnedRoomFlowSnapshot);
const accepted = await syncEstimate(payload);

let workflow = null;
for (let attempt = 0; attempt < 30; attempt += 1) {
  workflow = await getJob(accepted.job_id);
  if (workflow?.provider_ids?.gauzy_estimate_id) break;
  await new Promise(resolve => setTimeout(resolve, 1000));
}

// Persist these mappings using the existing organization-owned mapping table.
const providerIds = workflow?.provider_ids || {};
```

## Migration from the Townsquare adapter

Do not delete Townsquare mapping history. Add the new provider `floodman_ops` and preserve the old IDs for audit and lookup. New revisions should use Floodman ERP after the cutover date; finalized historical Townsquare estimates and invoices remain read-only.

The payload builder and orchestrator both reject invalid or non-integer financial totals. Two independent arithmetic gates are dull machinery, but they keep invoices from evolving extra zeroes in the moonlight.
