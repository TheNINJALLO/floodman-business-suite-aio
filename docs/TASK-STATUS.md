# Task status

Status vocabulary: `NOT STARTED`, `IN PROGRESS`, `FAILED`, `BLOCKED`, `COMPLETE`.

| Priority | ID | Task | Status | Current evidence / next action |
|---:|---|---|---|---|
| 0 | EXEC-000 | Preserve untouched handoff in Git | COMPLETE | Root manifest verified 553 files; baseline commit `a3177cc`; tag `handoff-v4.6.7`. |
| 0 | EXEC-001 | Restore execution controls and make repository verification reproducible on Windows | COMPLETE | Required controls reconstructed; Windows executable resolution repaired; inventory refreshed; `python scripts/verify_repo.py` passes with 0 warnings. |
| 1 | WEB-001 | Inventory and test every custom web route and interaction surface | COMPLETE | `server/tests/web_ui_smoke.py` renders 37 authenticated route states, public estimate/invoice/payment/receipt/PDF flows, and exercises Office/PWA/Hub/RoomFlow UI in local Edge. |
| 1 | WEB-002 | Repair usability, responsive layout, stacking, and close behavior found by WEB-001 | COMPLETE | Added dismiss/Escape/focus/bounds behavior to persistent overlays; repaired Hub initialization TDZ; desktop 1440×900 and mobile 390×844 overflow checks pass. |
| 2 | RF-001 | Fetch and verify pinned RoomFlow source and packaged feature parity | NOT STARTED | Fetch commit `1f97817a52b916875e50cc6380c0d284072b8ce8`; compare source, Android/iOS assets, server preparation, and bridge contracts. |
| 2 | RF-002 | Verify Supabase import, stable-ID updates, workspace linkage, layout capture, and repeat-import regression | NOT STARTED | Run existing smoke tests and add missing contract tests without live credentials or data. |
| 3 | AND-001 | Make Android alpha11 clean-build ready | NOT STARTED | Prepare pinned RoomFlow assets, then run compile, unit, lint, APK, and AAB gates where the Android toolchain is available. |
| 4 | IOS-001 | Make iOS alpha02 simulator-build ready | NOT STARTED | Review parity/project generation locally; run Xcode simulator build on macOS. Signing/TestFlight remains guarded. |
| 5 | SRV-001 | Run and repair local server smoke suites | COMPLETE | 2026-08-12: all 9 `server/tests/*.py` programs pass with fictional temporary state; Windows `tzdata` and portable PDF date formatting repaired. |
| 6 | PKG-001 | Verify clean derivative container build and immutable upstream inputs | NOT STARTED | Local source inspection first; image pulls/builds depend on Docker/network availability. |
| 7 | STAGE-001 | Validate clean install, upgrade, restart, backup, restore, and live route behavior in staging | BLOCKED | Requires an approved staging Pterodactyl/Tailscale node and sanitized backup. |
| 8 | DEVICE-001 | Complete Android physical-device and iPhone/iPad acceptance | BLOCKED | Requires devices, public staging HTTPS, and non-production test credentials. |
| 9 | RELEASE-001 | Signing, store upload, production deployment, and version change | BLOCKED | Explicit approval and all release gates required. |

## Resume rule

Resume `EXEC-001`, then continue automatically through the next unblocked row. Completed rows stay closed unless their inputs change or their evidence is invalidated.
