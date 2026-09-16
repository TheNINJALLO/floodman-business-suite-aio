# Security and compliance boundaries

## Access surfaces

### Private staff surface

The PWA, desktop workspace and Full ERP are intended for approved staff through `https://floodman.oninetwork.com`. The external HTTPS proxy must enforce the staff access policy before forwarding to port 9000.

### Public narrow surface

Public exposure is limited to the Mobile API path, reviewed provider webhooks, recipient signing routes, and tokenized customer signing/payment routes. The complete Office UI, Full ERP, signing administration, workflow administration, API documentation, engineering tools, Mailpit and databases must not be published without staff access control.

## Native authentication

The Mobile API implements:

- short-lived access tokens;
- rotating refresh tokens;
- per-device registration;
- device proof/signature material;
- device renaming and revocation;
- audit records;
- encrypted local session storage in native apps;
- biometric/device-lock integration;
- TLS-only network configuration.

## Payment handling

Floodman must never store:

```text
full card number
CVV/CVC
magnetic stripe data
processor secret in a mobile binary
```

Floodman may store:

```text
Square customer ID
Square card/payment-method token
brand and last four digits
expiration month/year
authorization and consent state
transaction/order/invoice IDs
masked display metadata
```

Card entry must use Square's secure SDK or hosted component. Manual cash, check and ACH/external records need staff identity, timestamp, amount, reference and notes.

## Secrets

Use GitHub/Pterodactyl secret stores or private environment files. Rotate any credential that has ever appeared in a screenshot, copied console log or chat message.

The repository's `.gitignore` protects common secret and data forms, but it is not a security control by itself. CI should run a dedicated secret scanner.

## Supabase

The original RoomFlow import authenticates as the user and relies on Supabase row-level security to determine readable records. Do not put a service-role key in Android, Apple or a browser bridge.

The source currently includes a default public Supabase URL and anonymous/publishable key in `roomflow_supabase.py`. Move these values into environment configuration during migration. Treat them as environment identifiers, not authorization to bypass RLS.

## Messaging

Twilio messaging requires documented opt-in/opt-out and applicable carrier/A2P compliance. Automated receivables messages must respect consent, holds, payment promises, quiet hours and staff escalation rules.

## AI

OpenAI-compatible providers are optional. Keep API keys server-side. Do not send payment-card data, unnecessary identity records, signed documents or full customer files to a model. Retain deterministic/fallback classification and staff approval paths for high-impact communications.

## Third-party licenses

Gauzy and Documenso are upstream AGPL projects in the current image design. Any redistribution, deep modification, hosted network use or white-label strategy needs a qualified license review and compliance plan. See `docs/THIRD_PARTY_AND_LICENSES.md`.

## Production hardening checklist

- Pin image and package digests.
- Generate and retain SBOMs.
- Scan containers and dependencies.
- Run services as least-privileged users.
- Separate public/private gateways.
- Add rate limiting and WAF controls to public endpoints.
- Centralize structured logs and alerts.
- Encrypt backups and test restore.
- Add database row-level authorization tests.
- Establish retention/deletion policies.
- Perform an independent security review before storing production payment tokens or signatures.
