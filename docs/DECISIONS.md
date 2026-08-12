# Decisions

## DEC-001 — Preserve the supplied archive state as the immutable baseline

- Date: 2026-08-12
- Decision: Verify the root manifest before initializing Git, then commit and annotate-tag the untouched extracted handoff.
- Reason: The supplied directory had no `.git` history, while its own handoff instructions required a private repository baseline before edits.
- Evidence: 553 manifest entries passed; commit `a3177cc`; tag `handoff-v4.6.7`.

## DEC-002 — Reconstruct missing execution controls without inventing historical passes

- Date: 2026-08-12
- Decision: Create the requested master prompt and ledgers from `AGENTS.md`, packaged handoff documents, recorded version identities, and the user's current acceptance priorities.
- Reason: The named files did not exist anywhere in the byte-verified package. Their absence means there is no trustworthy prior task/test state to resume.
- Consequence: Packaged claims remain historical context; every active pass requires fresh evidence.

## DEC-003 — Keep the RoomFlow pin unchanged

- Date: 2026-08-12
- Decision: Fetch and inspect exactly `1f97817a52b916875e50cc6380c0d284072b8ce8`; do not move to a newer upstream commit during readiness work.
- Reason: Release identity and native/server compatibility depend on the reviewed pin. Advancing it crosses an explicit release safety boundary.

## DEC-004 — Resolve executables explicitly in the Windows verifier

- Date: 2026-08-12
- Decision: On Windows, replace bare executable names with the absolute path returned by `shutil.which` before `subprocess.run`.
- Reason: Windows process search selected the inaccessible WSL `bash.exe` even when Git Bash appeared first on `PATH`; the explicit Git Bash path passed the same syntax check.
- Scope: Verification tooling only; no application runtime behavior changes.

## DEC-005 — Treat the root handoff manifest as baseline evidence

- Date: 2026-08-12
- Decision: Do not rewrite root `MANIFEST.sha256` after development begins. Refresh generated inventories and the component source manifests/checksums that cover modified deliverables instead.
- Reason: Rewriting the root manifest would erase the byte-level record of the untouched handoff preserved by `handoff-v4.6.7`.
