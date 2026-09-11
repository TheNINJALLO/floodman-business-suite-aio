# Floodman Operations v4.7.3

Released 2026-09-10.

## Business Suite changes

- Reduces the permanent sidebar to Dashboard, Calls, Customers, RoomFlow, Estimates, and Billing.
- Keeps secondary applications available under an accessible `More tools` section.
- Simplifies the dashboard and the customer, estimate, invoice, and payment indexes.
- Shows a customer's properties prominently on the customer file while keeping dense history sections collapsed.
- Requires a customer selection before listing properties and never shows another customer's properties in that view.
- Replaces raw customer-ID editing with searchable customer selection and validates reassignment server-side.

## Compatibility and safety

- Retains Mobile API `0.3.0-alpha11`, Android `0.4.0-alpha01`, iOS `0.1.0-alpha03`, and the existing RoomFlow pin.
- Preserves all v4.7.2 artifacts as rollback evidence.
- Includes authenticated route isolation tests and real-browser desktop/mobile coverage.
