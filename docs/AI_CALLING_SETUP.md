# AI calling integration setup

Floodman accepts a provider-neutral, signed event stream at:

`POST {PUBLIC_BASE_URL}/webhooks/ai-calling/{AI_CALLING_PROVIDER}`

The checked-in adapter is `deterministic`. It is the local/staging contract adapter and performs no model call. A production voice vendor needs a separate reviewed adapter that converts its webhook into the same strict event model; do not move identity matching, consent, suppression, billing, or pricing decisions into that adapter or a prompt.

## Required configuration

- `AI_CALLING_ENABLED=false` until the HTTPS route and provider are ready.
- `AI_CALLING_APPROVED=false` until an owner approves production intake.
- `AI_CALLING_PROVIDER=deterministic` for the checked-in adapter.
- `AI_CALLING_WEBHOOK_URL=https://api.example.com/webhooks/ai-calling/deterministic`; it must exactly match `PUBLIC_BASE_URL` plus the provider route.
- `AI_CALLING_HMAC_KEYS=call-v1:<base64 secret of at least 32 bytes>`. Keep this distinct from public API credentials. The all-in-one runtime can fall back to its existing AI HMAC key during migration, but a production provider should receive a separately rotated call key.

Each request must carry `X-Floodman-Key-Id`, `X-Floodman-Timestamp`, and `X-Floodman-Signature`. The signature is Base64 HMAC-SHA256 over `{unix_timestamp}.{exact_request_body}`. Floodman rejects expired timestamps, unknown keys, invalid signatures, oversized bodies, conflicting replays, and stale event sequences.

## Event contract

The supported event types are `call-started`, `caller-identified`, `transcript-updated`, `call-ended`, and `call-failed`. Every event includes a provider call ID, provider event ID, nondecreasing sequence, organization ID, Floodman workspace ID, and timezone-aware occurrence time that Floodman normalizes to UTC. Structured caller, property, service, urgency, appointment, consent, and summary fields are optional as the call progresses. A reviewed provider adapter sets `caller.phone_verified=true` only for provider-authenticated caller ID; unsigned or unverified numbers never link an existing customer automatically.

Do not send a raw transcript in this contract. Send `transcript_available`, an approved `transcript_reference`, and a concise structured summary. Floodman stores the event payload hash and redacted audit metadata, not the provider payload or credentials.

## Processing and review behavior

The Orchestrator commits the event and Office projection request to PostgreSQL/outbox in one transaction. Office then atomically writes the local call intake and any safe exact-match customer, property draft, replay-safe customer-file call note, RoomFlow job, unpublished estimate, follow-up task, and eligible staff notifications before the worker attempts a remote Floodman ERP/Gauzy contact/project sync. Opening RoomFlow from the call card passes the stable RoomFlow job ID and loads that exact customer/property context.

Multiple exact customer matches, invalid identity data, out-of-order initial events, call failures, missing property details, and exhausted provider retries remain visible as `REVIEW_REQUIRED`. They are never silently dropped or guessed. The prepared estimate has no measurements, line items, quantities, or prices and cannot be sent, accepted, converted, or charged until staff verifies and prices it.

Native OS push delivery still requires the owning Apple/Google push-provider credentials and approval. The slice delivers immediately through the authenticated web screen-pop, durable Office queue, native mobile notification feed, staff email, and best-effort SMS for eligible staff accounts with a configured E.164 mobile number. Registered native push tokens are retained and marked for the provider boundary without claiming a delivery that Floodman cannot prove.
