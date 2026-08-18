# Local development in VS Code and Codex

## Recommended host

Use Linux, WSL2, or a VS Code Dev Container. Docker is required for the full AIO runtime. Android needs JDK 17 and Android SDK 36. iOS compilation requires macOS and Xcode.

## Baseline setup

```bash
git init
git add .
git commit -m "Floodman v4.6.7 source handoff baseline"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r server/requirements-dev.txt
python scripts/generate_inventory.py
python scripts/verify_repo.py
```

On Windows PowerShell:

```powershell
git init
git add .
git commit -m "Floodman v4.6.7 source handoff baseline"
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r server/requirements-dev.txt
python scripts/generate_inventory.py
python scripts/verify_repo.py
```

## Fetch RoomFlow

```bash
bash scripts/fetch-roomflow.sh
```

```powershell
./scripts/fetch-roomflow.ps1
```

The fetched source lands under `vendor/roomflow/source` at the pinned commit.

## Server development

The current custom server source is in `server/`. The main services are ordinary Python packages, but the full runtime expects the AIO network and environment. For isolated work:

- set service-specific `PYTHONPATH` values;
- copy `deployment/env/floodman.env.example` to a local untracked `.env`;
- use Mailpit and local provider modes;
- keep Square in Sandbox;
- use a disposable database and disposable Office data directory.

## Docker paths

Derivative image:

```bash
docker build -f containers/derivative/Dockerfile -t floodman-operations:4.7.0 .
```

Complete AIO image:

```bash
docker build -f containers/base-aio/Dockerfile -t floodman-business-suite-aio:4.7.0 .
```

The complete build composes upstream images. Pin each upstream image by digest before a release.

## Suggested branch plan

```text
main                  verified releases only
develop               integrated next release
feature/<name>        one feature or repair
release/<version>     release stabilization
hotfix/<version>      urgent cumulative fix
```

## First Codex task

Open `docs/16-CODEX-STARTER-PROMPT.md` and give it to Codex from the repository root. Ask Codex to report its plan before changing files.
