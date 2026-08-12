# Floodman v4.6.3 build validation

## Server runtime

Passed:

- 156-file SHA-256 runtime manifest
- Python compilation for Office, Mobile API, RoomFlow importer, competitor intelligence, engineering, orchestrator, and tests
- Mobile API authentication and refresh-token smoke test
- Estimate, invoice, payment, calendar, and PDF smoke test
- Dependency-free estimate and invoice PDF smoke test
- Native RoomFlow create/update, layout capture, estimate synchronization, and catalog deduplication test
- Original Supabase dataset import and repeat-import idempotency test
- Imported workspace creation and automatic selection test
- Encrypted workspace create/select API test
- Workspace-specific job filtering test
- v4.6.2 organization-ID recovery and record backfill test
- Shell syntax for every runtime script and the v4.6.3 launcher
- JavaScript syntax for every bundled runtime script
- JSON parsing and zero Pillow/PIL import scan
- ZIP path-safety, CRC, extraction, and manifest verification

## Android source

Passed locally:

- 56-file SHA-256 source manifest
- Android XML parsing
- GitHub Actions YAML parsing
- RoomFlow native bridge JavaScript syntax
- Shell syntax for the pinned RoomFlow asset preparation script
- Kotlin structural parser scan with no syntax, redeclaration, JVM accessor collision, or unclosed-token diagnostics
- Static verification of workspace models, encrypted API methods, JavaScript interfaces, workspace-scoped save payload, selected-company state, matched server message, PDF guards, predictive back, dark mode, and no Tailscale dependency
- ZIP path-safety, CRC, extraction, and source-manifest verification

## Remaining authoritative Android gate

GitHub Actions must complete:

- `:app:compileDebugKotlin`
- `:app:testDebugUnitTest`
- `:app:lintDebug`
- `:app:assembleDebug`
- `:app:assembleRelease`
- `:app:bundleRelease`

A green GitHub run is required before installing the alpha11 APK.
