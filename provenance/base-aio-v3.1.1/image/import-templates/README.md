# Floodman historical migration folder

This folder contains the normalized import contract used by Floodman Office.

## Required files

- `contacts.csv`
- `properties.csv`
- `estimates.csv`
- `estimate_lines.csv`
- `invoices.csv`
- `payments.csv`

## Optional supported files

- `documents.csv`
- `notes.csv`
- referenced PDFs, images, Word documents, text files, and other permitted attachments

Download the same blank templates from the running Import Center:

```text
http://localhost:9000/office/imports/templates.zip
```

Download a complete working sample from:

```text
http://localhost:9000/office/imports/sample.zip
```

## Mapping a Townsquare export

Keep the untouched Townsquare exports in a separate read-only folder. Create a second working folder and map source columns into these templates.

Preserve the original source identifier in every `legacy_*_id` field. Do not invent a new identifier when the source has one. Those values provide idempotency and let Floodman trace a migrated record back to the original system.

Common mappings include:

| Source concept | Floodman field |
|---|---|
| Customer/client ID | `legacy_contact_id` |
| Service location/property ID | `legacy_property_id` |
| Estimate ID | `legacy_estimate_id` |
| Estimate item ID | `legacy_line_id` |
| Invoice ID | `legacy_invoice_id` |
| Payment ID | `legacy_payment_id` |
| Document/attachment ID | `legacy_document_id` |
| Note ID | `legacy_note_id` |

Money is always integer cents:

```text
$1,250.00 = 125000
$75.43    = 7543
```

Estimate lines must reconcile exactly to the estimate total. Payments are grouped by invoice to calculate historical paid, outstanding, and overpaid amounts.

## Local validation

To validate an extracted working folder before creating the ZIP:

```powershell
cd C:\FloodmanLab\migration
python validate_exports.py C:\Path\To\NormalizedExport
```

The browser Import Center performs deeper ZIP and attachment checks and remains the final local rehearsal step.

## Safe commit behavior

A local commit creates historical archive records only. It does not create a Square invoice, payment link, signature request, customer email, customer SMS, or receivables schedule. Outstanding imported balances remain review-only.
