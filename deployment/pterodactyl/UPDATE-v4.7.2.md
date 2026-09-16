# Floodman Operations v4.7.2 Pterodactyl update

This is an in-place application update from v4.7.1. It preserves persistent data and installs a new versioned runtime. Do not delete `data/`, `config/`, `backups/`, or `logs/`.

## Matched files

```text
floodman-operations-runtime-v4.7.2.zip
mobile-start-v4.7.2.sh (upload as mobile-start.sh)
egg-floodman-operations-mobile-v4.7.2.json
SHA256SUMS
```

Never combine files from different version rows and never overwrite the v4.7.1 release artifacts.

## Update procedure

1. Create and complete a Pterodactyl backup.
2. Record the current server state, startup command, allocations, environment, and active runtime marker.
3. Stop the intended Floodman server and wait for Offline.
4. Preserve the current `mobile-start.sh` as `mobile-start-v4.7.1.rollback.sh` if that rollback file is not already present.
5. Upload the v4.7.2 runtime ZIP without extracting it.
6. Upload `mobile-start-v4.7.2.sh` as `mobile-start.sh`.
7. Keep the startup command `bash ./mobile-start.sh` and retain current allocations and environment values.
8. Start the server and wait for `FLOODMAN_SUITE_READY`.
9. Verify Hub, Office, Mobile API, Full ERP, RoomFlow, and API gateway health.
10. Submit one fictional signed deterministic call-intake event, verify one linked draft context and staff notification, then restart once to prove persistence.

## Rollback

Stop the server, restore `mobile-start-v4.7.1.rollback.sh` as `mobile-start.sh`, and restart. The versioned v4.7.1 runtime remains available. Restore the Pterodactyl backup only if persistent data changed and application rollback alone is insufficient.
