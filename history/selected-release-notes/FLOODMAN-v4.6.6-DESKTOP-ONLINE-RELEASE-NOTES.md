# Floodman v4.6.6 Desktop Online Fix

## Summary

Floodman v4.6.5 could display **Floodman is offline** when opening the desktop workspace even though Tailscale Serve, the Floodman Hub, and Floodman Office were reachable.

The browser's generic network flag was being treated as the source of truth, and the service worker's short navigation deadline could misclassify a slow desktop response as a network outage.

## Changes

### Same-origin connection detection

The PWA now checks:

```text
/office-health/live
```

rather than relying on `navigator.onLine`. The UI requires two consecutive failed health probes before it changes to the offline state.

### Safer navigation fallback

The service worker now:

- Allows up to 30 seconds for dynamic Floodman Office navigation.
- Probes the Floodman Hub when a navigation request fails.
- Shows a temporary **Floodman Office is starting** page when the Hub is alive but Office is still warming.
- Shows the offline page only when Floodman itself cannot be reached.

### Faster desktop rendering

Desktop and mobile dashboards now obtain optional provider state through a short bounded request. Durable local Floodman Office records render even when an optional provider is unavailable or warming.

### Service-worker recovery

The workspace selector registers and updates the v4.6.6 service worker before redirecting to the chosen workspace. This helps replace a cached v4.6.5 worker that would otherwise continue using the old timeout.

### Private health route

Nginx now exposes:

```text
/office-health/live
```

as a same-origin private health check for the PWA.

## Compatibility

- Floodman server: v4.6.6
- Android: 0.3.0-alpha11 remains compatible
- Existing Tailscale Serve mapping remains unchanged
- No database migration or destructive reset is performed
