# Floodman Operations 4.7.1 release notes

Date: 2026-08-21

## Summary

Floodman Operations 4.7.1 packages the two server milestones completed after the frozen 4.7.0 RoomFlow Capture release: a licensed insurance-pricing import workflow and secure customer communications with payment-administrator alerts.

Services & Prices can safely identify a PLX transfer container, explain when a supported Xactimate conversion is required, download a reviewed CSV worksheet, preview every authorized row without writing data, and confirm one stable update. Insurance codes and supported source metadata remain searchable in Office and RoomFlow and appear in estimate PDFs.

Customers can now message Floodman through their existing secure estimate or invoice portal link. Conversations are scoped to the contact and service property, staff can reply in Office, both sides have read states, and retries cannot duplicate messages. Completed payments and new customer replies create durable alerts for the appropriate administrators; optional email notices omit customer message content and payment credentials. Existing native apps can obtain these alerts through the additive authenticated notification feed.

## Compatibility and identity

- Server/web/Pterodactyl advances from `4.7.0` to `4.7.1`.
- Mobile API remains `0.3.0-alpha11`; no capability or minimum-client contract was removed.
- Android remains `0.4.0-alpha01`/build 13 and iOS remains `0.1.0-alpha03`/build 3.
- RoomFlow remains pinned to `1f97817a52b916875e50cc6380c0d284072b8ce8`.
- America/Detroit remains the business time zone; stored timestamps remain UTC.
- The 4.7.0 runtime and launcher remain byte-identical historical evidence and are not overwritten.

## Local release evidence

- all 13 source smoke programs observed passing with fictional temporary data;
- customer portal coverage at 320 and 390 px, dismissible overlays, retry deduplication, property isolation, message limits, staff replies, and mobile alert read controls;
- two byte-identical Pterodactyl builds with 205 tracked runtime files plus the internal manifest;
- 12/12 portable smoke programs passed from the extracted runtime;
- 87 launcher-to-overlay preflight assertions verified against the exact packaged source;
- unchanged Android alpha01 compatibility gate completed under JDK 17/Gradle 8.13 with 8/8 tests, 27 lint advisories and zero error/fatal findings, plus debug APK, unsigned release APK, and unsigned AAB outputs;
- RoomFlow pin, native source-readiness, immutable container inputs, source manifests, generated inventory, deployment checksums, and repository verification checked by the release tools.

Current SHA-256 values:

```text
2e05a7c5386dda7931ee81cdf931585392903b94d9d93848357fc9f9546445ec  floodman-operations-runtime-v4.7.1.zip
bc3adee529c84e79ab1db03ff169b89e40339e22970eea4873e4650768a3d0fd  mobile-start-v4.7.1.sh
d1e8b08e7793f8d659c310362795a17cb89040ea3f27f58762e207c1e1c4931f  egg-floodman-operations-mobile-v4.7.1.json
```

## Boundaries

These are source and Pterodactyl upload artifacts, not evidence of a live deployment. Staging clean-install/upgrade/restart, sanitized backup/restore, physical Android and Apple device testing, signing/store upload, the container critical/high advisory scan, production provider credentials, and production rollout remain separate safety gates. No live customer, message, payment, Xactimate, signing, Supabase, or production data was read or changed while building this release.

## GitHub publication and pre-signing builds

- Release commit `ca9cd35` and its two prerequisite feature commits were pushed normally to `feature/roomflow-capture`; draft PR #1 targets `main`.
- Linux source-verification run `32494582232` passed.
- Android run `32494662846` passed and uploaded artifact `9451290230` with digest `sha256:9861d49523aea616e3603d195f8a699590eb7063e89f5b3f67a45b742525d215`.
- iOS simulator run `32494665766` passed the unsigned build and 6/6 tests and uploaded artifact `9451386408` with digest `sha256:c0bf3f4d61aa4b0b4b97517a343496c0b1c0cb54ce1755d5d44a12669eda2de6`.
- `main` was not merged, the v4.7.1 server-image workflow was not dispatched, and no signed/store or deployment action occurred.
