# Floodman Business Suite AIO for Pterodactyl v3.1.1

Testing-only all-in-one Pterodactyl edition of Floodman Operations.

## Fixed 9000 allocation scheme

| Allocation | Port | Service |
|---|---:|---|
| Primary | 9000 | Floodman-branded Gauzy Hub |
| Additional | 9001 | Documenso signing |
| Additional | 9002 | Mailpit test inbox |
| Additional | 9003 | Engineering Sandbox |
| Additional | 9004 | Floodman API, RoomFlow bridge, and provider webhooks |

The egg enables `FLOODMAN_ENFORCE_9000_PORT_SCHEME=true` by default. Startup stops with a readable error when the primary or additional allocations do not match the table.

## Important

This source package builds one large custom image. It does not run Docker Compose or Docker-in-Docker inside Pterodactyl. The image must be built and published to GHCR before the egg can start.

Read:

- `docs/PTERODACTYL_INSTALL_9000.md`
- `docs/BUILD_AND_PUBLISH_IMAGE.md`
- `docs/PORT_MAP_9000.md`
