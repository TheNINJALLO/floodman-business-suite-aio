# Release checklist

## Source

- [ ] Untouched handoff baseline committed and tagged
- [ ] Release branch created
- [ ] Version files updated consistently
- [ ] RoomFlow commit reviewed and pinned
- [ ] Upstream image digests pinned
- [ ] Generated inventories refreshed
- [ ] No live data or secrets included

## Server

- [ ] Python, shell, JavaScript, JSON, XML, plist, and YAML checks pass
- [ ] Server smoke tests pass
- [ ] Fresh AIO build succeeds
- [ ] Fresh install succeeds
- [ ] Upgrade succeeds
- [ ] Restart and PostgreSQL recovery succeed
- [ ] Desktop, mobile, Full ERP, health, RoomFlow, signing, and customer routes pass
- [ ] Estimate and invoice PDFs pass
- [ ] Backup and restore pass

## Android

- [ ] Compile, unit tests, lint, APK, and AAB pass
- [ ] Debug and release signatures recorded
- [ ] Public HTTPS login works without Tailscale
- [ ] Estimate/invoice/payment lifecycle passes
- [ ] RoomFlow workspace, import, layout, and sync pass
- [ ] Device revocation passes

## iOS

- [ ] Simulator build passes
- [ ] Core feature parity verified
- [ ] Signing secrets configured outside Git
- [ ] Archive and TestFlight upload pass
- [ ] iPhone and iPad testing pass

## Security and operations

- [ ] Vulnerability scan and SBOM produced
- [ ] Secret scan passes
- [ ] Square Sandbox and webhook tests pass
- [ ] Public route abuse and rate-limit tests pass
- [ ] Logs and alerts configured
- [ ] Rollback package and instructions verified
- [ ] Checksums and release notes published
