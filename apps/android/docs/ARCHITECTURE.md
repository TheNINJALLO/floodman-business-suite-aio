# Android architecture

```text
Floodman Android app
  | HTTPS only
  v
https://<Floodman Funnel host>/mobile-api
  | Tailscale Funnel, public path only
  v
Floodman public gateway on 127.0.0.1:9010
  | /mobile-api/*
  v
Floodman Office Mobile API on 127.0.0.1:8700
  | role, device, and workflow authorization
  v
Floodman customers, properties, schedules, estimates, invoices,
payments, documents, RoomFlow mappings, tasks, and time data
```

The staff PWA remains separate and private:

```text
Approved Tailscale staff device
  v
https://<Floodman node>.ts.net:8443
  v
Floodman PWA and full RoomFlow drawing workspace
```

The Android app does not install or invoke Tailscale. Funnel is currently the server-side HTTPS gateway. The API origin can later move to `https://api.floodman.com/mobile-api/` without changing the app architecture.

## RoomFlow

The Android app bundles the pinned Floodman RoomFlow engine locally and opens it through a secure `appassets.androidplatform.net` origin. The engine includes the guided workflow, 2D sketching, custom room shapes, camera/AR tools, 3D review, scope, materials, costing, and document tools. Floodman authentication replaces the old RoomFlow/Supabase login. The Mobile API stores the full snapshot, customer/property mapping, grouped estimate sections, reusable catalog items, and the actual captured layout image used in estimate PDFs.
