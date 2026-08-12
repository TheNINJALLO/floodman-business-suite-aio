# Floodman v4.6.7 build validation

## Package identity

- Runtime: `Floodman Operations 4.6.7`
- Release: `pterodactyl-mobile-v4.6.7`
- Upgrade base: `4.6.6`
- Android compatibility: `0.3.0-alpha11`

## Source and syntax checks

- 82 Python files parsed with the Python AST parser.
- 20 runtime shell scripts passed `bash -n`.
- The replacement Pterodactyl launcher passed `bash -n`.
- 5 JavaScript files passed `node --check`.
- 8 JSON files parsed successfully.
- No `PIL` or Pillow import remains in the runtime.
- The runtime manifest verified all 161 payload files.

## Application smoke tests

The following tests passed against the packaged source:

- Full ERP authentication routing
- Full ERP launcher behavior for signed-out, signed-in, forced-login, and HTTP 503 states
- Separate desktop/mobile workspace routing
- Dependency-free estimate PDF generation
- Android Mobile API authentication and capability contract
- Native estimate, invoice, payment, and scheduling operations
- Native RoomFlow create/update and actual-layout storage
- Original RoomFlow Supabase import
- RoomFlow workspace recovery, creation, selection, and isolation

## Nginx validation

The rendered Nginx configuration passed `nginx -t`.

A local integration test confirmed:

- `/` redirects to `/workspace?source=root&workspace=auto`;
- `/api/auth/authenticated` proxies the signed-out JSON value `false`;
- `/full-erp` contains the authentication-aware launcher;
- the ERP index receives `/floodman-boot-guard.js`;
- browser bundle URLs for `localhost`, `127.0.0.1`, and `0.0.0.0` are rewritten to `https://floodman-operations.tail274417.ts.net:8443` when the Host header uses the Tailscale HTTPS port.

## Archive checks

- Runtime ZIP CRC test: passed
- Runtime internal SHA-256 manifest: passed
- ZIP path-safety inspection: passed
- Complete fix-kit checksum manifest: passed

## Boundary

The final live test must occur on the user's Pterodactyl Wings node and Tailscale connection. This validation does not claim that the package has already been deployed to that node.
