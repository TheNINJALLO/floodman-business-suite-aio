# RoomFlow upstream source

RoomFlow is maintained as a separate repository. Floodman keeps a reviewed runtime-only export of the exact pin under `server/roomflow/release-assets/` so server startup and native builds do not depend on GitHub or a mutable CDN. The ignored checkout in this directory is for review and pin updates only.

```text
Repository: https://github.com/TheNINJALLO/roomflow.git
Pinned commit: 1f97817a52b916875e50cc6380c0d284072b8ce8
```

Fetch it with:

```bash
bash scripts/fetch-roomflow.sh
```

or on Windows PowerShell:

```powershell
./scripts/fetch-roomflow.ps1
```

After an approved pin update, run `python scripts/package_roomflow_release_assets.py` and `python scripts/verify_roomflow_release_assets.py`. Do not silently advance the commit. A RoomFlow update is a release change because it can alter local-storage schemas, bridge events, measurement output, catalog behavior, and estimate synchronization.

The server and native preparation scripts verify and consume the checksummed release assets. The root fetch scripts remain available for code review and controlled pin updates.
