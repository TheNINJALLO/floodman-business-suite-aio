# Test matrix

Outcomes: `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`. A historical statement is context, not current evidence.

| ID | Area | Command / method | Latest outcome | Evidence |
|---|---|---|---|---|
| T-001 | Handoff integrity | Verify every entry in root `MANIFEST.sha256` with SHA-256 | PASS | 2026-08-12: 553 files checked; zero missing or mismatched before baseline commit. |
| T-002 | Git provenance | `git status`, baseline commit, annotated handoff tag | PASS | 2026-08-12: commit `a3177cc`; tag `handoff-v4.6.7`; no prior Git history existed. |
| T-003 | Generated inventory | `python scripts/generate_inventory.py` | PASS | 2026-08-12 WEB milestone refresh: 310 routes, 180 environment names, 552 inventoried files, 73,645 text lines; ignored virtual environments and test caches are excluded. |
| T-004 | Repository verification | `python scripts/verify_repo.py` | PASS | 2026-08-12: full run passed with 0 warnings after resolving Windows executables to absolute paths. The initial 50 shell-launch failures are retained in history as environment evidence, not source failures. |
| T-005 | Server smoke suite | Run every `server/tests/*.py` with the venv Python and Office `PYTHONPATH` | PASS | 2026-08-12: 9/9 passed: dual workspace, ERP routing, Mobile API, mobile operations, PDF runtime, RoomFlow native/import/workspace, and web UI. |
| T-006 | Web route/render behavior | `server/tests/web_ui_smoke.py` TestClient and local Edge | PASS | 2026-08-12: 37 authenticated route states and public estimate/invoice/payment/receipt/PDF flows rendered successfully from fictional temporary data. |
| T-007 | Overlay/responsive behavior | `server/tests/web_ui_smoke.py` at 1440×900 and 390×844 | PASS | 2026-08-12: Office navigation, PWA toast, Hub drawer/module overlay, active RoomFlow panel, and legacy RoomFlow modal all close; selected desktop/mobile routes have no document-level horizontal overflow. |
| T-008 | RoomFlow pin and feature inventory | Fetch fixed commit and compare bridge/prepared assets | NOT RUN | RF-001; network source absent. |
| T-009 | RoomFlow Supabase repeat import | `server/tests/roomflow_supabase_import_smoke.py` | PASS | 2026-08-12: fictional dataset imported twice; stable mapped records updated without duplicates and local-only contact fields were preserved. RF-002 will expand source/bridge evidence. |
| T-010 | Android compile | `compileDebugKotlin` | NOT RUN | AND-001. |
| T-011 | Android unit tests | `testDebugUnitTest` | NOT RUN | AND-001. |
| T-012 | Android lint | `lintDebug` | NOT RUN | AND-001; lint may not be weakened. |
| T-013 | Android APK/AAB | `assembleDebug assembleRelease bundleRelease` | NOT RUN | AND-001. |
| T-014 | iOS simulator | project generation and unsigned `xcodebuild` | BLOCKED | Requires macOS/Xcode; Windows source review still pending. |
| T-015 | Live staging | clean install, upgrade, restart, backup/restore, Pterodactyl/Tailscale routes | BLOCKED | No approved staging node or sanitized backup. |
| T-016 | Signing/device/store | signed builds, physical devices, TestFlight/Play | BLOCKED | Requires credentials, devices, and explicit approval. |
| T-017 | JavaScript and generated shell syntax | `node --check` on PWA/Hub/RoomFlow scripts; Git Bash `bash -n` on launcher and deployment launcher | PASS | 2026-08-12: all four JavaScript assets and both shell launchers passed. PowerShell's bare `bash` selected the denied WSL shim; explicit `C:\Program Files\Git\bin\bash.exe` passed. |
| T-018 | Historical v3.1.1 Office tests against v4.6.7 | Two selected provenance pytest cases | FAIL | 2026-08-12: stale tests expect the retired “Floodman Office” label and `/setup` root redirect after owner creation; current source intentionally uses “Floodman Operations” and `/office/desktop`. These provenance tests are retained as historical artifacts, not current gates. |
