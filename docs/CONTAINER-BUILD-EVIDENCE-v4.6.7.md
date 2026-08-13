# Floodman Operations v4.6.7 container build evidence

- Date: 2026-08-13
- Task: PKG-001
- Host tools: Docker 29.6.2; Docker Compose 5.3.1

## Reviewed inputs

- Floodman AIO base OCI index: `sha256:3c2d611d64980589a0680bf6c467af73ea8a2a519a51252be577ea78150c37e5`
- Floodman AIO linux/amd64 manifest: `sha256:d11f6369084d407ac26d5f0702541dc8d813169c108cf7ef4b4d6e23ba11be6d`
- Direct Python requirements are fixed; five service constraint files fix 128 transitive package entries.
- `.dockerignore` is deny-by-default and admits only reviewed server/container inputs.
- Active OCI images and workflow actions are checked by `scripts/verify_container_inputs.py`.

Local input SHA-256 values at the audited build:

```text
ad57f4019dd9aa69e0d4fd161eb86c2f3a0f8f17ef3feed2e7830c0bd66908db  .dockerignore
8b9bc0eaabfca235befcb1ede30c1eca321f9835605ab979f7f956b21821be5d  containers/derivative/Dockerfile
a6720785e1443938c3b34298a29bb2f8a27d82efaabc7a195773ae9a4fa3ace2  containers/base-aio/Dockerfile
a8406f7b039217c3d9fb97a672058c2793f964d24befbe74ce03f3832653667d  server/MANIFEST.sha256
e2c030d6a19e6a0a264d0668f0f49e705dff39b691d5161508528f779cb2dff9  vendor/UPSTREAMS.lock.json
2e9541be68b5877fd62b0a1211c6f34f57d6db8cf5eda0b1031c11651443a328  scripts/verify_container_inputs.py
```

## Build

The derivative image was built for linux/amd64 with `--pull --no-cache`. The clean constrained build completed successfully. A subsequent ownership-only optimization reused those proven dependency layers and produced:

```text
local image ID:  sha256:dc62f410562383bd43ce75a97f7c714b244954e569f8a73d7e989e50d2ff3311
OCI manifest:    sha256:36958ff12fc65d28cdfb30e2c2a9a46e09f306d99675308c3e485f374d7bab96
OCI config:      sha256:ab1f9a9fb0c25f7bcdb3fc17eb70e82f0c11aa6bc1a693504517c59045cfa50c
OCI attestation: sha256:039c807a6e814de939e1d81eb2138b8cf247bed8038f9c3b8267a491fcc70b4c
OCI index:       sha256:aca3ab504d901ceda58637297b219270848090589b893e2b2037bddfd8226ba8
created:         2026-08-13T13:53:54.524351944Z
size:            2,210,207,729 bytes
runtime user:    container (uid 1000)
```

The labels identify Floodman Operations v4.6.7, authored by Josh Aldrich. Inherited AIO development placeholder values for the session/JWT secrets are explicitly empty in the derivative image; runtime launch code must generate or receive real values without logging them.

## Isolated audit

A one-shot container was run with `--network none`, no mounts, and no published ports. It did not start the Floodman services. The audit passed:

- all 174 `server/MANIFEST.sha256` entries matched;
- `Clients.csv` and `office-state.json` were absent;
- all Floodman application files were owned by `container`;
- dependency paths had no world-writable entries;
- the installed package list for orchestrator, messaging AI, competitor intelligence, Office, and local lab exactly matched its committed constraint set;
- release version, runtime user, labels, and cleared inherited secret placeholders matched the contract.

The Docker host already contained running Floodman/support containers. They were not started, stopped, restarted, mounted, or used for this test. Live startup, persistence, restart, backup, and restore remain STAGE-001.

## Unfinished external gate

Docker Scout 1.23.1 returned no critical/high SARIF report within five minutes. The process was stopped and no pass is claimed. BLK-008 requires a completed advisory report and SBOM review before release. The CI build is configured to produce provenance and an SBOM and to record the published image digest.
