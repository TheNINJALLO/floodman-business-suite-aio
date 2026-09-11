# Configuration and secrets

## Configuration files

- `deployment/env/floodman.env.example`
- `deployment/env/floodman-payments.env.example`
- `deployment/env/apple-testflight-secrets.example`
- Android `local.properties.example`

Examples are field catalogs only. Copy them to untracked local files and replace placeholders.

## Major configuration groups

- company and owner identity
- time zone
- ports and public/private URLs
- PostgreSQL databases and passwords
- internal HMAC keys
- mobile token secret and lifetimes
- Square environment, application, token, location, version, and webhook configuration
- Documenso URLs and webhook secret
- SMTP and Twilio
- AI provider and API key
- external HTTPS origins, certificates, forwarding headers, and access policy
- Apple and Android signing

## Secret handling

Recommended hierarchy:

1. local `.env` files ignored by Git for development;
2. GitHub Actions secrets for CI signing and provider tests;
3. Pterodactyl encrypted variables or mounted secret files for staging;
4. a dedicated secret manager for production.

Rotate any secret that was ever pasted into a chat, console screenshot, public issue, or committed file.

## Environment inventory

`docs/generated/ENVIRONMENT_VARIABLES.csv` contains the variable names referenced by the custom source. It intentionally does not contain values.
