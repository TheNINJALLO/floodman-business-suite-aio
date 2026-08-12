# Floodman v4.6.3 and Android 0.3.0-alpha11

## RoomFlow company and workspace repair

This release replaces the missing organization bridge between the bundled Android RoomFlow engine and Floodman Office.

- Imports each accessible RoomFlow Supabase organization as a persistent Floodman workspace.
- Repairs records already imported by v4.6.2 using their saved `roomflow_organization_id` values.
- Automatically selects the authoritative imported organization after an idempotent Supabase import.
- Returns the selected workspace, complete workspace list, jobs, catalog, customer/property links, and estimates through the encrypted Mobile API.
- Adds native API actions to create and select workspaces.
- Applies `state.currentOrganization`, session context, and capabilities before the RoomFlow dashboard restores jobs.
- Adds a company selector and working plus button to the RoomFlow top bar.
- Scopes RoomFlow jobs, imported catalog items, customers, properties, and estimates to the selected workspace.
- Preserves pending unsynchronized field work while changing workspaces.
- Keeps direct Supabase access and service-role keys out of the Android WebView.

## Server contract

- Floodman runtime: `4.6.3`
- Mobile API: `0.3.0-alpha11`
- Required capability: `roomflow.workspaces.v1`
- Android version: `0.3.0-alpha11`, version code `11`
- Time zone: `America/Detroit`

## Data safety

No database, customer, property, estimate, invoice, payment, signed document, RoomFlow job, Tailscale identity, or device enrollment is intentionally deleted. Repeating the original RoomFlow import uses stable source identifiers and updates matched records.

## Build boundary

The server runtime passed local Python compilation, API smoke tests, workspace recovery tests, import tests, PDF tests, shell syntax, JavaScript syntax, and checksum validation. Android source passed XML/YAML parsing, JavaScript parsing, Kotlin structural parsing, and static workspace-contract checks. The GitHub Actions Gradle run remains the authoritative APK/AAB compiler, unit-test, lint, and packaging gate.
