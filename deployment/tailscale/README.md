# Tailscale layout

The current private staff topology is:

```text
HTTPS :8443 -> Floodman Hub / PWA / Full ERP gateway on 127.0.0.1:9000
HTTPS :8444 -> public signing service on 127.0.0.1:9001
HTTPS :8445 -> Floodman API on 127.0.0.1:9004
HTTPS :8446 -> Mailpit on 127.0.0.1:9002
HTTPS :8447 -> engineering tools on 127.0.0.1:9003
```

The Android application does not require Tailscale on the handset. It connects to the public encrypted `/mobile-api/` path through the server-side gateway. The staff PWA and Full ERP stay private through Tailscale Serve.

Never commit `tailscale-auth-key.txt`. Back up the Tailscale state directory if preserving the machine identity matters during host migration.
