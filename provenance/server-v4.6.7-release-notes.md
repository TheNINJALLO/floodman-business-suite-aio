# Floodman v4.6.7 release notes

## Full ERP login and private HTTPS routing repair

Floodman v4.6.7 corrects the Full ERP link that could open the upstream ERP recovery or "server down" page even while the Floodman Hub and ERP API were running.

### Authentication-aware ERP launcher

`/full-erp` now queries the same-origin ERP authentication endpoint before loading the Angular browser:

- an authenticated session opens `#/pages/dashboard`;
- a signed-out session opens `#/auth/login`;
- HTTP 200 with the JSON value `false` is treated as a normal signed-out response;
- HTTP 5xx responses are treated as startup conditions and retried.

Direct shortcuts are also included:

- `/erp-login`
- `/erp-home`
- `/floodman-login`
- `/erp-dashboard`

### Injected browser guard

The launcher now creates, serves, and injects `/floodman-boot-guard.js` into the real ERP index page. The guard corrects a direct dashboard URL when the browser is signed out and provides a focused recovery page only when the Hub and ERP API respond but the browser fails to render.

### Tailscale HTTPS preservation

The internal Nginx gateway recognizes the private Tailscale HTTPS ports `8443` through `8447` even when the final loopback hop reports HTTP. ERP JavaScript and CSS responses rewrite Hub URLs using the browser-facing HTTPS origin, including placeholders based on:

- `localhost`
- `127.0.0.1`
- `0.0.0.0`

This prevents mixed-content and wrong-origin failures inside the Full ERP page.

### Status and startup checks

The v4.6.7 launcher now validates:

- the Full ERP launcher;
- the injected browser guard;
- the same-origin ERP authentication endpoint;
- the private Hub;
- the existing mobile API, RoomFlow, signing, payments, scheduling, and workspace capabilities.

A new `/floodman-status.html` page separates Hub readiness from ERP API readiness.

## Compatibility

- Android `0.3.0-alpha11` remains compatible.
- No Android rebuild is required.
- PostgreSQL and existing Floodman records are preserved.
- Existing desktop and mobile workspace routes remain separate.
