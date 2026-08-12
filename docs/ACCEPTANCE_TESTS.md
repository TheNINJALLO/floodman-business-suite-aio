# Acceptance test catalogue

## A. Startup and persistence

1. Start from an intact data directory.
2. Wait for `FLOODMAN_SUITE_READY`.
3. Verify every health endpoint.
4. Stop normally, start again, and confirm no duplicate PostgreSQL or stale PID loop.
5. Confirm record counts and recent documents are unchanged.

## B. Desktop/mobile/ERP routing

1. Open `/workspace?workspace=auto` on Windows/macOS/Linux and confirm desktop.
2. Open the same route on Android/iPhone/tablet and confirm mobile.
3. Force `/office/desktop?desktop=1` on a touch laptop and confirm desktop sidebar/table layout.
4. Force `/office/mobile?mobile=1` on desktop and confirm touch shell.
5. Open `/full-erp?target=login` signed out and confirm ERP login.
6. Sign in, open `/full-erp`, and confirm dashboard.
7. Inspect browser console for mixed-content, localhost or wrong-port URLs.

## C. Customer and property

1. Search by name, company, email, phone, tag and address.
2. Open a customer with multiple properties.
3. Add, pin and delete notes with authorization checks.
4. Update tags.
5. Add a property and confirm it appears only under the correct customer.
6. Upload and download a document.

## D. Import

1. Upload the safe template with known test records.
2. Preview validation errors without committing.
3. Correct and commit.
4. Repeat the import and prove idempotent matching.
5. Verify counts and external/source IDs.
6. Test ZIP path traversal rejection and upload-size limits.

## E. Estimate

1. Search existing estimates without creating a draft.
2. Create with existing customer/property.
3. Create with existing customer/new property.
4. Create new customer/new property.
5. Select a project category and inspect generated plan, outcomes, assumptions, exclusions, protections and options.
6. Add at least four headers and edit their names/descriptions.
7. Add catalog and custom lines; verify the custom line is reusable.
8. Configure 50-percent and fixed deposits.
9. Save, reopen and edit.
10. Generate PDF and compare to approved reference structure.
11. Send, authorize, accept, activate deposit and collect sandbox/manual payment.
12. Convert to invoice.

## F. RoomFlow

1. Import original Supabase organization with a test account.
2. Confirm organization/workspace auto-selection.
3. Change workspace and prove job isolation.
4. Open an imported historical job and restore geometry.
5. Add/change measurements and scope.
6. Save and sync twice; prove no duplicate job/estimate/catalog records.
7. Capture actual layout and verify PDF page.
8. Create a new workspace via the native bridge.
9. Test offline pending edit then reconnect.

## G. Invoice and payments

1. Create directly and from estimate.
2. Edit grouped headers/lines before issue.
3. Send customer link.
4. Pay through Square sandbox.
5. Record cash, check and ACH test entries.
6. Verify exact-cent balance/history.
7. Void/delete only eligible records.
8. Confirm $0 balance produces paid/receipt behavior.
9. Verify no raw card data appears in Office state, logs or API payloads.

## H. Documents/signatures

1. Send a Work Authorization.
2. Sign through the public tokenized link.
3. Process webhook.
4. Confirm signed PDF and audit metadata attach to customer, property, job and estimate.
5. Create and sign a change order.
6. Confirm original signed scope remains immutable.

## I. Scheduling and staff

1. Create inspection, job, estimate appointment, follow-up, delivery, training and meeting events.
2. Assign multiple employees and a lead.
3. Create a conflict and verify rejection/authorized override.
4. Update status through en route, in progress and complete.
5. Verify tasks, announcements, notifications and time clock.
6. Subscribe to the read-only ICS feed.

## J. Android

1. Install clean debug/release build.
2. Sign in with Tailscale off.
3. Enroll, refresh, revoke and re-enroll device.
4. Test all main modules and theme modes.
5. Open PDFs only when they pass PDF validation.
6. Exercise full RoomFlow workflow and app back behavior.
7. Test process death/reopen and token refresh.
8. Test phone and tablet layouts.

## K. Apple

1. Build simulator and run on iPhone/iPad simulators.
2. Test login, Keychain, refresh and device lock.
3. Test RoomFlow local asset server and sync.
4. Record every native parity gap.
5. After parity, sign, upload and install through TestFlight.
