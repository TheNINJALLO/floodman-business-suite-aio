# Floodman Operations Android 0.3.0-alpha11

## Alpha10 RoomFlow migration and document correction

- Adds the matched Floodman v4.6.3 capability check before login.
- Adds a secure **Cloud** import inside bundled RoomFlow for the original Supabase account.
- Restores imported customers, jobs, snapshots, measurements, costing data, catalog items, estimates, grouped sections, and estimate lines.
- Preserves the full RoomFlow snapshot in Android models instead of discarding it during JSON decoding.
- Links imported local RoomFlow jobs to their Floodman job IDs so later saves update the same records.
- Seeds the bundled RoomFlow catalog from the shared Floodman catalog returned by the server bootstrap.
- Marks historical imported jobs that need one real layout capture for the estimate PDF.
- Validates estimate and invoice PDF responses by HTTP status, content type, and `%PDF-` signature.
- Shows a clear matched-server upgrade message rather than opening `{"detail":"Not Found"}` as a document.
- Keeps non-PDF document downloads available through the normal document viewer.

## Security boundary

- The old direct Supabase scripts and login remain removed from the WebView.
- The RoomFlow password is cleared from the form immediately and is not placed in local storage.
- Credentials travel only through Floodman's encrypted HTTPS Mobile API for the import request.
- The server authenticates to Supabase as the original RoomFlow user and remains subject to Supabase row-level security.
- No Supabase service-role key is embedded in the APK.

## Retained from alpha09

- AndroidX predictive-back-compatible RoomFlow navigation.
- Full native estimate and invoice lifecycle.
- Editable grouped headers and shared catalog.
- Calendar, employee assignment, tasks, documents, announcements, notifications, time clock, and dark mode.
- Actual RoomFlow layout capture and synchronization.

## Alpha11 RoomFlow workspace repair

- Restores imported RoomFlow Supabase organizations as selectable Floodman workspaces.
- Automatically applies the selected company to RoomFlow state before jobs and estimates load.
- Adds an encrypted native workspace selector and working Create Workspace action.
- Keeps jobs, customers, properties, estimates, and catalog items isolated by workspace.
- Requires the matched Floodman server v4.6.3 capability `roomflow.workspaces.v1`.
