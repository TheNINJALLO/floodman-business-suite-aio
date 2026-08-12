# Security model

## Exposure model

- Staff PWA and Full ERP: private Tailscale access
- Native app API: public HTTPS, narrow route set
- Customer estimates/invoices/payments: public tokenized links
- Signing: public customer surface
- Engineering, Mailpit, database, Supervisor, and administrative internals: private only

## Native device security

- per-device enrollment
- encrypted session storage
- short access-token lifetime
- rotating refresh tokens
- device-specific proof
- remote revocation
- HTTPS-only network policy
- biometric/device-PIN local unlock
- server capability and minimum-version negotiation

## Payment security

- use Square-hosted or native tokenization
- never store PAN, CVV, track data, or full card-entry payloads
- store only processor IDs and masked metadata when needed
- verify webhooks and make them idempotent
- use Sandbox until acceptance tests pass
- restrict payment logs

## Customer-link security

- use random, unguessable tokens
- store token hashes when feasible
- set expiration and revocation rules
- scope a link to one document or action
- record access and completion events
- do not expose internal IDs as authorization

## Internal service security

- use HMAC-authenticated internal requests
- enforce timestamp windows and replay protection
- rotate keys with key IDs
- separate AI provider keys from internal service keys
- run deterministic AI mode when customer-message approval is not configured

## Secrets

Never commit:

```text
Tailscale auth keys
Square access or webhook keys
OpenAI keys
Twilio credentials
SMTP passwords
Apple certificates, profiles, or App Store Connect keys
Android signing keys
mobile token secrets
HMAC secrets
production database passwords
```

Use `.env.example` only as a field catalog.

## Immediate hardening tasks

- pin upstream images by digest
- run container and dependency vulnerability scanning
- add rate limiting and abuse controls to public endpoints
- centralize secrets
- add structured audit export
- add backup encryption and restore drills
- review Documenso/Gauzy licenses and public-source obligations
- complete a payment and customer-data threat model
