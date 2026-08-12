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
- Live Tailscale Serve/Funnel routing.
- Android Gradle compile/lint/APK/AAB from this monorepo.
- Android physical-device acceptance.
- Apple Xcode simulator build.
- Apple signed archive/TestFlight upload.
- Real Square, Twilio, OpenAI, Documenso or Gauzy production transactions.

Those remain authoritative external gates.
