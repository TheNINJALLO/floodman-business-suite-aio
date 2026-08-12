# Testing and release

## Static checks

```bash
python scripts/generate_inventory.py
python scripts/verify_repo.py
```

These check version pins, Python syntax, shell syntax, JavaScript syntax, structured files, source manifests, sensitive-file exclusions, and key API contract strings.

## Server smoke tests

The current server source includes smoke tests for:

- Mobile API authentication and operations
- RoomFlow native sync
- RoomFlow Supabase migration
- RoomFlow workspaces
- PDF runtime without Pillow
- desktop/mobile workspace routing
- Full ERP routing

Run them in an environment containing the service dependencies and expected `PYTHONPATH`.

## Android gate

A release is not complete until all of these pass on a clean GitHub runner:

```text
compileDebugKotlin
testDebugUnitTest
lintDebug
assembleDebug
assembleRelease
bundleRelease
```

Then complete a physical-device test over public HTTPS with Tailscale disabled.

## iOS gate

1. Generate the Xcode project.
2. Build an unsigned simulator target.
3. Run simulator acceptance tests.
4. Configure Apple signing.
5. Archive and upload through the guarded TestFlight workflow.
6. Test on at least one iPhone and one iPad class device.

## Server release gate

- build from clean source
- pin upstream digests
- create SBOM and vulnerability scan
- test fresh install
- test upgrade from previous release
- test restart after abrupt stop
- test backup and restore
- test all health endpoints and public/private routes
- test PDFs and document signing
- test Square Sandbox and webhook idempotency
- record image digest, source commit, release archive checksum, and database migration level

## Compatibility

The server publishes capability and minimum-version information for native apps. Do not remove a capability or change a payload shape without a versioned migration and client release plan.
