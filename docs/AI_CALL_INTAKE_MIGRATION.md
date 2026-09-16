# AI call intake migration 005

`server/database/migrations/005_ai_call_intakes.sql` is an additive, idempotent migration. The all-in-one bootstrap applies it as the `floodman` database owner after the fixed v3 baseline. Existing customer, RoomFlow, estimate, payment, consent, suppression, and audit records are not rewritten.

Before production rollout, back up PostgreSQL, stop the Orchestrator and its outbox worker, apply the migration in staging, and verify the call-intake smoke plus existing server smoke suite. Enabling the webhook is a separate approval: keep `AI_CALLING_ENABLED=false` until the public HTTPS route, signing keys, provider account, and `AI_CALLING_APPROVED=true` have been reviewed.

Rollback is manual and destructive. Stop the Orchestrator first, back up the database, disable AI calling, drain or discard only the call-intake outbox events, and then run `005_ai_call_intakes.rollback.sql`. The rollback removes only the two call-intake tables and its migration-ledger row; it does not delete Office customer, property, RoomFlow, estimate, task, or notification projections already created from accepted calls.
