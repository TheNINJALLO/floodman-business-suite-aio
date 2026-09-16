# Feature inventory

## Customers and properties

- Searchable customer directory
- Customer file with company, contact, mailing, phone, and email information
- Multiple service properties
- Notes, pinned notes, tags, and status
- Customer documents and signed documents
- Estimate, invoice, payment, and job history
- CSV and ZIP import
- Blank import template included in `reference/`
- RoomFlow customer/property mapping

## Estimates

- Search existing estimates without saving
- Create new customer and property inside the estimate flow
- Multiple editable scope headers
- Header descriptions and subtotals
- Reusable catalog search
- Custom line items saved to the catalog
- Quantity, unit, price, tax, optional item, and order controls
- Project category and recommended plan
- Duration, assumptions, exclusions, protections, and optional upgrades
- Percentage or fixed deposit
- Draft, send, resend, authorize, accept, activate deposit, pay, convert, revise, and eligible-delete actions
- Customer portal and PDF
- Actual RoomFlow layout embedding

## Invoices

- Direct invoice creation or estimate conversion
- Grouped editable headers and lines
- Contract total, changes, prior payments, and current balance
- Send/resend, payment, void, and eligible-delete actions
- Customer portal and PDF
- Payment and completion history
- Linked signed documents and project notes

## Payments

- Customer online checkout
- Card by phone using Square tokenization
- Processor-managed saved payment method authorization
- Cash, check, ACH/bank transfer, external card, and other manual methods
- Payment attempts and audit records
- Deduplicated in-app/mobile and email alerts for payment administrators
- No intended raw card or CVV storage

## Documents and signing

- Documenso-backed signing
- Work authorization
- Change order
- Completion of service
- Warranty and project document linkage
- Signed documents attached to customer and project files
- Public tokenized signing routes

## RoomFlow

- 2D room and custom-shape sketching
- Levels, walls, openings, doors, windows, pumps, drainage, cracks, reinforcement, utilities, and annotations
- Measurements and material quantities
- 3D and supported camera/AR flows
- Internal costing and customer pricing
- Catalog items and grouped estimate scope
- Full job snapshot synchronization
- Actual layout capture
- Original Supabase migration
- Multiple company/workspace support

## Scheduling and workforce

- Jobs and inspections
- Estimate appointments, follow-ups, deliveries, meetings, and training
- Multiple assigned employees
- Lead employee
- Conflict detection and controlled override
- Status, location, internal notes, and customer notes
- Tasks, announcements, notifications, and time clock
- Read-only external calendar subscriptions

## Communications and intelligence

- Property-scoped two-way customer conversations inside secure estimate/invoice links
- Staff conversation inbox, replies, unread state, and customer email notifications
- Per-user alert center with mobile notification-feed compatibility and email delivery status
- Mailpit test email
- SMTP provider configuration
- Twilio configuration and local mock support
- Deterministic or configured AI message drafting
- Receivables scheduler and outreach workflow
- Competitor targets, scans, snapshots, reports, and scheduler

## Clients

### PWA

- External HTTPS proxy integration with staff-only access policy
- Separate desktop and mobile layouts
- Adaptive launcher and explicit mode switching
- Dark/light/system preference data
- Installable PWA and service worker

### Android

- Native Compose shell
- Encrypted API, device enrollment, refresh rotation, secure storage, and biometric/PIN unlock
- Customer, property, estimate, invoice, payment, document, schedule, task, notification, time, and RoomFlow modules
- Bundled local RoomFlow engine
- Dark/light/system modes

### iOS

- Native SwiftUI shell
- Keychain storage and Mobile API client
- iPhone and iPad target
- Core operations module shells
- Bundled RoomFlow engine
- Dark/light/system modes
- Simulator and guarded TestFlight workflows
