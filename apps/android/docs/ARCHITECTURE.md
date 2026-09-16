# Android architecture

```text
Floodman Android app
  | HTTPS only
  v
https://api.oninetwork.com/mobile-api/
  | external HTTPS proxy, public device-authenticated path only
  v
Floodman API gateway on allocation 9004
  | /mobile-api/*
  v
Floodman Office Mobile API on 127.0.0.1:8700
  | role, device, and workflow authorization
  v
Floodman customers, properties, schedules, estimates, invoices,
payments, documents, RoomFlow mappings, tasks, and time data
```

The staff PWA remains separate and protected:

```text
Approved staff browser through the HTTPS proxy access policy
  v
https://floodman.oninetwork.com
  v
Floodman PWA and full RoomFlow drawing workspace
```

The Android app connects directly to the external HTTPS proxy. The server package does not install or invoke an overlay-network client. The proxy must expose `/mobile-api/` while protecting workflow administration and API documentation.

## RoomFlow

The Android app bundles the pinned Floodman RoomFlow engine locally and opens it through a secure `appassets.androidplatform.net` origin. The engine includes the guided workflow, 2D sketching, custom room shapes, camera/AR tools, 3D review, scope, materials, costing, and document tools. Floodman authentication replaces the old RoomFlow/Supabase login. The Mobile API stores the full snapshot, customer/property mapping, grouped estimate sections, reusable catalog items, and the actual captured layout image used in estimate PDFs.
