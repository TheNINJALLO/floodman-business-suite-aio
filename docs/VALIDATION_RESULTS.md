# Handoff validation results

Validation performed while assembling this repository:

## Static repository verification

```text
Python AST parsing: passed
JSON parsing: passed
Android XML parsing: passed
Apple plist parsing: passed
Shell syntax (bash -n): passed
JavaScript syntax (node --check): passed
YAML parsing: passed
Server, Android and Apple source-manifest verification: passed
Version/capability contract checks: passed
High-risk secret-pattern scan: passed after excluding known JPEG test fixtures
Live customer/auth-key file checks: passed
```

## Packaged server smoke tests

Run with:

```bash
bash scripts/run_server_smoke_tests.sh
```

Results during handoff assembly:

```text
dual_workspace_smoke.py: passed
full_erp_routing_smoke.py: passed
mobile_api_smoke.py: passed
mobile_operations_smoke.py: passed
pdf_runtime_smoke.py: passed
roomflow_native_smoke.py: passed
roomflow_supabase_import_smoke.py: passed
roomflow_workspace_smoke.py: passed
```

## What was not run in this environment

- Docker build of the derivative or complete AIO image.
- Live Pterodactyl/Wings startup with existing data.
- Live `oninetwork.com` DNS, TLS certificates, reverse-proxy routing, and staff access rules.
- Android physical-device acceptance.
- Apple Xcode simulator build.
- Apple signed archive/TestFlight upload.
- Real Square, Twilio, OpenAI, Documenso or Gauzy production transactions.

Those remain authoritative external gates.

## HTTPS001 external-HTTPS validation — 2026-08-28

- Tailscale download, authentication, Serve/Funnel, watchdog, Supervisor, egg, and runtime-package inputs are absent from the current deployment path.
- The four `oninetwork.com` origins and 9000/9001/9003/9004 gateway contract pass the static launcher, egg, Nginx, native-default, and package verifier.
- Two consecutive component builds are byte-identical. The runtime contains 203 internally verified files and all 12 portable smoke programs pass from a clean extraction.
- All 13 source smoke programs pass; the browser suite required one isolated rerun after a transient local WebKit navigation error and then passed.
- Android JDK 17/Gradle 8.13 clean compile, 8 unit tests, lint, debug/release APK, and release AAB packaging pass with the exact `https://api.oninetwork.com/mobile-api/` origin embedded. Release outputs remain unsigned.
- Apple source readiness passes for 11 Swift files and 18 icon slots. A current macOS/Xcode compile remains BLK-015.
- Live DNS, certificates, proxy forwarding/access policy, node startup/restart, backup/restore, and physical-device acceptance remain BLK-005/BLK-006 and are not claimed.
