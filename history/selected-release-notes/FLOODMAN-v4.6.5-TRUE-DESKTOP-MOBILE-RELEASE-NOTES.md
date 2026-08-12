# Floodman Operations v4.6.5

## True desktop and separate mobile workspaces

This cumulative release repairs the private web entry point and the desktop
layout boundary without changing the Android alpha11 API contract.

### Root no longer depends on the upstream ERP

The exact private root route now opens `/workspace`, which selects the proper
Floodman Office shell. It no longer falls through to the Gauzy/ERP frontend or
its 502 startup page.

Nginx redirects are relative, preserving the Tailscale HTTPS origin and port
8443 across the internal HTTP proxy hop.

### Desktop is no longer widened mobile

The Office page sets `data-workspace="desktop"` or `data-workspace="mobile"`
before first paint. A final workspace stylesheet then overrides legacy
viewport media queries.

Desktop mode forces:

- a permanent 265-pixel sidebar;
- grid-based desktop shell;
- full tables;
- multi-column forms;
- desktop metrics and toolbars;
- no mobile top or bottom navigation.

Mobile mode forces:

- an off-canvas sidebar;
- touch controls;
- mobile top and bottom navigation;
- single-column field workflows;
- mobile RoomFlow sizing.

The explicit route wins even on a touchscreen Windows computer or when a phone
user deliberately opens desktop mode.

### Full ERP isolated behind `/full-erp`

The upstream ERP is still included, but it is no longer the private root.
Floodman ERP hash routes now request `/index.html` so the workspace-owned root
does not swallow them.

### Cache refresh

The PWA manifest, service worker, workspace selector, and cache release are all
bumped to 4.6.5. The PWA start URL is the adaptive workspace selector rather
than the mobile page.

### Preserved functionality

The release remains cumulative with:

- Android 0.3.0-alpha11 Mobile API compatibility;
- persistent RoomFlow company workspaces;
- original Supabase import;
- grouped estimates and invoices;
- payment, document, and signing workflows;
- calendar and employee assignments;
- dependency-free RoomFlow JPEG embedding in estimate PDFs;
- no Pillow/PIL requirement.
