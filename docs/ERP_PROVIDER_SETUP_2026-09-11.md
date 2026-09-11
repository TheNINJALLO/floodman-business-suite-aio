# ERP Payments & email setup

Owner entry: `/office/settings` → **Payments & email**, or `/office/service-setup`.
The old payment-settings link redirects owners to the new page. Ordinary administrators
and other staff cannot read or submit the credential forms. The unified ERP's primary
owner is also recognized when its server-verified SUPER_ADMIN identity matches the
server-configured owner email, even though its local Office role is projected as ADMIN.
Neither another super-admin nor a matching email without that verified role is sufficient.

## Workflow

1. Save SMTP or Square credentials to a draft. Existing active delivery/checkout is unchanged.
2. Check the saved connection. Checks perform SMTP TLS/login/NOOP or Square GET locations;
   they do not send email, create customers/invoices, or charge cards.
3. SMTP: send one test to an explicitly entered inbox and confirm receipt, then enable.
4. Square: enable Sandbox and verify a fictional-document checkout with Square test data.
   Production requires separate credentials, a fresh check and explicit owner confirmation.

Blank secrets keep the saved value only for the same SMTP account/server/security or
Square environment. Changing credentials clears the draft check. Checks expire after
15 minutes for activation. A failed draft check never disables an existing connection.
The UI does not return saved passwords/tokens. Square locations are limited to active,
USD card-processing locations. The Locations API does **not** validate application-ID
pairing or demonstrate successful checkout; the UI states that remaining test explicitly.

## Storage and safety

Private provider state is stored in `OFFICE_CONSOLE_DATA_DIR/private-integrations/settings.json`.
Directory mode is 0700 and files are created 0600 before writing. Atomic replacement,
flush/fsync and revision checks protect against partial saves and stale/replayed forms.
This is a private credential file, not encrypted storage: restrict host/panel access and
encrypt/restrict its backups. It is outside Office JSON exports and customer documents.
No database migration is needed. Back up the private directory with other DATA_DIR files.

Every setup POST requires a currently active OWNER, an exact trusted Origin, a bounded
URL-encoded body and an expiring HMAC form ticket bound to the owner session/revision.
Provider errors are redacted. Test-email reservations are persisted before delivery,
with a 60-second cooldown; server acceptance is distinguished from inbox delivery.

UI SMTP supports certificate-verified STARTTLS/587 or TLS/465 and authenticated public
mail hosts. Plaintext auth and internal addresses are refused. Square endpoints are fixed
to the official Sandbox/Production hosts and credential-bearing redirects are disabled.
Enabled settings are loaded without a server restart and survive restarts. HTTP business
operations pin one configuration snapshot to avoid switching environments mid-operation.
Disabling configured payments blocks Office/mobile provider mutations; a client-supplied
`verified` value cannot override that gate. Existing environment-based setups are retained
until the owner explicitly activates or disables a service.

## Boundaries

- SMTP applies to Office document/receipt/message/invitation email. On the unified server,
  **Copy Call Center email settings** can copy the existing private configuration into a
  draft, without displaying the password. It does not modify Call Center email settings
  or their activation, and the two copies do not automatically track later edits.
- Square applies to Office and mobile checkout. The separate orchestration/RoomFlow
  automated billing adapter and changes made directly in Square still need matching
  server/webhook setup. This page does not claim those connections were configured.
- Client views remain the existing secure document links; no all-documents client-login
  dashboard is added by this change.
- Saving/testing does not activate real payments or send customer communications.
- This patch does not change telephony, consent, SMS, routing or database schemas.

## Verification

`PYTHONPATH=server/office-console`:

- `python server/tests/integration_setup_smoke.py`
- `python server/tests/integration_setup_browser_smoke.py`

These use fictional credentials and mock providers, including actual Chromium/WebKit
forms at mobile, tablet and desktop widths. They are not proof of a live Square account,
external SMTP inbox delivery or a real payment. No real email/charge is used for validation.

References: [Square credentials](https://developer.squareup.com/docs/build-basics/access-tokens),
[Square locations](https://developer.squareup.com/reference/square/locations-api/list-locations),
[Python SMTP TLS](https://docs.python.org/3/library/smtplib.html).
