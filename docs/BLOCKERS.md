# Blockers

| ID | Scope | State | Blocking condition | Work that can continue |
|---|---|---|---|---|
| BLK-001 | Original execution history | RESOLVED | The requested master prompt and five ledgers were absent from the byte-verified handoff, and no prior Git metadata existed. | Reconstructed controls now record the handoff baseline explicitly. |
| BLK-002 | Shell verification on Windows | RESOLVED | `subprocess.run(["bash", ...])` invoked the denied Windows WSL shim despite Git Bash being first on `PATH`. | `verify_repo.py` now resolves the executable path explicitly on Windows; full verification passes with 0 warnings. |
| BLK-003 | Pinned RoomFlow source | RESOLVED | Exact commit `1f97817a52b916875e50cc6380c0d284072b8ce8` was fetched into the ignored vendor checkout and verified clean with 1,032 tracked files. | The reproducible fetch and validation scripts retain the pin; no upstream source is committed. |
| BLK-004 | iOS compilation | OPEN | Xcode and an iOS simulator require a macOS runner. | 2026-08-13 local source/project/asset/workflow readiness is complete; run the checksum-producing unsigned simulator workflow on macOS 26/Xcode 26. |
| BLK-005 | Staging acceptance | OPEN | No approved staging Pterodactyl/Tailscale node or sanitized backup is present. | Complete all local source, unit, smoke, and package checks. |
| BLK-006 | Native device acceptance | OPEN | Physical Android/iPhone/iPad devices and public staging HTTPS are external. | Produce unsigned/local artifacts and acceptance checklists. |
| BLK-007 | Signing and production release | OPEN | Apple/Android signing, provider credentials, store uploads, and production deployment require explicit approval. | Do not access credentials; finish pre-signing gates. |
| BLK-008 | Container advisory scan | OPEN | Docker Scout 1.23.1 did not return a local CVE report within five minutes, so no vulnerability result exists to evaluate. | The immutable clean build and isolated contract audit are complete. Re-run a critical/high scan in CI or a dedicated scanner and review the generated SBOM before any release. |
| BLK-009 | v4.6.8 derivative image build | OPEN | Docker Desktop is installed but its service is stopped/manual and the daemon did not respond. Starting the engine may automatically restart unrelated existing containers, which is outside DEC-016 and the authorized isolated test scope. | The Pterodactyl runtime/launcher/egg build, static container-input verification, and all source/package tests are complete. Build and audit the derivative image on a clean runner or an owner-approved isolated Docker engine. |

An open blocker applies only to its named scope and does not pause unrelated tasks.
