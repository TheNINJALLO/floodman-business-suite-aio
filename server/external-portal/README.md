# Floodman externally hosted photo portal

This additive overlay connects the existing PHP/SQLite portal at `public_html/portal`
to the shared Voice AIO and Business Suite. Photos stay on the existing host.
No database migration, existing customer import, staff credential replacement, or
customer message is performed by installing this overlay.

## Staff workflow

1. Open Office -> Calls and select a call.
2. Review the name, email, phone, and full service address. Choose an existing
   customer when appropriate; the property list contains only that customer's
   properties in the current workspace.
3. Select **Approve and create customer files**. Local customer/property,
   RoomFlow, and an unpublished/unpriced estimate are committed first.
4. A durable retry worker creates or links the portal job and ERP customer/project.
   The call shows the connection status and a staff photo-portal link. ERP email
   ambiguity stops synchronization for staff review. Approval is not telephone
   ownership verification or messaging consent.
5. Open **Photo Portal** in the ERP sidebar and select the job. View its gallery
   without a second portal login, or upload a photo with property-management
   permission. Uploads are stored under DATA_DIR first and retried safely; the
   temporary local copy is released only after the hosted original is verified.
   Owners/administrators may browse unlinked legacy jobs. Other staff see only
   jobs linked to their selected workspace and organization. Capture and save the actual
   RoomFlow layout. Price/review the estimate and explicitly send it using the
   existing estimate workflow. Its customer page then includes a signed gallery
   of that job's photos and saved floor plan. No invented diagram is generated.

The gallery includes all photos on the linked portal job; do not add internal-only
images there if they must not appear in a sent estimate. Internal notes, receipts,
other customers' photos, and staff authentication credentials are not returned by
the connector. Existing portal photo URLs and staff/mobile login behavior are not
changed. This is not a replacement for reviewing legacy portal media permissions.

## Installation

Back up existing portal source/database. Install `data/.htaccess`, then create
`data/floodman-suite` and install its `.htaccess` before adding credentials.
Confirm the private directory and the database return HTTP 403 without login.
Create private `data/floodman-suite/config.php` containing a generated shared
secret (at least 32 characters) in a PHP array with the key `secret`, readable
only by the hosting account. Never commit it. Install `includes/floodman_bridge.php`,
`includes/floodman_catalog.php`, `includes/floodman_job_tools.php`, then
`api/floodman.php`. The optional shared
theme updates `includes/layout.php`, `login.php`, `assets/floodman-erp.css`,
and `sw.js`; compare against and back up the existing versions before replacing.
PHP must support PDO SQLite; the existing jobs table must
have its unique `client_job_id` index. This connector never calls legacy schema
migration routines. Staff uploads require the existing photos table's
`client_photo_id` and `client_job_id` fields and unique `(job_id,client_photo_id)`
index. Staff image links expire after ten minutes; customer links after one hour.

Office, Hub, and the installed web app choose their layout automatically before
first paint. Old manual mode preferences are ignored, and resizing preserves
the current job or unsaved form. Existing desktop/mobile URLs remain aliases.

Set these in the shared server's private `DATA_DIR/runtime.env`:

```dotenv
CALL_INTAKE_APPROVAL_REQUIRED=true
FLOODMAN_PORTAL_API_URL=https://floodmanblog.com/portal/api/floodman.php
FLOODMAN_PORTAL_API_TOKEN=<same generated secret>
```

FTPS credentials are deployment-only; never put them in browser code or the image.
The runtime communicates over HTTPS using timestamped HMAC-SHA256. Customer
gallery URLs expire in one hour and are regenerated when the customer reopens the
estimate. Keep the signing key private. The gallery's allowed embedding origin
is `https://floodman.oninetwork.com`; review it if changing the Office domain.

## Verification and rollback

### ERP job tools

Photo Portal retains five job sections: photos, videos, staff notes, receipts,
and contents inventory. Staff can add multiple photos, capture from a phone
camera, upload videos up to 100 MB, record receipt vendor/amount/notes, print
receipt images and totals using the browser's Save PDF option, and maintain
contents items with linked photos. Receipt entry accepts one image at a time so
its amount is not accidentally counted once per scan in a batch. Photos/receipt
images support JPEG, PNG, WebP and GIF up to 12 MB each. Video support is MP4,
QuickTime/MOV, WebM and AVI; playback also depends on the browser's codec support.

Existing job metadata, captions, topics, notes, receipt details and inventory
can be edited by property managers. Technicians gain `portal.upload` for additions
to jobs they can access, without gaining removal, global legacy-job access or
marketing privileges. Original posting/advanced tools remain available under
the collapsed **Original portal tools** link using the existing portal staff
login. New uploads do not publish images for marketing. Editing portal job
metadata does not silently overwrite the canonical ERP customer/property.

All writes are staged as `portal_actions` in the existing local Office store
before remote synchronization. Interrupted multi-chunk uploads resume from the
job's Saved changes and uploads section after selecting the original file.
Completed files continue synchronizing even after the browser closes; do not
close the page before it confirms they are saved locally. No browser offline
camera queue is claimed. Outstanding local uploads are limited to 500 MB and
100 operations per actor. Videos advance one 4 MB remote chunk per worker pass
to preserve call-intake responsiveness. SHA-256 verifies every hosted original.

The existing portal tables are used without schema migrations. Private
`operation-<uuid>.json` journals record before/after rows, conflict revisions,
and acknowledgements. A lost acknowledgement is replay-safe; conflicting edits
require review. Removing an item hides its database row but retains the original
file and private recovery record. Recovery requires an administrator to review
that journal against current rows; there is no automatic destructive rollback.
Staff receipt/video links have distinct, ten-minute signatures. Customer
estimate galleries still contain only project photos and floor plans, never
staff receipts or notes. Legacy raw media URLs retain the original portal's
access behavior; this update does not retroactively privatize those URLs.

Each native section shows the newest 500 entries with a notice when truncated;
the original portal retains older entries. Receipt totals cover the whole job.
Large truncated jobs should use the original portal for a complete image export.

### Release checks

Run `photo_portal_smoke.py`, `adaptive_portal_browser_smoke.py`, the
`portal_*_smoke.py` tests under `server/tests`, the existing call
intake tests, and `scripts/test_external_portal.py` in the repository test venv.
The PHP test uses a pinned disposable Docker image and fictional data; browser
tests include narrow/mobile/desktop layouts. All live setup health checks are
read-only. Final operational acceptance requires a staff-approved real call,
field photos/layout, and an explicitly reviewed/sent estimate.

The separate `containers/unified-portal` image is an immutable patch on the
existing shared Voice + Suite image, retaining version 4.7.3, mobile contracts,
and RoomFlow's pin. It refreshes the bundled runtime manifest and keeps the owner
recovery and placeholder-route compatibility fixes. Standalone runtime archives
remain pinned to immutable Git revisions and checksums; historical download
revisions remain available. This patch does not advance a native release version.

Keep the previous exact image digest, private runtime configuration, and a
validated Office state snapshot before deployment. Roll back the image and
configuration without replacing customer state by default. Restore a state backup
only after separately preserving any new staff work and choosing a restore point.
Disable the connector by removing its API URL/key and restarting Office; retain
all customer records and portal database protections. No database rollback or
destructive migration is required.
