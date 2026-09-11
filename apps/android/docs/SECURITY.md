# Security model

- Cleartext HTTP is disabled.
- The app trusts normal public certificate authorities and validates HTTPS.
- Access tokens are short-lived.
- Refresh tokens rotate after every use.
- Refresh requests include per-device proof.
- The server can revoke a device and its refresh-token chain.
- Session material is encrypted using Android Keystore.
- Device unlock uses Android BiometricPrompt with device-credential fallback.
- Floodman permissions and status rules are applied to every protected operation.
- Login attempts are rate-limited and security events are recorded.
- Raw card numbers, CVV values, magnetic-stripe data, chip data, and PIN data are never stored in Floodman.
- Square card entry creates a one-time payment token; the server processes the token.
- Customer signing and payment links are token-protected public pages; the staff application API uses staff authentication and device enrollment.

## Alpha limitations

- The release has not completed an external penetration test.
- Certificate pinning remains disabled so certificates can rotate through the operator-managed `api.oninetwork.com` HTTPS proxy; normal public certificate-authority validation remains required.
- A broad offline customer cache is not enabled.
- Native push delivery still requires FCM credentials.
- The bundled RoomFlow engine runs in a hardened local WebView origin; it still requires device-level field testing across the supported camera and AR hardware range.
