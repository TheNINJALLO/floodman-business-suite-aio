# Floodman Operations source handoff

This repository is the source handoff for the Floodman Operations system developed during the ChatGPT build session. It is arranged for VS Code and Codex rather than for one-click mobile deployment.

## Current baseline

| Component | Version | Status |
|---|---:|---|
| Floodman server overlay | 4.6.9 | Current cumulative custom source |
| Pterodactyl launcher | 4.6.9 | Current cumulative launcher |
| Android app | 0.3.0-alpha12 | Local compile/test/lint/APK/AAB gate passed; device/signing/CI dispatch remain external |
| iPhone/iPad app | 0.1.0-alpha03 | Windows source/workflow readiness passed; run the Xcode simulator workflow before TestFlight |
| RoomFlow | pinned commit `1f97817a52b916875e50cc6380c0d284072b8ce8` | Fetched separately by script |
| Time zone | America/Detroit | Project standard |

## Start here

1. Open `floodman.code-workspace` in VS Code.
2. Read `AGENTS.md`, then `docs/00-EXECUTIVE-HANDOFF.md`.
3. Create a private Git repository and commit this untouched baseline.
4. Run `python scripts/generate_inventory.py`.
5. Run `python scripts/verify_repo.py`.
6. Fetch RoomFlow with `bash scripts/fetch-roomflow.sh` or `./scripts/fetch-roomflow.ps1`.
7. Build the server from `containers/derivative/Dockerfile` first. It is the least disruptive path.
8. Run the Android GitHub workflow and the unsigned iOS simulator workflow before any production release.

## What is included

- Complete Floodman custom server source for v4.6.9
- Native Android source and local build evidence for alpha12
- Native iOS source and Windows readiness evidence for alpha03
- Original v3.1.1 AIO build source and current AIO Docker scaffolding
- Current Pterodactyl runtime, launcher, and egg files
- Android, iOS simulator, and TestFlight workflows
- VS Code workspace, Codex instructions, source inventories, API inventories, release history, security rules, and deployment notes
- Fictional estimate and invoice reference PDFs plus a blank customer import template

## What is intentionally excluded

- Live customers, properties, estimates, invoices, payment records, signed documents, logs, screenshots, database volumes, RoomFlow job data, and backups
- Passwords, Tailscale auth keys, Square tokens, Apple signing keys, mobile refresh tokens, private keys, and other secrets
- Full upstream Gauzy, Documenso, Mailpit, Tailscale, and Square source
- The RoomFlow repository itself. It remains pinned and fetchable through the included scripts.

This is a source handoff, not a live-data backup and not proof that the latest release has passed every platform compiler and live-node test.

## Repository map

```text
apps/android/                 Native Android application
apps/ios/                     Native iPhone and iPad application
server/                       Current Floodman server custom source
provenance/base-aio-v3.1.1/       Original AIO source package and build provenance
containers/base-aio/          Current full AIO image build
containers/derivative/        Current overlay-on-base image build
launcher/                     Current Pterodactyl launcher
deployment/releases/          Current regenerated Pterodactyl upload artifacts
release-artifacts/             Immutable handoff-era comparison/rollback archives
reference/                     Fictional approved document references and blank import template
deployment/                    Pterodactyl, Docker, Tailscale, and GitHub workflow files
vendor/                        Pinned upstream source records and RoomFlow fetch information
scripts/                       Verification, inventory, and source-fetch tools
docs/                          Complete technical and project handoff
history/                       Reconstructed release and artifact history
```

## Quick commands

```bash
python scripts/generate_inventory.py
python scripts/verify_repo.py
python scripts/package_pterodactyl_release.py
python scripts/verify_pterodactyl_release.py
bash scripts/fetch-roomflow.sh
make derivative-image
```

Android and iOS build commands are documented in `docs/06-ANDROID.md` and `docs/07-IOS.md`.
