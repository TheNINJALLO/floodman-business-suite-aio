# Task status

Status vocabulary: `NOT STARTED`, `IN PROGRESS`, `FAILED`, `BLOCKED`, `COMPLETE`.

| Priority | ID | Task | Status | Current evidence / next action |
|---:|---|---|---|---|
| 0 | EXEC-000 | Preserve untouched handoff in Git | COMPLETE | Root manifest verified 553 files; baseline commit `a3177cc`; tag `handoff-v4.6.7`. A broad `data/` ignore was later found to have omitted four unchanged Android package sources; their root hashes were reverified and they are tracked with AND-001. Policy-excluded archives/environment evidence remain represented by the immutable root manifest. |
| 0 | EXEC-001 | Restore execution controls and make repository verification reproducible on Windows | COMPLETE | Required controls reconstructed; Windows executable resolution repaired; inventory refreshed; `python scripts/verify_repo.py` passes with 0 warnings. |
| 1 | WEB-001 | Inventory and test every custom web route and interaction surface | COMPLETE | `server/tests/web_ui_smoke.py` renders 37 authenticated route states, public estimate/invoice/payment/receipt/PDF flows, and exercises Office/PWA/Hub/RoomFlow UI in local Edge. |
| 1 | WEB-002 | Repair usability, responsive layout, stacking, and close behavior found by WEB-001 | COMPLETE | Added dismiss/Escape/focus/bounds behavior to persistent overlays; repaired Hub initialization TDZ; desktop 1440×900 and mobile 390×844 overflow checks pass. |
| 2 | RF-001 | Fetch and verify pinned RoomFlow source and packaged feature parity | COMPLETE | Exact clean pin verified (1,032 tracked files); full upstream/server/Android/iOS bundles validated; missing native `cost-tests.js`, Windows fetch false-success, and duplicate job-renderer package defect repaired without changing the pin. |
| 2 | RF-002 | Verify Supabase import, stable-ID updates, workspace linkage, layout capture, and repeat-import regression | COMPLETE | Fictional repeat import and mocked authenticated HTTP/RLS contract pass; stable records update without duplicates, legacy layouts import, real layout capture remains required, and passwords/tokens are not persisted. |
| 3 | AND-001 | Make Android alpha11 clean-build ready | COMPLETE | Exact JDK 17/Gradle 8.13/SDK 36 gate passed: compile, 1/1 unit test, lint with 0 errors, debug APK, unsigned release APK, and unsigned release AAB. RoomFlow pin metadata and runtime are embedded; hashes are recorded. Device/signing remain external blockers. |
| 4 | IOS-001 | Make iOS alpha02 simulator-build ready | BLOCKED | All local source/project/asset/workflow gates pass: HTTPS/minimum-version/capability/PDF/keychain/refresh checks, 18 icon slots, dismissible loopback RoomFlow, exact pin, and 9/9 server smokes. Actual unsigned simulator compilation requires macOS/Xcode (BLK-004); signing/TestFlight remains guarded. |
| 5 | SRV-001 | Run and repair local server smoke suites | COMPLETE | 2026-08-12: all 9 `server/tests/*.py` programs pass with fictional temporary state; Windows `tzdata` and portable PDF date formatting repaired. |
| 6 | PKG-001 | Verify clean derivative container build and immutable upstream inputs | COMPLETE | 2026-08-13: immutable image/action pins, 128 transitive Python constraints, restricted context, and a clean `--pull --no-cache` linux/amd64 derivative build passed. A network-isolated runtime audit verified all 174 server manifest entries, package constraints, non-root ownership, empty inherited placeholder secrets, and no packaged live-state files. Local advisory scanning remains BLK-008. |
| 6 | PKG-002 | Refresh installable Pterodactyl v4.6.7 artifacts from the verified source | COMPLETE | 2026-08-13: deterministic packager rebuilt the deployable runtime ZIP from 162 reviewed tracked server files, synchronized the canonical/release launchers, and replaced the egg's stale v3.3.0 bootstrap with the current launcher and immutable 3.2.2 base. Internal hashes, 8/8 packaged smoke programs, launcher syntax, and release checksums pass. Historical `release-artifacts/` remain untouched. |
| 7 | STAGE-001 | Validate clean install, upgrade, restart, backup, restore, and live route behavior in staging | BLOCKED | Requires an approved staging Pterodactyl/Tailscale node and sanitized backup. |
| 8 | DEVICE-001 | Complete Android physical-device and iPhone/iPad acceptance | BLOCKED | Requires devices, public staging HTTPS, and non-production test credentials. |
| 9 | RELEASE-001 | Signing, store upload, production deployment, and version change | BLOCKED | Explicit approval and all release gates required. |

## Resume rule

Resume `EXEC-001`, then continue automatically through the next unblocked row. Completed rows stay closed unless their inputs change or their evidence is invalidated.
