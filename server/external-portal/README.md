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
5. Upload photos to that job in the existing portal. Capture and save the actual
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
only by the hosting account. Never commit it. Install `includes/floodman_bridge.php`
and `api/floodman.php`. PHP must support PDO SQLite; the existing jobs table must
have its unique `client_job_id` index. This connector never calls legacy schema
migration routines.

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

Run the `portal_*_smoke.py` tests under `server/tests`, the existing call
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
