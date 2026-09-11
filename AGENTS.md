# Codex operating instructions for Floodman Operations

## Source of truth

- Treat `server/overlay.json`, `server/VERSION`, `apps/android/VERSION`, `apps/ios/VERSION`, and `vendor/roomflow/PINNED_COMMIT` as release identity files.
- The current server contract is Floodman v4.7.3 with Mobile API `0.3.0-alpha11`.
- Do not use historical ZIPs as the editing source. Edit the extracted folders.
- Preserve the Floodman branding and the attribution `Created by Josh Aldrich` where attribution is displayed.

## Data safety

- Never delete, reset, recreate, or migrate a live database without an explicit backup, restore plan, migration script, and approval.
- Never include `Clients.csv`, live exports, `office-state.json`, signed documents, payment records, retired network-overlay state, or production logs in source control.
- All migrations must be idempotent where feasible and must record their version.
- RoomFlow Supabase imports must use stable source identifiers and must update rather than duplicate existing records.

## Payment safety

- Never store raw card numbers, expiration dates as reusable credentials, magnetic-stripe data, or CVV.
- Square card entry must return a token or processor-managed payment method. Floodman may store masked brand/last-four metadata and processor identifiers only.
- Never log payment tokens, access tokens, authorization headers, or full webhook bodies containing sensitive values.

## Authentication and public exposure

- The staff PWA, Full ERP, signing administration, API documentation, and Engineering Sandbox must be protected by the external HTTPS proxy's staff access policy.
- Public access is limited to the customer portal, signing, payments, and the narrow Mobile API gateway.
- Native apps must require HTTPS, validate the server capability contract, and use short-lived access tokens plus rotating refresh tokens.
- Do not add a public administrative endpoint or database endpoint.

## RoomFlow

- The pinned commit is `1f97817a52b916875e50cc6380c0d284072b8ce8`.
- Do not advance RoomFlow without a release note, schema/bridge review, Android build, iOS build, and synchronization regression test.
- Estimate PDFs must embed the actual captured RoomFlow layout when available. Never create a fake diagram and represent it as measured field data.

## API compatibility

- Additive changes are preferred for `/mobile-api/v1`.
- A breaking Android or iOS requirement must update the server capability list and minimum app version.
- PDF endpoints must return `application/pdf` and a valid `%PDF-` file signature. Native apps must reject JSON or HTML presented as a PDF.

## Release gates

Before changing a release version:

1. Run `python scripts/generate_inventory.py`.
2. Run `python scripts/verify_repo.py`.
3. Run server smoke tests.
4. Run Android compile, unit tests, lint, APK, and AAB packaging.
5. Run iOS simulator compilation.
6. Run TestFlight only after simulator compilation and signing configuration succeed.
7. Test a clean install, upgrade, restart, backup, and restore.
8. Record checksums and release notes.

## Coding direction

- Prefer typed models, explicit migrations, structured templates, and testable service boundaries.
- Reduce giant inline HTML and JavaScript strings over time, but preserve behavior during refactors.
- Move long-term operational state from the JSON Office store into versioned PostgreSQL tables after a migration plan is approved.
- Keep America/Detroit as the business time zone while storing timestamps in UTC.
- Keep upstream image versions pinned by digest in production.

## Floodman interface quality contract

- The active local worktree is the source of truth. Preserve unfinished and unrelated work.
- Preserve Floodman branding, `Created by Josh Aldrich` where attribution is displayed, and required third-party notices and licenses.
- Do not expose visible upstream branding on Floodman-owned Hub, Office, PWA, portal, or native-shell surfaces unless legally required.
- Preserve the existing Python-rendered, CSS/JavaScript, PWA, Android Compose, and Apple SwiftUI architecture. Do not migrate the product to another frontend framework.
- Verify interface changes in a real browser. Source inspection alone is not acceptance evidence.
- Treat desktop, narrow desktop, mobile browser, tablet, installed PWA, Android, iPhone, and iPad as distinct layout targets.
- Respect a user-selected mobile or desktop workspace mode while making that selected mode respond safely to the available width and height.
- Do not allow page-level horizontal scrolling, clipped or unreachable primary controls, fixed navigation covering content, or closed overlays intercepting focus or pointer input.
- Do not hide root overflow to conceal a broken child and do not solve stacking defects through arbitrary z-index escalation. Inspect containing blocks, overflow ancestors, transforms, filters, isolation, containment, portals, and pointer events.
- Persistent overlays require an obvious close or cancel control, Escape behavior where appropriate, bounded short-viewport layout, focus management, focus restoration, background inertness, and scroll restoration.
- Use truthful loading, empty, error, disconnected, success, and disabled states. Do not invent activity, records, provider output, or RoomFlow measurements.
- Preserve server-side authorization. Never expose secrets, payment tokens, refresh tokens, signing data, or private customer information in rendered output, screenshots, logs, or tests.
- Test console errors, failed required requests, keyboard and touch behavior, focus, overlays, safe areas, PWA lifecycle state, text zoom, dynamic content, and component-level overflow.
- Run proportionate source, browser, Android, Apple, packaging, inventory, and verification gates after changes.

### Current interface and release commands

- Inventory: `python scripts/generate_inventory.py`
- Repository verification: `python scripts/verify_repo.py`
- Server/browser/PWA smoke: set `PYTHONPATH=server/office-console` and run each `server/tests/*.py`; `server/tests/web_ui_smoke.py` starts its own isolated fictional-data server and real-browser fixture.
- Android: from `apps/android`, use JDK 17 and run `gradle --no-daemon :app:compileDebugKotlin :app:testDebugUnitTest :app:lintDebug :app:assembleDebug :app:assembleRelease :app:bundleRelease`.
- Apple source readiness: `python scripts/verify_ios_readiness.py`
- Apple simulator: from `apps/ios` on macOS/Xcode, run `xcodegen generate` and the checked-in `.github/workflows/build-ios-simulator.yml` `xcodebuild` build/test sequence with signing disabled.
- Runtime package: `python scripts/package_pterodactyl_release.py`
- Runtime verification: `python scripts/verify_pterodactyl_release.py`
