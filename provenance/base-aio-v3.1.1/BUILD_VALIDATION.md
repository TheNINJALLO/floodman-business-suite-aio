# Floodman Pterodactyl AIO v3.1.1 validation

## Port scheme

- 9000: Main Floodman/Gauzy Hub, primary Pterodactyl allocation
- 9001: Documenso
- 9002: Mailpit
- 9003: Engineering Sandbox
- 9004: Floodman API, RoomFlow bridge, and provider webhooks

`FLOODMAN_ENFORCE_9000_PORT_SCHEME` defaults to `true`, so startup stops with a clear message if the assigned allocations do not match.

## Completed static validation

- PTDL_v2 egg JSON parsed successfully.
- GitHub Actions workflow YAML parsed successfully.
- Package validator passed.
- 19 AIO shell wrappers passed POSIX shell syntax checks.
- 86 Python files parsed successfully.
- JavaScript files passed `node --check`.
- No nested Docker, Docker socket, privileged-container, or DinD markers were found.
- Genuine Gauzy is forced to `DEMO=false`.
- Floodman uses the fixed v3 database baseline and contains no runtime Floodman migration directory.

## Tests

- Orchestrator: 38 passed
- Messaging AI: 4 passed
- Competitor Intelligence: 5 passed
- Floodman Office: 31 passed, 2 Windows-only tests skipped
- Engineering Sandbox: 8 passed, 1 Windows-only test skipped

Total applicable tests: **86 passed**. Three tests are intentionally skipped because this package is Pterodactyl/Linux AIO rather than the Windows Docker Compose edition.

## Remaining runtime gate

The complete multi-service image has not been built or booted on an actual Pterodactyl Wings node in this environment. The GitHub Actions workflow must build `ghcr.io/theninjallo/floodman-business-suite-aio:3.1.1`, followed by a first-boot smoke test on the target node.
