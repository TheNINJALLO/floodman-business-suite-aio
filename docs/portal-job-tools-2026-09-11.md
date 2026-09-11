# Photo Portal job tools patch

Server contract remains 4.7.3; no native API, RoomFlow pin, voice routing, consent,
payment verification or production database schema changes.

Adds ERP-native photo batches/camera capture, chunked video upload, staff notes,
receipts with totals and browser print/PDF, contents inventory with linked photos,
and permission-checked edits/removals. Local-first operation records, stable
upload IDs, checksum verification and private recovery journals preserve data
during retries, restart and removal. Staff-only receipts and notes are never
added to customer estimate galleries. Original posting tools remain behind the
existing portal staff login; uploads never trigger marketing publication.

Deployment order: back up portal connector/database; install new PHP helper
before the API dispatcher; verify signed read-only health/job tools; publish an
immutable shared Voice + Suite image based on the previous live digest; verify
zero active calls, save current panel configuration/runtime/Office state, then
switch only the image and restart. Verify Voice, Office and Mobile API health,
authenticated job sections, guest rejection, data preservation and runtime
configuration persistence. Never create test records in real customer jobs.

Rollback: retain the previous exact image digest and restore it without
replacing live state. New pending `portal_actions` must remain intact for replay
when the new worker returns. The older portal endpoints remain compatible;
keep the new PHP helper/journals unless separately reviewing a connector rollback.
No schema downgrade is needed. Do not restore database backups over new staff
work without a separate approved restore plan.

Verification: `server/tests/portal_tools_smoke.py`,
`server/tests/portal_tools_browser_smoke.py`, existing photo/adaptive/call/portal
tests, `scripts/test_external_portal.py`, repository/inventory/runtime checks.
Browser tests use fictional records at 320-1440 px in Chromium, Firefox and
WebKit. PHP tests use a pinned disposable container and cover scoping, signatures,
staff-only media, CRUD, stale edits, crash acknowledgement replay, video ranges,
invalid files, receipt amounts and retained originals. These fixture checks do
not substitute for a real staff-approved call and customer estimate acceptance.

The live external host reports PHP 8.0. Its associative-array compatibility
was verified with signed read-only job-tool requests, and the disposable PHP
fixture is pinned to that runtime to exercise mutations without production data.
This patch does not change the hosting account's PHP version.
