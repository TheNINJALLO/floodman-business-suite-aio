# Executive handoff

## What was built

Floodman Operations is a single-company field-service and business-operations suite for waterproofing, foundation repair, restoration, mold work, demolition, inspections, and related projects. The system started as a clean all-in-one Gauzy test environment and grew into a Floodman-branded platform with its own Office workspace, customer records, estimating, invoicing, payments, document signing, RoomFlow field measurement, scheduling, receivables, messaging, competitor intelligence, PWA, Android app, and early iPhone/iPad app.

The current custom server baseline is v4.7.0. Android is v0.4.0-alpha01 (build 13). iOS remains v0.1.0-alpha03. RoomFlow is pinned to commit `1f97817a52b916875e50cc6380c0d284072b8ce8`.

## Business outcomes

The target workflow is one connected project record:

```text
Lead or imported customer
  -> customer file and service property
  -> inspection or scheduled job
  -> RoomFlow measurements and field layout
  -> grouped Floodman estimate
  -> electronic work authorization
  -> deposit and scheduling
  -> work, photos, notes, and change orders
  -> invoice and payments
  -> completion documents, warranty, and retained customer history
```

The approved estimate is a four-page Floodman document with customer/property details, a recommended project plan, grouped scope, actual RoomFlow layout, assumptions, exclusions, deposit, and approval path. The approved invoice is a two-page document with amount due, service property, estimate/job reference, contract activity, payment history, linked documents, and completion notes.

## Deployment model

The testing deployment is one Pterodactyl server using ports 9000 through 9004. Staff web surfaces are private through Tailscale. Public customer signing, payment pages, and the narrow native-app API are exposed through an HTTPS gateway. Native apps do not require Tailscale on every phone.

## Important status boundary

This handoff contains the complete Floodman custom source and current build files, not the live database. Android 0.4.0-alpha01 passes its local unsigned compiler/package gate and iOS alpha03 passes Windows source readiness, but no native device, iOS Xcode, signing/store, or live v4.7.0 staging pass is claimed.

## Recommended migration strategy

1. Put this folder into a new private Git repository.
2. Tag the untouched handoff as `handoff-v4.6.7`.
3. Run all static verification before editing.
4. Build the derivative server image on the current AIO base.
5. Run the Android workflow and physical-device acceptance test.
6. Run the iOS simulator workflow.
7. Create a clean staging Pterodactyl server and restore a sanitized backup.
8. Only after staging passes should the live server move from overlay ZIP deployment to a source-built image.
