# Port migration from the earlier draft

The earlier AIO draft used a mixed allocation set that included `8080`. Version 3.1.1 replaces the public allocation map with a consecutive block:

```text
9000 Main Hub
9001 Documenso
9002 Mailpit
9003 Engineering Sandbox
9004 Floodman API
```

No Pterodactyl allocation is required for `8080` in v3.1.1.

The API process itself now listens on the configured `FLOODMAN_API_PORT`, which defaults to `9004`. Hub links, RoomFlow bridge output, webhook URLs, AI callbacks, Engineering Sandbox URLs, Office defaults, image metadata, and egg variables were updated accordingly.

Internal-only ports such as `3000`, `4201`, `5432`, `8090`, `8100`, and `8700` remain private inside the AIO container.
