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

## Live acceptance — September 11, 2026

Live owner entry: https://floodman.oninetwork.com/office/service-setup

- Code/image revision: `7fb7b92705a98aa36c38ad9a0ec28ebb3b24d806`.
- Shared image: `ghcr.io/theninjallo/floodman-operations:unified-portal-7fb7b92705a98aa36c38ad9a0ec28ebb3b24d806@sha256:e210ab10eb234a4bb2d88e5274a8d9d7adc0ca757790ab1dab1f02e0d9042b69`.
- Immutable runtime source: `6154bea091bbe096697afb949e0b79eea69c3af7`.
- Published ZIP SHA-256 (download verified): `f82d23fafbf032c5eecec92bbea379e0039ce24dd15ad1652f30f0df60741fcb`.
- GitHub source verification and both server builds passed. Shared build run: `34636367601`.
- Fresh private configuration/Office backup: `adaptive-portal-switch-20260911T190606Z`
  in the operator's private backups directory. No active calls at either pre-restart check.
- The initial live check caught the unified primary owner projecting to local ADMIN;
  the final release includes the narrowly scoped verified-primary-owner compatibility rule.
- Final live browser: owner GET 200, anonymous access blocked, invalid form ticket
  rejected, payment-settings redirect correct, blank password fields, Call Center copy
  option present. No horizontal scrolling at widths 390, 768 and 1440.
- Voice readiness, Office health and API readiness all returned 200 after restart;
  panel state is running. Existing contact/property/RoomFlow/estimate/invoice/payment
  and SMS-consent IDs were preserved; runtime environment bytes were unchanged.
- No provider configuration was written or activated on the live server. Email and
  Square remain local-test only until the owner saves/checks/enables the desired service.
  Zero real emails sent and zero real charges during this work.
- Local checks passed: provider/security/persistence smoke; Chromium/WebKit setup
  matrix including unified primary-owner identity; mobile API and mobile operations;
  customer SMS; portal linkage; unified login; full web routes/responsive/overlay smoke;
  text-zoom overflow; repository verification (zero warnings) and release verification.

Retained pre-feature rollback image:
`ghcr.io/theninjallo/floodman-operations:unified-portal-837d13b89b01c336ee4c3cc97ef4cce1dffb6291@sha256:fbf8194e2935f1239b6743d1fd9e1d86cda44fc3c89f3dd5d5d29635ce426fbc`.
Do not restore an Office-state backup over newer customer activity merely to roll back
the image. Preserve any newly saved private provider configuration separately.
