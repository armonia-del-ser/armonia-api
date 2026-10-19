# ADR 0006: Mutation Testing & Boundary Hardening for Core Business Logic

## Status
Accepted (2026-10-19)

## Context
Standard line and branch coverage metrics only verify that code was executed during a test run; they do not verify that the test assertions are strict enough to detect subtle defects.

In `armonia-api`, two domain invariants carry direct business risks if mutated:
1. **Mandatory Post-Session Buffer Overlap Math**:
   - An off-by-one operator error ($<$ vs $\le$) or sign change (`duration - buffer` instead of `duration + buffer`) could either allow double-booking a slot during Jasmin's decompression window or falsely reject a legitimate back-to-back appointment.
2. **48-Hour Payment Follow-Up Cutoff**:
   - A boundary condition mutation ($<$ vs $\le$) on `hours_until <= threshold` could exclude consultantes scheduled at the exact threshold boundary, preventing Jasmin's assistant from sending timely WhatsApp follow-ups and allowing ghosted reservations to block inventory.

## Decision
1. **Decouple Pure Domain Logic into `app/services/`**:
   - Business arithmetic (buffer collision detection, 48-hour follow-up evaluation, and folio generation) is decoupled from FastAPI route handlers into `app/services/bookings.py` and `app/services/timestamps.py`.
2. **Adopt `mutmut` as Quality Audit Gate**:
   - Mutation testing is configured in `pyproject.toml` (`[tool.mutmut]`), targeting `app/services/`.
   - The test selection for mutation workers is restricted to isolated unit tests (`pytest_add_cli_args_test_selection = ["tests/unit/services/"]`) to avoid SQLite database lock contention (`SQLITE_BUSY`) during parallel test execution.
   - All surviving mutants on boundary arithmetic ($<$, $\le$, `+`, `-`, and threshold fallbacks) must be eliminated prior to merging PRs altering `app/services/`.

## Consequences
### Positive
- **Guaranteed Boundary Invariants**: 100% kill rate achieved on domain functions (`check_slot_collision`, `evaluate_payment_followup`, `calculate_hours_until`, `parse_iso_datetime`, `compute_calendar_prefix`).
- **Zero Tautological Tests**: Unit tests assert exact boundary values (`48.0h`, `48.01h`, adjacent buffer ends) rather than loose status checks.
- **Fast Execution**: Pure unit tests execute in under 0.1 seconds, enabling `mutmut` to evaluate 250+ mutants in seconds.

### Negative / Trade-offs
- Developers modifying domain logic in `app/services/` must run `mutmut` alongside standard `pytest` to prevent mutation leaks.
