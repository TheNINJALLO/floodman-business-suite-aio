# Known issues and validation boundary

## Live issues at the end of the conversation

### Full ERP server-down page

The latest reported live issue was that the Full ERP link from the desktop workspace opened the upstream server-down/recovery page. v4.6.7 was produced with:

- authentication-aware signed-in/signed-out routing;
- HTTP `200` plus JSON `false` treated as signed out;
- ERP API startup retries;
- an injected browser boot guard;
- `X-Forwarded-Proto` HTTPS-origin preservation for the external proxy;
- a separate status page.

Local Nginx and application smoke tests passed, but a successful live v4.6.7 result was not posted in this chat. Treat this as the first staging acceptance test.

### Android build/install identity

Several Android alphas were built during the conversation. The exact installed APK on any current handset may not match the locally verified 0.4.0-alpha01/build-13 source/artifact. Use app version/build metadata, the recorded SHA-256, and server compatibility response rather than appearance alone.

### Apple parity

Apple alpha03 is a development shell and RoomFlow bridge with passing Windows source readiness, not a compiled or fully accepted counterpart to Android. Xcode simulator compilation, estimate/invoice/payment/calendar editing parity, and full device testing remain.

## Architectural debt

- The AIO container is large and operationally coupled.
- Office custom state is JSON rather than relational.
- Supervisor startup logs can be noisy and obscure the first real exception.
- Upstream image tags in the complete AIO Dockerfile are not yet immutable digests.
- PWA cache/version behavior has caused stale assets after upgrades.
- Correct security depends on the external HTTPS proxy applying the documented per-host and per-path access policy.
- Some provider integrations have local-mock modes that must never be mistaken for production success.
- APNs/FCM production delivery is not configured in source alone.
- RoomFlow's original public Supabase project defaults remain in source and should move to environment variables.

## What local validation proves

The included reports and scripts can prove:

- source files parse;
- shell/JS syntax is valid;
- manifests/checksums match;
- route handlers and expected strings exist;
- smoke tests pass in a controlled local fixture;
- Nginx templates can render and validate where Nginx is available.

They do not prove:

- live Pterodactyl permissions or resource limits;
- real DNS, certificates, proxy headers, WebSocket forwarding, or access-policy behavior;
- upstream Gauzy/Documenso image compatibility at a later date;
- production Square/Twilio/OpenAI behavior;
- physical mobile-device behavior;
- data migration correctness against the entire live dataset.

## Required first staging test

1. Build a derivative image from this commit.
2. Restore sanitized copies of PostgreSQL and Office/files data.
3. Start twice to prove restart safety.
4. Test all private and public health routes.
5. Test Full ERP signed out and signed in.
6. Search a customer with multiple properties.
7. Create a multi-header estimate with category plan.
8. Attach a real RoomFlow layout and generate PDF.
9. Send/sign a test authorization.
10. Collect a Square sandbox payment and manual payment.
11. Convert to invoice and generate paid receipt.
12. Install the locally verified Android 0.4.0-alpha01/build-13 debug APK and repeat the lifecycle.
13. Build Apple simulator and record parity gaps.
14. Restore the staging backup again to prove recovery.
