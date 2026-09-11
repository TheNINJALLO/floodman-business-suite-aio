# Customer SMS deployment - September 11, 2026

## Live release

The shared Ai Calling Pterodactyl server is running:

`ghcr.io/theninjallo/floodman-operations:unified-portal-837d13b89b01c336ee4c3cc97ef4cce1dffb6291@sha256:fbf8194e2935f1239b6743d1fd9e1d86cda44fc3c89f3dd5d5d29635ce426fbc`

The previous image is retained for rollback:

`ghcr.io/theninjallo/floodman-operations:unified-portal-ddd53888d21d28c5b889da36c41d21b88931ebec@sha256:7a5cd29d507f8f1def0dfdf75506ddf96b4ba1bd44c3e58fbc4abb2106461e76`

A private configuration and Office state snapshot was taken at 17:39:54 UTC before restarting, with no active calls. Runtime environment contents were unchanged. The existing locked full-panel backup was retained. No database migration or hosted-photo-portal modification was performed.

## Verification boundaries

- Customer consent core, real Chromium/WebKit forms, backend validation/delivery guards, complete responsive web UI, portal connection/projection/tools, call intake, and unified-login tests passed using isolated fictional data.
- Repository verification passed without warnings. The immutable runtime download matches the locally tested ZIP (SHA-256 `d59b0e91ade47e22a0906ed31e19766b7d8498a9ed9f0401923ab8c9159db637`). The corrected shared-image build and source verification passed.
- Live Voice, Suite, and API health returned 200. Owner login and Office messages passed. Existing records survived the restart. No consent events or enrollments were created by the rollout, and no SMS was sent.
- Public privacy, terms, and program pages returned 200 without authentication; exact Hub aliases redirected to the matching public policies. The public review preview was unchecked and non-submitting on mobile and desktop. Both Google and Cloudflare public DNS resolved the service domains to the same public address.
- Live photo portal checks passed for desktop/mobile, 50 listed jobs, 20 images in the selected job, private storage protection, unsigned API rejection, and absence of browser script errors.
- No existing enabled customer document links were available for a read-only production form check. Actual customer enrollment/withdrawal was tested only in the isolated browser fixture, not against customer records.

## Twilio submission - not carrier approval

Advanced Opt-Out was enabled on the existing messaging service after saving Floodman-branded opt-out, reactivation, and HELP replies. The campaign's replies match that configuration. Initial enrollment remains an explicit customer-portal or staff-profile choice, not an unsolicited keyword or existing contact record. Twilio documents that disabling Advanced Opt-Out after activation requires its support team.

The existing rejected campaign was corrected and submitted once at 17:43:44 UTC. The automated pre-check required additional review rather than declaring the information verified. The submission page then confirmed receipt and said the registration was being reviewed.

Important: after finishing and refreshing, the campaign overview still showed its prior Rejected status, original staff-only description, and August 15 update date. Do not interpret the submission confirmation as a verified campaign-status transition or approval, and do not repeatedly resubmit. Recheck the campaign and review email before enabling delivery; escalate the discrepancy to Twilio if it persists.

The Voice readiness endpoint still reported SMS configuration as false. Carrier approval and delivery-credential configuration remain separate requirements before sending messages. This release establishes consent capture, public disclosures, and enforcement; it does not claim working production SMS delivery.
