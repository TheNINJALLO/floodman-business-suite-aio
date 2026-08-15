# CRM and RoomFlow settings usability — v4.6.9

Date: 2026-08-15
Scope: Floodman Office CRM, integrated RoomFlow, RoomFlow source-data import, Android and iOS settings entry points
Release identity: unchanged (`server 4.6.9`, Mobile API `0.3.0-alpha11`, Android `alpha12`, iOS `alpha03`)

## Intended first-day experience

An owner should be able to begin without learning server terminology:

1. Open **Settings & Setup**.
2. Confirm the business name and contact details.
3. Add employees in the main ERP and choose the narrowest Floodman access level.
4. Review reusable **Services & Prices**.
5. Open RoomFlow, choose the customer and property, sketch and price the job, then save the draft.

Provider URLs, modes, API addresses, server templates, and old-data migration controls are collapsed or clearly marked owner/installer-only. They remain available; they are not mixed into the everyday path.

## Complete staff-visible settings inventory

| Area | Entry point | Normal user decision | Usability treatment and safe default |
|---|---|---|---|
| Settings home | `/office/settings` | Which setup area needs attention | One ordered dashboard: four everyday areas followed by owner-only setup; readable readiness summaries; no secret values or live writes. |
| Business identity | `/setup#company-profile` | Display/legal name, office/billing contact, address | Required and optional fields are explicit; browser autocomplete and formats are supplied; state, ZIP, email, name, and time zone are validated on the server. |
| Business time | `/setup#company-profile` | Scheduling time zone | A single plain choice, **Eastern Time (Detroit)**; stored timestamps remain UTC. Arbitrary time-zone strings are rejected. |
| Go-live review | `/setup` | Connections, import choice, document and communication review | Plain ordered steps; the page states that review does not activate production services; starting fresh is an explicit valid import choice. |
| Connected-service health | `/setup`, `/office/linking` | Run a safe health check | One safe action explains what it does not do; individual technical results are collapsible. |
| Provider connection plan | `/office/linking` | Installer-reviewed modes and addresses | Marked installer-only and collapsed; allowed modes are validated; owner permission is enforced on both GET and POST; credentials are never accepted. |
| Card payments | `/office/payment-settings` | Understand test, sandbox, or production readiness | Plain status and four-step onboarding; full card data is explicitly prohibited; file-path/server values appear only under server-owner instructions. |
| Services and prices | `/office/catalog` | Search, filter, add, tax, unit, standard price, RoomFlow refresh | “Line-item catalog” is renamed; units are a select; dollar input and customer-facing descriptions are explained; source names are human-readable. |
| RoomFlow/Supabase catalog | `/office/catalog`, RoomFlow customer/job panel | Refresh current shared services | Current RoomFlow/Supabase values update by stable source ID; the `catalog_sync=1` link now deliberately opens and runs the refresh path. |
| Team and access | `/office/members` | Add staff and choose access | ERP identity is the recommended path; six non-owner roles have job-based explanations; local recovery invitations are collapsed. A second owner cannot be invited by UI or direct POST. |
| Existing business data | `/office/imports` | Select CSV/ZIP, preview, confirm | Three-step explanation; original file is not modified; no records are written before preview; matching/stable-ID behavior is explained under details. |
| Connected applications | `/office/apps` | Open the right application | Everyday applications are first and named by job; developer/test tools are collapsed under an installer section. |
| RoomFlow launch | `/office/roomflow` | Understand the field workflow | Four visible steps and a clear statement that the ERP login is already the RoomFlow login. |
| RoomFlow company | RoomFlow customer/job panel | Use or change the active company | The active company is automatic; create/switch controls are collapsed; new companies use Eastern Time (Detroit); no separate account prompt remains. |
| RoomFlow customer/property | RoomFlow customer/job panel | Link the job to the correct records | Two mandatory, numbered search steps; searches use name, contact details, tags, and address; an empty result links to the correct add-record page. |
| RoomFlow notes/tags | RoomFlow customer/job panel | Optional customer context | Collapsed as optional; categories use plain labels; feedback remains in the panel. |
| RoomFlow estimate scope | RoomFlow customer/job panel | Sections, services, quantity, unit price | Numbered as the third required step; shared catalog search and custom services remain available. |
| RoomFlow save | RoomFlow customer/job panel | Save or update the draft | Numbered fourth step; copy states that re-saving updates the same draft; stable estimate identity is retained. |
| RoomFlow quick start | RoomFlow customer/job panel | Show/hide in-context training | Non-modal progress card; always has a dismiss button; Help restores it; dismissal persists locally. |
| RoomFlow feedback | RoomFlow customer/job panel | Read and dismiss results/errors | Live region remains in the panel and every displayed status now has a dismiss button. Panel, backdrop, Escape, and close-button behavior remain intact. |
| Old RoomFlow cloud import | `/office/roomflow/import`, Android, iOS | Import original Supabase companies/jobs/data | Owner-only web form and mobile sheets explain one-time password use, immediate clearing, stable-ID updates, and real-layout preservation. Passwords are not stored. |
| Android app settings | More → App settings | Appearance, calendar, connection, sign-out | Everyday connection summary first; raw Mobile API editing is collapsed and warns that changing it signs the device out. |
| Android RoomFlow settings | RoomFlow toolbar | Company, customer/property, old-data import, save | Four-step explanation added; company time is a fixed choice; “Cloud” and “Link” labels are replaced with plain actions; all dialogs retain Cancel, backdrop, and Escape close paths. |
| iOS app settings | More → App settings | Connection details, appearance, sign-out | Plain secure-connection and business-time summary; raw endpoint is read-only inside installer disclosure. |
| iOS RoomFlow settings | Floodman RoomFlow | Company selection, another company, old-data import | Four-step section added; uncommon company/import controls use disclosure; new company time is fixed; password is cleared on cancel, completion, and dismissal. |

## Upstream ERP boundary

The genuine Floodman ERP retains its native employees, organization, accounting, inventory, reporting, role, and permission settings. Floodman does not silently rewrite those upstream records or expose them through a new public administration endpoint. The low-training path links owners to the exact ERP employee screens, while Floodman-specific module access remains on **Team & Access**.

## Safety behavior preserved

- The staff PWA, Office, RoomFlow, Settings, and import form remain authenticated/private surfaces.
- No page displays access tokens, authorization headers, payment credentials, or the old RoomFlow password.
- Card numbers, expiration dates, and security codes remain processor-controlled.
- Old RoomFlow imports update stable source IDs and do not invent measured layouts.
- A settings page view does not send customer messages, charge cards, enable production providers, or migrate a database.
- Release versions and the pinned RoomFlow commit `1f97817a52b916875e50cc6380c0d284072b8ce8` are unchanged.

## Verification target

`server/tests/web_ui_smoke.py` is the executable acceptance check for these settings. It covers authenticated rendering, invalid company time rejection, owner-role escalation rejection, owner-only old RoomFlow import plumbing without password persistence, desktop/mobile overflow, progressive disclosure, quick-start dismissal/restoration, status dismissal contracts, and all existing overlay close paths. The dedicated RoomFlow Supabase regression remains the authority for authenticated source pulls, stable-ID repeat updates, company linkage, and layout rules.
