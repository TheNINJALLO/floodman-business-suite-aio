# Floodman Operations v4.7.3 Pterodactyl update

This release simplifies the daily Business Suite workspace and makes property lists customer-scoped. It retains the Voice AIO, ERP, RoomFlow, signing, messaging, and notification contracts from v4.7.2.

## Matched files

```text
floodman-operations-runtime-v4.7.3.zip
mobile-start-v4.7.3.sh (upload as mobile-start.sh)
egg-floodman-operations-mobile-v4.7.3.json
```

## Update sequence

1. Record the current image digest and active runtime.
2. Create and verify a complete Pterodactyl backup.
3. Stop the server and wait for Offline.
4. Preserve the previous launcher and runtime as rollback artifacts.
5. Install the matched v4.7.3 runtime and launcher, or deploy the unified image that embeds them.
6. Start the server and wait for both Voice AIO and Business Suite readiness.
7. Verify the voice health endpoint, Floodman Office, customer-scoped properties, RoomFlow, and restart persistence.

Never delete or recreate `data/`, databases, recordings, customer files, or configuration as part of this update.
