# Floodman Operations for Android

Native Android staff application for Floodman Operations.

## Release

```text
App version: 0.4.0-alpha01 (build 13)
Current server runtime: Floodman Operations v4.7.0
Minimum capability-compatible server: Floodman Operations v4.6.3
Android package: com.floodman.operations
Minimum Android: Android 9 (API 28)
Time zone: America/Detroit
```

Android 0.4.0-alpha01 retains the additive v4.6.3 Mobile API compatibility floor while matching the current v4.7.0 server. It adds real ARCore room capture with optional Depth, guided fallback, reviewed geometry, and durable offline synchronization. RoomFlow customer/property searches and saves remain scoped to the selected company. Install the server runtime first. The app checks the server capability contract during login and refuses to operate against an incompatible server instead of displaying JSON or HTML as an estimate or PDF.

## Original RoomFlow migration

The bundled RoomFlow workspace now has a **Cloud** action that imports the data visible to the original RoomFlow Supabase account:

- customers and job/property relationships
- RoomFlow jobs and complete saved project snapshots
- rooms, measurements, layout geometry, and costing snapshots when available
- shared estimate catalog items
- estimates, grouped headers, and estimate lines

The email and password are transmitted through the encrypted Floodman Mobile API for that import request only. They are not saved in Android or Floodman. Supabase row-level security continues to decide what the signed-in RoomFlow user can read.

The import is idempotent. Running it again updates matched records instead of creating another copy.

Historical jobs imported from Supabase are marked as needing an actual layout capture. Open each job and press **Save** once. Android captures the real RoomFlow canvas and Floodman attaches it to the job and estimate PDF. Floodman does not invent a placeholder drawing.

## Included operations

- Public encrypted Mobile API. The Android phone does not need the Tailscale app.
- Existing Floodman PWA remains private through Tailscale Serve.
- Device enrollment, rotating refresh tokens, encrypted session storage, biometric/device-PIN unlock, and remote device revocation.
- Dashboard, customers, properties, notes, tags, documents, estimates, invoices, payments, tasks, announcements, notifications, scheduling, employee assignment, RoomFlow, and time clock.
- Full estimate and invoice lifecycle, including editable grouped headers, PDFs, sending, authorization, acceptance, deposits, payments, conversion, voiding, and eligible deletion.
- Server-verified PDF downloads. Estimate and invoice files must return `application/pdf` and begin with `%PDF-` before Android opens them.
- System, light, and dark appearance modes.

## Bundled Floodman RoomFlow workspace

The Android package carries a pinned local copy of the RoomFlow field-estimating engine. It opens under Android WebView's secure app-assets origin, so field work does not require the private PWA or the Tailscale app.

RoomFlow supports guided estimating, 2D sketching, custom shapes, camera/AR tools where supported, 3D review, measurements, material quantities, internal costing, grouped scope, proposal tools, customer/property linking, complete snapshot restoration, actual layout capture, and synchronization into a Floodman estimate.

## Build requirements

- JDK 17
- Android SDK 36
- Gradle 8.13
- Android Gradle Plugin 8.13.2
- Kotlin 2.3.20

## Configuration

Copy `local.properties.example` to `local.properties` and set:

```properties
FLOODMAN_API_BASE_URL=https://floodman-operations.tail274417.ts.net/mobile-api/
SQUARE_APPLICATION_ID=YOUR_SQUARE_SANDBOX_APPLICATION_ID
```

The API URL must use HTTPS and end in `/mobile-api/`.

## Build

```bash
gradle --no-daemon :app:compileDebugKotlin
gradle --no-daemon :app:testDebugUnitTest :app:lintDebug
gradle --no-daemon :app:assembleDebug :app:assembleRelease :app:bundleRelease
```

Use the included GitHub Actions workflow for the authoritative Android SDK build and artifact packaging.

Local build-13 evidence and package hashes are recorded in `docs/ANDROID_BUILD_EVIDENCE-v0.4.0-alpha01.md`. Release APK/AAB outputs remain unsigned until approved production signing credentials are supplied.
