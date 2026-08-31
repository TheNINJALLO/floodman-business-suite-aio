# Floodman Operations fresh Pterodactyl setup without Tailscale

This handoff installs Floodman Operations server 4.7.1 with Mobile API `0.3.0-alpha11` on a new Pterodactyl server. Tailscale is not downloaded, configured, or started. Your external HTTPS proxy owns DNS, certificates, HTTPS redirects, and access policy for `oninetwork.com`.

This is a fresh-server package. It does not migrate or delete an existing database, application data, or any old network state.

## Files in the handoff

```text
egg-floodman-operations-mobile-v4.7.1.json
floodman-operations-runtime-v4.7.1.zip
mobile-start.sh
SHA256SUMS
README-FIRST.md
```

Do not extract or rename `floodman-operations-runtime-v4.7.1.zip`.

## 1. Import the egg

1. In Pterodactyl administration, open **Nests** and import `egg-floodman-operations-mobile-v4.7.1.json`.
2. Confirm the image is exactly:

   ```text
   ghcr.io/theninjallo/floodman-business-suite-aio:3.2.2@sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5
   ```

3. Keep the startup command as `bash ./mobile-start.sh`.

## 2. Create the server and allocations

Create these allocations on the same node:

```text
9000  Floodman Hub, ERP, CRM, PWA, RoomFlow, and customer portal
9001  Floodman Signing
9002  Mailpit test inbox; never attach a public hostname
9003  Engineering Sandbox; staff-only hostname
9004  external API gateway, native Mobile API, and provider callbacks
```

## 3. Configure the four HTTPS hostnames

Create these proxy mappings:

```text
floodman.oninetwork.com -> Pterodactyl allocation 9000
sign.oninetwork.com     -> Pterodactyl allocation 9001
lab.oninetwork.com      -> Pterodactyl allocation 9003
api.oninetwork.com      -> Pterodactyl allocation 9004
```

Every proxy mapping must:

- redirect HTTP to HTTPS;
- use a valid certificate for the exact hostname;
- preserve the original `Host` header;
- send `X-Forwarded-Proto: https`;
- send `X-Forwarded-For` and the client address;
- support WebSocket upgrade headers;
- allow request bodies up to 50 MB;
- use upstream read/send timeouts of at least 300 seconds.

DNS records select a server; DNS cannot select a port. The HTTPS reverse proxy must perform the hostname-to-port mapping.

## 4. Apply access policy before publishing DNS

The proxy is now the staff-security boundary:

- `floodman.oninetwork.com`: require approved staff access for the ERP, CRM, PWA, Office, RoomFlow, and administrative paths. Permit only tokenized `/customer/` routes without staff authentication when customers need messages, documents, or payments.
- `sign.oninetwork.com`: allow recipient signing routes. Protect signing administration, templates, and account screens. Public account creation is disabled by Floodman.
- `lab.oninetwork.com`: require approved staff access for every path.
- `api.oninetwork.com`: allow the device-authenticated `/mobile-api/` routes and reviewed provider webhook/customer-token routes. Protect workflow administration, OpenAPI documentation, and all other paths.
- Port `9002`: do not create a DNS name or public proxy mapping.

Do not publish the database, Office service port `8700`, workflow service port `8701`, or any other internal process.

## 5. Set Pterodactyl Startup values

Replace the company and Owner examples, then confirm these exact HTTPS defaults:

```text
Main Floodman URL       https://floodman.oninetwork.com
Floodman Signing URL    https://sign.oninetwork.com
Customer Portal URL     https://floodman.oninetwork.com/customer
Native Mobile API URL   https://api.oninetwork.com/mobile-api
Workflow API URL        https://api.oninetwork.com
Engineering URL         https://lab.oninetwork.com
```

Keep the time zone as `America/Detroit`. Keep ports `9001` through `9004` matched to their allocations. Leave both AI providers on `deterministic` unless a separately reviewed provider configuration is authorized.

No Tailscale hostname, key file, machine approval, Serve rule, or Funnel permission is required.

## 6. Automatic runtime download and verification

During Pterodactyl installation, the egg downloads the runtime from the immutable GitHub commit recorded in the installer when this file is missing:

```text
/home/container/floodman-operations-runtime-v4.7.1.zip
```

The installer verifies SHA-256 before moving the download into place. If a runtime ZIP already exists, it is retained only when its checksum matches; a mismatched file stops installation and is never overwritten. The egg also installs `mobile-start.sh`.

If the Pterodactyl node cannot reach `raw.githubusercontent.com`, upload the supplied runtime ZIP with that exact filename before reinstalling the server. Do not extract it. Compare manually uploaded files to the supplied `SHA256SUMS` before first start.

## 7. First start

Start the server and wait for:

```text
FLOODMAN_SUITE_READY
```

This marker proves the internal services and gateways became ready. It does not prove that external DNS, certificates, or proxy access rules are correct.

## 8. Acceptance checks

1. Confirm all four hostnames present a valid HTTPS certificate.
2. Sign in at `https://floodman.oninetwork.com` and open Desktop Workspace, Mobile Workspace, Full ERP, and RoomFlow.
3. Confirm `https://api.oninetwork.com/mobile-api/v1/health` reports Mobile API `0.3.0-alpha11`.
4. Confirm Android uses `https://api.oninetwork.com/mobile-api/` and can sign in with a fictional test account.
5. Confirm an unapproved browser cannot open staff or Engineering pages.
6. Confirm a fictional customer token can open only its intended portal, signing, or payment route.
7. Stop and restart the server once. Confirm the readiness marker returns and fictional data remains.
8. Create a Pterodactyl backup after clean-install and restart validation. Test restore only on an approved isolated server.

If startup fails, preserve the console and `diagnostics/`. Never repair startup by deleting `data/`, `config/`, databases, signed documents, payment records, or old network-state folders.

Created by Josh Aldrich.
