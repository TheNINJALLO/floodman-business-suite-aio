# Customer SMS consent

The private estimate and invoice portal includes optional text preferences. Opening a link, accepting an estimate, paying an invoice, or having an existing customer record does not enroll anyone. The checkbox is unchecked on every load, including for previously enrolled customers. Staff opt-in remains separate in the authenticated call-center profile.

The public program, privacy policy, and terms are at `https://aicall.oninetwork.com/sms-program`, `/privacy`, and `/terms`. Office exposes the same content under `/customer/sms/program`, `/customer/sms/privacy`, and `/customer/sms/terms`. The Hub's exact `/privacy`, `/terms`, and `/sms-program` paths redirect to the canonical public pages; staff screens remain private.

## Consent and delivery boundaries

- A short-lived, signed form ticket binds consent to the existing private document and customer. Store the exact disclosure, version, timestamp, number, source, and choice locally before synchronization.
- An idempotent outbox retries authenticated synchronization to the existing communication consent table. This release does not migrate a database or enroll existing records.
- Changing a number withdraws the old number's portal consent. A new number needs a new checked disclosure. Replaying an old request cannot undo a later withdrawal.
- Enable `CUSTOMER_SMS_CONSENT_CHECK_ENABLED=true` in the shared image. Delivery checks both the backend consent and current portal state. Unavailable checks, pending synchronization, portal withdrawal, and provider STOP suppression prevent delivery.
- STOP applies even without an open receivables case. START may resume an existing evidenced subscription but must not enroll an unknown number. Advanced Opt-Out owns its configured keyword replies; do not send duplicate HELP replies.
- Carrier registration approval, provider credentials, and the existing SMS delivery gates remain separate requirements. Saving a preference does not send a message or claim that a rejected campaign is approved.

## Verification

Use isolated fictional data, never enroll or message a live customer to test:

```powershell
$env:PYTHONPATH='server/office-console'
.venv/Scripts/python.exe server/tests/customer_sms_smoke.py
.venv/Scripts/python.exe server/tests/customer_sms_browser_smoke.py
.venv/Scripts/python.exe server/tests/customer_sms_orchestrator_smoke.py
.venv/Scripts/python.exe server/tests/web_ui_smoke.py
```

Before deployment retain the previous shared image digest, back up runtime configuration and Office state, and confirm there are no active calls. After deployment verify both Voice and Office, public policy pages without cookies, private staff routes, customer portal layout without changing consent, preserved records, and restart persistence. Twilio review is external acceptance, not a source-test result.
