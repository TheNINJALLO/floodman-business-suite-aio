# Floodman RoomFlow in Android

The Floodman Android shell launches a pinned local copy of the RoomFlow field-estimating engine under Android WebView's secure app-assets origin. It does not require the browser PWA during capture.

## Cloud bootstrap

On launch, Android downloads a device-authenticated Floodman bootstrap containing:

- imported and native RoomFlow jobs
- complete saved project snapshots
- customer and service-property relationships
- linked estimate records and grouped sections
- shared Floodman/RoomFlow catalog items
- prior import status

The bridge restores these records into RoomFlow's local job store without overwriting a locally pending unsynchronized edit.


## Floodman workspaces

The native bridge receives the selected Floodman workspace before RoomFlow restores any job. Imported Supabase organizations appear in the company selector automatically after the idempotent import. The selector changes the active workspace through the encrypted Mobile API, and the plus button creates a new Floodman workspace without exposing Supabase credentials or direct database access to the WebView. Jobs, customer/property links, estimates, and imported catalog items remain scoped to the selected workspace.

## Original Supabase import

Open **Cloud** in RoomFlow and enter the former RoomFlow Supabase email and password. The matching Floodman v4.6.3 server authenticates as that user and copies only rows visible through the existing Supabase access policies. The password and access token are not persisted.

The import may be repeated. Stable source identifiers update existing Floodman records rather than duplicating them.

## Layouts and PDFs

Imported geometry is restored immediately. Historical jobs may not contain a rendered JPEG, so they are labeled as needing layout capture. Open the job and press **Save** once. The Android bridge captures the actual 2D or 3D canvas and synchronizes it to Floodman. Estimate PDFs use that saved image. Without a capture, the PDF states that no saved RoomFlow layout is attached.
