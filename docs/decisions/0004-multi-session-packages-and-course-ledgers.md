# ADR 0004: Multi-Session Packages and Digital Course Attendance Ledgers

## Status
Accepted

## Context
Operational interviews revealed that clients frequently purchase therapy as multi-session packages (e.g., 5 or 10 sessions). Currently, tracking remaining sessions (e.g. "sesión 8 de 10") is discussed informally at the end of consultations, relying on memory and chat history.
Similarly, for recurring low-cost workshops (*Curso de Abundancia*, $50 MXN/session), Jasmin records attendees and payments on a physical sheet of paper and photographs it to share with her assistant.

## Decision
1. **Package Domain Model**: We introduce a `packages` entity tracking `client_id`, `service_id`, `total_sessions`, and `completed_sessions`. Booking individual sessions under a package sets `payment_arrangement = 'PACKAGE_REDEEMED'` and `payment_status = 'NOT_APPLICABLE'`, decrementing available package credits without entering the unpaid follow-up queue.
2. **Digital Workshop Attendance Ledger**: We support workshop roster tracking allowing Jasmin or her assistant to record workshop participants and payment status in `armonia-dashboard`.

## Consequences
### Positive
- Completely replaces physical paper sheets and phone photographs.
- Eliminates verbal confusion over remaining package sessions.
- Enables collaborative coordination between Jasmin and her assistant.

### Negative / Trade-offs
- Adds `packages` entity management to the data model.
