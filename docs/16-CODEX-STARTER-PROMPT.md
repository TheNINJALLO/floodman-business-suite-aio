# Codex starter prompt

Use this from the repository root:

```text
You are taking over the Floodman Operations source handoff.

Before editing anything:
1. Read README.md, AGENTS.md, docs/00-EXECUTIVE-HANDOFF.md, docs/02-CURRENT-ARCHITECTURE.md, docs/10-SECURITY.md, and docs/11-OPEN-ISSUES-AND-NEXT-STEPS.md.
2. Read server/overlay.json, apps/android/README.md, apps/ios/README.md, and vendor/UPSTREAMS.lock.json.
3. Run python scripts/generate_inventory.py and python scripts/verify_repo.py.
4. Report the current versions, source boundaries, failed or unverified release gates, and the files you intend to change.
5. Do not access or import live customer data or secrets.
6. Do not reset any database or modify release artifacts.
7. Preserve the existing Floodman brand, America/Detroit business time zone, payment tokenization boundary, Tailscale private surfaces, public customer/mobile route boundary, and actual RoomFlow layout requirement.

First task:
Create a clean staging build plan for server v4.6.7, Android 0.3.0-alpha11, and iOS 0.1.0-alpha02. Identify reproducibility gaps, mutable dependencies, missing tests, and likely migration risks. Make no code changes until the plan is approved.
```

Suggested second task after the baseline is committed:

```text
Make the Android alpha11 workflow reproducible and green. Do not weaken lint. Preserve the API capability contract and RoomFlow pinned commit. Produce exact build artifacts and checksums, then write an acceptance checklist for a physical Android device.
```
