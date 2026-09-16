# Floodman interface layout hardening

## Authorization and baseline

- Authorization date: 2026-08-28.
- Successor task: WEB-007, extending the narrower completed WEB-002 evidence without rewriting it.
- Initial branch and commit: `feature/roomflow-capture` at `b3cf9c2ba359ad187be441d99d1413b2914743d6`.
- Initial worktree: clean and synchronized with `origin/feature/roomflow-capture`; no modified or untracked files existed before project-local skill installation.
- Protected identities: server 4.7.1, Mobile API 0.3.0-alpha11, Android 0.4.0-alpha01/build 13, iOS 0.1.0-alpha03/build 3, RoomFlow `1f97817a52b916875e50cc6380c0d284072b8ce8`.
- Data boundary: fictional temporary state only. No live customers, documents, payments, messages, signing records, imports, provider credentials, or production logs were used.

## Architecture map

| Layer | Active implementation | Layout or lifecycle ownership |
|---|---|---|
| Office, CRM, public portal | FastAPI and Python-rendered HTML in `server/office-console/app/ui.py` | Shared inline base CSS, semantic Office shell, route-specific forms/cards/tables, one ERP/Office/RoomFlow session |
| Workspace cascade | `server/pwa/workspace-mode.css` loaded after the inline base CSS | Explicit desktop/mobile density choice; viewport independently decides fixed sidebar versus dismissible drawer |
| PWA | `floodman-pwa.css`, `floodman-pwa.js`, `floodman-sw.js` | Install prompt/toast/network state, standalone class, offline fallback, private-page network-only policy |
| Hub and Full ERP launch surface | `server/hub/*` plus the canonical launcher/Nginx gateway | Drawer, iframe overlay, focus restoration, authenticated same-origin launch and recovery |
| Integrated RoomFlow | Exact pinned upstream export plus `server/roomflow/floodman-panel.*`, legacy adapter, and suite-owned capture dialog | Floodman workspaces and unified login, responsive estimator iframe/panel, capture/review overlays and canvas containment |
| Android | Jetpack Compose shell, local RoomFlow WebView, ARCore/optional Depth capture | Material navigation adapts at 700 dp; safe-drawing/system-bar/cutout insets protect Compose, WebView, and scanner controls |
| Apple | SwiftUI shell, local WKWebView, RoomPlan with ARKit/LiDAR fallback | Native safe areas/system sheets; a 44-point native RoomFlow close target remains outside web content |
| Verification and packaging | `server/tests/web_ui_smoke.py`, native readiness/build gates, deterministic Pterodactyl packager | Cross-engine layout contracts, screenshots, source/package manifests, pinned egg and launcher preflights |

The Office CSS order is intentional: PWA base resources load first, the shared server-rendered base establishes tokens/components, and `workspace-mode.css` supplies the final workspace-specific cascade. JavaScript applies the workspace attribute before first paint and updates drawer inertness, focus trapping, Escape behavior, and focus restoration after load.

## Expanded acceptance difference

WEB-002 established browser evidence at 1440×900 and 390×844. WEB-007 covers all supplied viewports: 320×568, 360×640, 375×667, 390×844, 412×915, 430×932, 540×720, 667×375, 844×390, 768×1024, 820×1180, 1024×768, 1024×1366, 1280×720, 1366×768, 1440×900, 1536×864, 1920×1080, and 2560×1440. It also tests 719/720/721 and 1099/1100/1101 transition widths.

Chromium executes every viewport against representative desktop, mobile, settings, contacts, estimate editor, RoomFlow, RoomFlow import, customer portal, upstream RoomFlow, and Hub routes. Firefox and WebKit execute five representative phone/landscape/tablet/desktop widths against the same route families. Separate checks cover a 200-percent reflow proxy, 390×480 virtual-keyboard layout, a 512-character unbroken token, reduced motion, forced colors, skip-link keyboard order, PWA standalone display mode, online/offline transitions, service-worker cache contents, and drawer/dialog focus behavior.

## Audit and repairs

