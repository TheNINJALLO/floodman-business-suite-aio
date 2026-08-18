# Floodman Android 0.4.0-alpha01 (build 13) acceptance checklist

## Matched deployment

1. Install the current Floodman Operations runtime v4.6.9 and wait for `FLOODMAN_SUITE_READY` (v4.6.3 remains the minimum capability baseline, not the current release).
2. With Tailscale disabled on the phone, open `/mobile-api/v1/health` and confirm API version `0.3.0-alpha11`.
3. Install the 0.4.0-alpha01/build-13 debug APK and sign in.
4. Confirm an older server is rejected with the matched-server message rather than opening JSON as a document.


## Workspace and organization repair

1. Open **More → Floodman RoomFlow** and confirm the top company selector is populated.
2. Run **Cloud → Import original RoomFlow** once after installing the matched server.
3. Confirm the original Supabase company name becomes selected automatically.
4. Switch between companies and confirm only that workspace’s jobs and imported catalog records appear.
5. Search for a customer/property that belongs only to another company and confirm it is not offered in the active company.
6. Tap the plus button, create a temporary workspace, and confirm it becomes active immediately.
7. Switch back to the imported company before continuing production work.

## Original RoomFlow import

1. Open **More → Floodman RoomFlow → Cloud**.
2. Enter the original RoomFlow Supabase login.
3. Confirm the import reports customer, job, estimate, and catalog counts.
4. Confirm existing RoomFlow jobs appear in the Jobs dashboard.
5. Open a job and confirm rooms, measurements, customer, property, estimate sections, and catalog data are restored.
6. Press **Save** and confirm the same job and estimate update instead of duplicating.
7. Open the estimate PDF and confirm the actual saved RoomFlow layout appears after the first capture.

## Estimates and invoices

1. Open an imported estimate and edit its grouped headers and lines.
2. View its PDF.
3. Send, authorize, accept, activate the deposit, record or take payment, and convert it to an invoice.
4. Open and edit the invoice, view its PDF, send it, and record payment.
5. Confirm JSON or HTML responses are never passed to Android's PDF viewer.

## Existing modules

Confirm customers, properties, calendar, employee assignment, tasks, documents, notifications, RoomFlow, time clock, and system/light/dark appearance modes remain operational.
