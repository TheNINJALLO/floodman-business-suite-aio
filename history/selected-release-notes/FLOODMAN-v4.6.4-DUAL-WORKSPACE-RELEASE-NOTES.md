# Floodman Operations v4.6.4

## Dedicated desktop and mobile workspaces

Floodman now exposes three intentional web entry points:

- `/office/desktop?desktop=1` for the desktop operations command center.
- `/office/mobile?mobile=1` for the phone and tablet field interface.
- `/workspace` for automatic device selection and the installed PWA.

The full ERP remains available at `/?desktop=1#/pages/dashboard`.

## Corrected routing

The earlier PWA always started at `/office/mobile`, and the Hub used a coarse-pointer media query that could classify touch-enabled Windows computers as mobile. v4.6.4 removes that rule and uses mobile browser identity only. Explicit desktop and mobile choices are persisted per browser and always win over automatic detection.

## Current frontend assets

Nginx now serves the v4.6.4 Hub, PWA, icons, install page, service worker, and adaptive launcher from the active runtime. Stale v4.1.0 frontend aliases are rejected by launcher preflight.

## PWA migration

The manifest now starts at `/workspace?source=pwa`. Desktop and Mobile shortcuts are included. The service worker and installation page use release 4.6.4 and route notifications through the adaptive workspace.

## Preserved functionality

This is a web-routing and presentation correction. It retains the v4.6.3 RoomFlow workspace recovery, Supabase import, Android alpha11 Mobile API contract, dependency-free RoomFlow PDF images, estimates, invoices, payments, scheduling, documents, and Tailscale setup.

Android 0.3.0-alpha11 does not need to be rebuilt.
