# Floodman Pterodactyl 9000 Port Map

Use these five TCP allocations on the same Pterodactyl server.

| Pterodactyl allocation | Environment value | Purpose | Browser path |
|---|---|---|---|
| `9000` primary | `SERVER_PORT=9000` supplied by Pterodactyl | Main Floodman Gauzy Hub | `http://HOST:9000` |
| `9001` additional | `DOCUMENSO_PORT=9001` | Documenso | `http://HOST:9001` |
| `9002` additional | `MAILPIT_PORT=9002` | Local email capture | `http://HOST:9002` |
| `9003` additional | `ENGINEERING_PORT=9003` | Engineering Sandbox | `http://HOST:9003/lab` |
| `9004` additional | `FLOODMAN_API_PORT=9004` | API, RoomFlow, Square/Twilio/Documenso webhooks | `http://HOST:9004/docs` |

## Internal-only ports

Do not assign these as public Pterodactyl allocations for this egg:

```text
1025  Mailpit SMTP
1026  reserved SMTP fallback
3000  genuine Gauzy API behind the Hub
4201  internal Gauzy static server
5432  embedded PostgreSQL
8090  competitor intelligence API
8100  messaging AI API
8700  Floodman Office internal service
```

## Firewall

The Wings node or hosting provider must permit inbound TCP traffic to `9000-9004`. Only expose `9000` and `9001` to normal staff. Restrict `9002-9004` to administrators, a VPN, an IP allowlist, or an authenticated reverse proxy.
