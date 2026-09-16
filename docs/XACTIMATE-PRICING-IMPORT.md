# Licensed Xactimate pricing import

Floodman can keep user-authorized Xactimate line-item references and prices in the shared Services & Prices catalog. Imported items are searchable from Office and the integrated RoomFlow estimate builder. When an imported item is selected, its category/selector/activity code, price-list name, market, and effective date stay with the estimate line; the code and unit price also appear in the estimate PDF.

Xactimate is a Verisk product. This feature is not affiliated with, endorsed by, or a substitute for Xactimate. Only import pricing data your license and agreements allow you to use.

## Why the supplied PLX is not decoded directly

The supplied `MITC8X_AUG26 Traverse~SCity~O~SMI.PLX` is a valid ZIP transfer container with one member named `XACTDOC.ZIPXML`. That 2,109,208-byte member is opaque/protected rather than plain XML. Its outer SHA-256 is `8da48331cdf954cb1fe00a7f4156c5da77e52ba2a614ce7dfee2e44b3f1370e2`; its member SHA-256 is `508395378064f7fdcfc5befa40c579319d138914fcf92acf5eeb515552b2a613`.

Verisk documents Data Transfer as the Xactimate feature for transferring projects, price lists, contacts, macros, and other information between compatible Xactimate users. Verisk also documents that the Price List Editor is the supported place to view and edit non-read-only price-list items. No public PLX payload schema or supported third-party decoder was found in those official materials:

- <https://xactware.helpdocs.io/l/enUS/article/zqky4iijfs-glossary-a-h>
- <https://xactware.helpdocs.io/l/enUS/article/k2vg1vfajf-where-is-the-price-list-editor>
- <https://xactware.helpdocs.io/l/enUS/article/t0zhge9azq-glossary-i-q>

Floodman therefore recognizes and safely inspects PLX containers but does not guess at or circumvent the protected payload. A rejected PLX is not retained in Floodman runtime imports and is excluded from Git by `*.plx`/`*.PLX` rules.

## Operator workflow

1. In Xactimate Desktop, use its supported Data Transfer workflow to import the PLX into the compatible licensed profile.
2. Open the price list through Xactimate's Price List Editor and obtain the line-item values your license permits you to use outside Xactimate.
3. In Floodman, open **Services & Prices** and expand **Bring in licensed Xactimate pricing**.
4. Download `floodman-xactimate-pricing-template.csv`.
5. Put the authorized values into the template without changing its header row, then upload it.
6. Review the line-item count, price list, market, effective dates, code, description, unit, and unit price. Nothing is written during preview.
7. Select **Import reviewed prices**. No estimate, message, invoice, or customer record is created by the catalog import.

The original successful CSV preview is stored only under the private Office runtime data directory so the reviewed import has an audit source. Runtime `data/` and `imports/` are excluded from source control.

## Pricing worksheet columns

| Column | Required | Purpose |
|---|---:|---|
| `price_list` | Yes | Price-list edition/name used for audit, such as a market list and month. |
| `market_id` | Recommended | Stable market identity that remains unchanged when a monthly list is refreshed. |
| `market` | No | Human-readable city/region. |
| `effective_date` | Recommended | Published/effective date. Missing dates are visibly marked for review. |
| `category` | Yes | Xactimate category code. |
| `category_name` | No | Friendly estimate-section name. The category code is used when blank. |
| `selector` | Yes | Xactimate selector/item code. |
| `activity` | No | Activity code, such as remove, install, or detach/reset when applicable. |
| `description` | Yes | Licensed line-item description. |
| `unit` | Yes | Unit of measure. |
| `unit_price` | Yes | Customer unit price in dollars. |
| `material`, `labor`, `equipment` | No | Optional dollar components retained as source metadata; Floodman does not invent missing splits. |
| `taxable` | No | `yes` or `no`; defaults to `no`. |
| `active` | No | `yes` or `no`; defaults to `yes`. |

## Duplicate and refresh behavior

The stable source identity is:

`market_id + category + selector + activity`

The price-list month is intentionally not part of that identity. Uploading a newer monthly edition for the same market updates the existing item and its metadata instead of adding a duplicate. If `market_id` is blank, Floodman derives a market key from `price_list` and removes a trailing month/year pattern such as `_AUG26`; an explicit stable `market_id` is safer.

The import accepts up to 50,000 validated items and 25 MB per upload. It rejects missing required columns, malformed money/boolean values, duplicate identities within one worksheet, unsafe PLX paths, excessive expansion, and unsupported containers before any catalog write. The confirmed import is normalized in full and then written once under the Office store lock.

## Remaining external dependency

Direct extraction of all items from this exact PLX remains blocked until the owner supplies either:

- an authorized CSV populated from Xactimate; or
- a documented/licensed Verisk conversion or integration route that is permitted to expose the price-list rows.

This blocker does not affect manual Floodman services, bundled RoomFlow services, Supabase catalog synchronization, or later CSV refreshes.
