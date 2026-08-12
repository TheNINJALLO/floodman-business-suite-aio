# Floodman Operations v4.6.0 and Android 0.3.0-alpha10

This cumulative matched release repairs the original RoomFlow migration path and prevents Android from treating server error responses as estimate or invoice PDFs.

## Server changes

- Adds a secure, user-authenticated importer for the original RoomFlow Supabase data.
- Imports accessible RoomFlow customers, jobs, project snapshots, layout geometry, costing snapshots, estimate catalog items, estimates, grouped sections, and line items.
- Keeps Supabase authentication credentials and access tokens in memory only for the import request.
- Uses deterministic source mappings so repeat imports update matched Floodman records rather than intentionally duplicating them.
- Preserves existing Floodman contact and property fields when the corresponding imported field is blank.
- Adds a complete RoomFlow bootstrap endpoint for Android.
- Returns full project snapshots, customer and property relationships, linked estimates, grouped estimate sections, catalog data, and import history.
- Marks imported historical layouts as requiring a real Android canvas capture before they are embedded in customer PDFs.
- Advertises the minimum compatible Android version and required feature capabilities through the health and configuration endpoints.

## Android changes

- Restores complete RoomFlow job snapshots instead of discarding geometry, costing, links, and estimate data.
- Adds the Cloud import flow for the original RoomFlow Supabase login.
- Loads imported RoomFlow jobs and the shared Floodman catalog into the bundled RoomFlow workspace.
- Keeps imported jobs linked to their Floodman IDs so later saves update the same records.
- Captures the real RoomFlow canvas as a JPEG when staff saves a job.
- Verifies estimate and invoice downloads are successful PDF responses before opening them.
- Rejects JSON, HTML, and incompatible-server responses with a readable message.
- Blocks sign-in when the server does not provide the v4.6.0 capability contract.

## Data safety

The launcher and importer do not intentionally delete PostgreSQL data, Floodman customers, service properties, estimates, invoices, payments, documents, signed records, RoomFlow data, Tailscale identity, Funnel configuration, or backups. The original Supabase records remain in place.

## Build boundary

The Floodman server runtime and launcher have passed local validation and smoke tests. The Android source package has passed source-level validation. The included GitHub Actions workflow remains the authoritative Gradle, lint, APK, and Android App Bundle build gate.
