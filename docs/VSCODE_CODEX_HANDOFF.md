# VS Code and Codex handoff

## Recommended repository initialization

```bash
unzip floodman-complete-source-handoff-v4.6.7.zip
cd floodman-complete-source-handoff-v4.6.7
git init
git add .
git commit -m "Import Floodman Operations v4.6.7 handoff"
git tag handoff-v4.6.7
code floodman.code-workspace
```

Use a private remote. Do not upload this project to a public repository until the third-party licensing, branding and secret review is complete.

## First Codex prompt

A useful first task is:

```text
Read AGENTS.md, PROJECT_STATUS.md, docs/ARCHITECTURE.md,
docs/KNOWN_ISSUES_AND_VALIDATION.md, and server/overlay.json.
Do not change code yet. Produce a migration plan that makes the derivative
Docker image reproducible, moves environment-specific values out of source,
and creates a staging acceptance suite. Never delete or reset data.
```

## Suggested branches

```text
chore/reproducible-build
security/secrets-and-env
fix/full-erp-live-routing
data/office-postgres-migration
android/alpha11-acceptance
ios/native-parity
infra/dedicated-server
```

## Local tooling

- Python 3.12
- Node 22 for JS syntax checks
- Docker/Buildx
- JDK 17 and Android SDK 36
- Gradle 8.13
- macOS/Xcode/XcodeGen for Apple
- Git, ShellCheck and a secret scanner

## Safe first-week sequence

1. Run `make inventory` and `make verify` without modifying source.
2. Compare `SHA256SUMS` to the handoff archive.
3. Move the Supabase defaults and all provider settings to env/config.
4. Build the derivative image.
5. Add a staging-only compose or deployment definition.
6. Import sanitized data and reproduce the Full ERP issue.
7. Add an automated test before changing the route.
8. Build Android and Apple from the same commit.
9. Document every deviation from the handoff baseline.

## Working with large files

The approved PDF references and exact release ZIPs are included for provenance. Do not edit release ZIPs in place. Change source, build a new versioned artifact, and regenerate checksums.

RoomFlow is fetched separately to avoid duplicating a second repository. Do not commit its fetched working tree unless you intentionally convert it to a submodule or subtree and record the license/source decision.

## Context for Codex

The main non-negotiables are in `AGENTS.md`. The most useful generated machine context is:

```text
docs/generated/API_ROUTE_INVENTORY.csv
docs/generated/ENVIRONMENT_VARIABLES.csv
docs/generated/SOURCE_MANIFEST.csv
docs/generated/SOURCE_STATS.json
```

For a focused change, tell Codex which component, version contract, acceptance test and rollback boundary apply.