| Surface and state | Root cause | Repair | Verification result |
|---|---|---|---|
| Desktop workspace below the old fixed minimum | A desktop preference forced a 1120 px document even on smaller windows | Removed the minimum width; density remains a user choice while navigation responds to viewport | All required and transition widths pass without root overflow |
| Mobile workspace on a 1440 px display | Header/nav child geometry existed only inside the <=1100 px media query, allowing SVGs to expand into a page-covering overlay | Defined the complete mobile header, drawer, button, and SVG geometry for mobile workspace at every width | Visual review found the defect; rerun and an explicit <=48 px shell-icon assertion pass |
| RoomFlow at 320 px | Fixed canvas/intrinsic media width escaped the panel | Constrained canvas, image, SVG, and video media to the panel and made iframe height adaptive | 320 px RoomFlow/capture and all route-family overflow contracts pass |
| Closed Hub and RoomFlow overlays | Visually hidden controls could remain keyboard reachable | Apply `inert` while closed, trap focus while open, support Escape, and restore the opener | Chromium interaction tests and cross-engine hidden-focus scans pass |
| Office drawer at narrow explicit desktop widths | Drawer state assumed workspace mode alone implied a fixed sidebar | Fixed-sidebar state now requires desktop mode and a >=1101 px media match | 1099/1100/1101 state, ARIA, inertness, Escape, and focus restoration pass |
| PWA network/install chrome | Ad-hoc extreme z-index values and a persistent online badge competed with product controls | Added named layer tokens, dismissible status/toasts, coherent SVG actions, safe-area placement, and reduced-motion behavior | Standalone, install, dismiss, offline, and fixed-surface bounds checks pass |
| PWA private-data cache | Staff navigation URLs were listed in the service-worker precache | Removed `/workspace` and `/full-erp`; authenticated Office routes remain network-only | Runtime cache inspection proves no Office/workspace/Full ERP route is cached |
| Long forms with mobile keyboard | Fixed bottom navigation could reduce the visible focus area | Added safe-area-aware scroll padding and focus margins for editable controls | Focused estimate field remains above mobile navigation at 390×480 |
| Android target SDK 36 shells | WebView and AR capture controls did not explicitly consume system-bar/display-cutout insets; login/lock screens lacked Compose safe drawing padding | Added `WindowInsetsCompat` listeners and `safeDrawingPadding()` | Fresh JDK 17 compile, 8/8 tests, lint, debug/release APK, and AAB gates pass |
| Apple RoomFlow close action | The explicit close glyph used a 32-point frame | Increased the native target to 44×44 points | Apple readiness verifier passes; current source still requires a macOS/Xcode compile under BLK-015 |
| Visual system | Multiple UI layers requested unavailable web fonts and mixed emoji/text action symbols | Consolidated on platform UI fonts and one coherent inline SVG action family while preserving Floodman colors/branding | Cross-engine screenshots and source validators pass |

## Evidence

- Five project-local UI/testing skill packages are pinned and documented in `.agents/skills/SOURCES.md`. Their source-data validators, unique-name scan, relative-link audit, forbidden-directory audit, and strict-JSON repository compatibility pass.
- Final browser result: `Floodman web routes, responsive layouts, and dismissible overlay smoke test passed` after the complete expanded matrix.
- All 13 server smoke programs pass together with fictional temporary state.
- Final screenshots:
  - `docs/evidence/ui-layout/final/chromium-320x568-office-mobile-mobile-1.png`
  - `docs/evidence/ui-layout/final/chromium-390x844-office-roomflow.png`
  - `docs/evidence/ui-layout/final/chromium-1024x768-office-desktop-desktop-1.png`
  - `docs/evidence/ui-layout/final/chromium-1440x900-office-settings.png` (mobile workspace intentionally retained on a wide screen)
  - `docs/evidence/ui-layout/final/chromium-1440x900-office-settings-desktop-1.png`
- Android used checksum-verified Temurin 17.0.20.1+1, Gradle 8.13, SDK/build tools 36.1.0. Forced compile/unit/lint passed 36/36 tasks in 9m33s; 8 tests passed; lint contained 27 advisories and 0 error/fatal findings. Packaging passed 99 tasks. Artifact hashes are recorded in the versioned Android evidence.
- Apple Windows-available source readiness passes for 11 Swift files, 18 icon slots, HTTPS/capability/PDF/Keychain/RoomFlow/workflow contracts. This Windows host cannot perform the current Xcode simulator compile.
- The refreshed fresh-server runtime is deterministic at SHA-256 `2775227e411ae5ecbc80d9eee88509864971d5988f1510af77e4fdc9bce9b989`; all 205 internal hashes, 87 launcher preflights, pinned base egg, launcher syntax, and 12 portable extracted smokes pass.
- The originally published 2026-08-21 v4.7.1 artifact hashes remain recorded separately in `deployment/releases/SHA256SUMS-v4.7.1-published-20260821` and in Git release commit `ca9cd3580521ed51431a075be35e88b5e2cecb27`.

## Acceptance boundary

WEB-007 implementation and every Windows/local source/package gate are complete. The overall cross-platform release is only partially complete because the current Apple close-target edit has not been compiled on macOS/Xcode, physical Android/iPhone/iPad capture and rotation remain external, and the fresh Pterodactyl bundle has not been started, restarted, backed up, or restored on an approved staging node. These are BLK-015, BLK-006, and BLK-005 respectively. Signing, store upload, image publication, live credentials/data, and production deployment remain outside authorization.
