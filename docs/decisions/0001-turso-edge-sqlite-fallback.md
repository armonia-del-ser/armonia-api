# ADR 0001: Turso Edge Persistence with Local SQLite Fallback

## Status
Accepted

## Context
Armonía del Ser operates on a low-margin business model where recurring software subscription fees or persistent virtual private server (VPS) costs would outweigh the operational benefits. We require a relational database that:
1. Incurs **$0/month** in operational overhead for the anticipated volume (< 500 bookings/month).
2. Provides relational schema enforcement, constraints, and atomic operations (unlike Google Sheets) for bookings, payment acknowledgments, administrator allowlists, and audit logs.
3. Executes seamlessly in local development and automated CI/CD testing without requiring remote cloud network calls or credentials.

## Decision
We adopt **Turso (libSQL)** as the primary production database, coupled with `libsql-client` in Python:
- In production, `DATABASE_URL` connects to Turso's edge network via `libsql://` or `https://` using token-based authentication.
- In local development and automated testing (`pytest`), `DATABASE_URL` connects to standard file-based SQLite (`file:local.db` or temporary test files) without requiring any cloud connection.

## Consequences
### Positive
- **Zero Cost**: Turso's free tier provides 9 GB storage and 1 billion row reads/month, far exceeding the operational needs of the practice.
- **Developer Experience**: Automated tests run locally in under 0.15 seconds with zero network dependency.
- **Relational Integrity**: Foreign keys and enum constraints prevent data corruption.

### Negative / Trade-offs
- Turso does not provide a native visual spreadsheet UI for non-technical users. Jasmin cannot open the raw database table directly; she and her assistant interact with the data exclusively through `armonia-dashboard` and Google Calendar.
