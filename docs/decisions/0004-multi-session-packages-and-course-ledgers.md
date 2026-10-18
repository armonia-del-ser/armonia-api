# ADR 0004: Multi-Session Packages and Digital Course Attendance Ledgers

## Status
Accepted

## Context
Operational interviews revealed that clients frequently purchase therapy as multi-session packages (e.g., 5 or 10 sessions paid upfront). Currently, tracking remaining sessions (e.g. "sesión 8 de 10") is discussed informally at the end of consultations, relying on memory and chat history.
Similarly, for recurring low-cost workshops (*Curso de Abundancia*, $50 MXN/session), Jazmín records attendees and payments on a physical sheet of paper and photographs it to share with her assistant.

## Decision
1. **Package Domain Model**: We introduce a `packages` entity tracking `client_id`, `service_id`, `total_sessions`, and `completed_sessions`. Booking individual sessions decrements available package credits without triggering payment requests.
2. **Digital Workshop Attendance Ledger**: We introduce an `occurrences` and `attendance` model allowing Jazmín or her assistant to record workshop participants and toggle payment status (`attended: true/false`, `payment_method: CASH | SPEI`) with a single mobile tap in `armonia-dashboard`.

## Consequences
### Positive
- Completely replaces physical paper sheets and phone photographs.
- Eliminates awkward verbal disputes over remaining package sessions.
- Enables collaborative coordination between Jazmín and her assistant.

### Negative / Trade-offs
- Adds additional entities (`packages`, `attendance`) to the data model and migration pipeline.
