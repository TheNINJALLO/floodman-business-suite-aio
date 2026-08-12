# Test matrix

Outcomes: `PASS`, `FAIL`, `BLOCKED`, `NOT RUN`. A historical statement is context, not current evidence.

| ID | Area | Command / method | Latest outcome | Evidence |
|---|---|---|---|---|
| T-001 | Handoff integrity | Verify every entry in root `MANIFEST.sha256` with SHA-256 | PASS | 2026-08-12: 553 files checked; zero missing or mismatched before baseline commit. |
| T-002 | Git provenance | `git status`, baseline commit, annotated handoff tag | PASS | 2026-08-12: commit `a3177cc`; tag `handoff-v4.6.7`; no prior Git history existed. |
| T-003 | Generated inventory | `python scripts/generate_inventory.py` | PASS | 2026-08-12: 304 routes, 180 environment names, 551 inventoried files, 73,102 text lines; current file hashes recorded in `docs/generated/SOURCE_MANIFEST.csv`. |
| T-004 | Repository verification | `python scripts/verify_repo.py` | PASS | 2026-08-12: full run passed with 0 warnings after resolving Windows executables to absolute paths. The initial 50 shell-launch failures are retained in history as environment evidence, not source failures. |
| T-005 | Server smoke suite | `scripts/run_server_smoke_tests.sh` or platform-equivalent commands | NOT RUN | Await EXEC-001 and WEB/RF inspection. |
| T-006 | Web route/render behavior | Route smoke tests plus browser interaction suite | NOT RUN | WEB-001. |
| T-007 | Overlay/responsive behavior | Desktop/tablet/mobile dialog, drawer, loading, Escape, and close-path checks | NOT RUN | WEB-001/WEB-002. |
| T-008 | RoomFlow pin and feature inventory | Fetch fixed commit and compare bridge/prepared assets | NOT RUN | RF-001; network source absent. |
| T-009 | RoomFlow Supabase repeat import | Fictional temporary fixtures; run import twice and compare stable mappings/counts | NOT RUN | RF-002; no live credentials permitted. |
| T-010 | Android compile | `compileDebugKotlin` | NOT RUN | AND-001. |
| T-011 | Android unit tests | `testDebugUnitTest` | NOT RUN | AND-001. |
| T-012 | Android lint | `lintDebug` | NOT RUN | AND-001; lint may not be weakened. |
| T-013 | Android APK/AAB | `assembleDebug assembleRelease bundleRelease` | NOT RUN | AND-001. |
| T-014 | iOS simulator | project generation and unsigned `xcodebuild` | BLOCKED | Requires macOS/Xcode; Windows source review still pending. |
| T-015 | Live staging | clean install, upgrade, restart, backup/restore, Pterodactyl/Tailscale routes | BLOCKED | No approved staging node or sanitized backup. |
| T-016 | Signing/device/store | signed builds, physical devices, TestFlight/Play | BLOCKED | Requires credentials, devices, and explicit approval. |
