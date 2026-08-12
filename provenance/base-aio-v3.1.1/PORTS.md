# Port allocation plan

| Port | Pterodactyl allocation | Purpose | Exposure guidance |
|---:|---|---|---|
| 9000 | Primary | Floodman-branded Gauzy Hub | May be reverse proxied with HTTPS |
| 9001 | Additional | Documenso signing UI | Restrict to authorized staff during testing |
| 9002 | Additional | Mailpit test inbox | Owner/admin only |
| 9003 | Additional | Engineering Sandbox | Owner/developer only |
| 9004 | Additional | Floodman API, RoomFlow, webhooks | Protect API docs; allow only required webhook routes |

Internal-only ports, which must not be assigned or exposed: `1025`, `1026`, `3000`, `4201`, `5432`, `8090`, `8100`, and `8700`.

The egg defaults to ports 9001 through 9004. Pterodactyl supplies the primary port through `SERVER_PORT`; select port 9000 as the primary allocation. `FLOODMAN_ENFORCE_9000_PORT_SCHEME=true` makes startup fail immediately when any allocation is incorrect. Set it to `false` only when the panel cannot provide the exact block, then make every Startup port match the actual assigned allocation.
