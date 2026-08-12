# RoomFlow upstream source

RoomFlow is maintained as a separate repository and is intentionally not duplicated in this handoff archive. The Android and Apple build scripts fetch the exact commit recorded in `PINNED_COMMIT` and then layer the native Floodman bridge over it.

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

Do not silently advance the commit. A RoomFlow update is a release change because it can alter local-storage schemas, bridge events, measurement output, catalog behavior, and estimate synchronization.

The native app preparation scripts independently fetch the same pinned commit from GitHub. The root fetch scripts are supplied for code review, local refactoring and optional conversion to a submodule.
