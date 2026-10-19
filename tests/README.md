# Test Suite Architecture & Mutation Testing Guide (`armonia-api`)

This directory contains the automated test suite for `armonia-api`, structured into isolated unit tests and end-to-end integration workflows.

---

## 1. Test Suite Taxonomy

```
tests/
├── conftest.py                       # Session fixtures, SQLite lifecycle, TestClient
├── test_auth_and_workflows.py        # Integration: OAuth allowlist, 48h queue, delayed pay
├── test_bookings.py                  # Integration: Booking creation, payment ack, buffers
├── test_health.py                    # Integration: Health check probe
├── test_services.py                  # Integration: Seeded service catalog endpoints
└── unit/                             # Fast, isolated unit tests (< 0.5s total)
    ├── models/                       # SQLModel schema validation and defaults
    │   ├── test_admin_model.py
    │   ├── test_booking_model.py
    │   ├── test_client_model.py
    │   ├── test_package_model.py
    │   ├── test_payment_model.py
    │   └── test_service_model.py
    ├── services/                     # Consumer-agnostic domain logic invariants
    │   ├── test_booking_service.py   # Buffer collision arithmetic & 48h follow-up rules
    │   ├── test_calendar.py          # Calendar prefix computation & unconfigured fallback
    │   └── test_timestamps.py        # UTC ISO serialization & timezone normalization
    └── test_database.py              # SQLite table reflection & schema parity
```

### Unit Tests (`tests/unit/`)
- **Execution Speed:** In-memory, zero network I/O, zero database concurrency contention.
- **Coverage:** Pure business invariants—buffer overlap math, 48-hour follow-up state machines, folio generation, timestamp parsing, and model field validations.

### Integration Tests (`tests/test_*.py`)
- **Execution:** Exercises FastAPI routes against an isolated local SQLite file (`test_armonia.db`).
- **External I/O:** Google Calendar and OAuth network side-effects are mocked via `pytest-mock` (`mocker`) and monkeypatched configuration.

---

## 2. Running Verification Gates

Ensure you are inside the Nix `devShell` (`direnv` or `nix develop`).

```bash
# 1. Format check
uv run ruff format --check .

# 2. Lint check
uv run ruff check .

# 3. Static type analysis
uv run pyright

# 4. Pytest test suite
uv run pytest
```

---

## 3. Mutation Testing with `mutmut`

Mutation testing systematically inserts synthetic syntactic faults (e.g., swapping `<` for `<=`, flipping boolean conditions, changing buffer addition `+` to `-`, or altering numeric constants) to verify that unit tests fail when code semantics change.

### Configuration (`pyproject.toml`)
Mutmut is configured under `[tool.mutmut]`:
```toml
[tool.mutmut]
source_paths = ["app/services/"]
also_copy = ["app"]
pytest_add_cli_args_test_selection = ["tests/unit/services/"]
```
- **`source_paths`**: Targets extracted domain services (`app/services/`).
- **`also_copy = ["app"]`**: Ensures `app.core`, `app.models`, and schema modules are copied into the mutant runtime workspace to prevent `ModuleNotFoundError`.
- **`pytest_add_cli_args_test_selection`**: Executes lightning-fast unit tests (`tests/unit/services/`) for each mutant, preventing SQLite file lock contention (`SQLITE_BUSY`) during parallel worker execution.

### Mutation Execution Workflow
```bash
# Clean previous mutant artifacts and run mutation audit
rm -rf mutants && uv run mutmut run

# Check surviving mutants (should output nothing when 100% killed)
uv run mutmut results

# Inspect a specific mutant diff
uv run mutmut show <mutant_id>

# Export CI/CD machine-readable statistics
uv run mutmut export-cicd-stats
```

### Hardened Domain Invariants
The unit tests in `tests/unit/services/test_booking_service.py` specifically enforce:
1. **Buffer Collision Boundaries ($<$ vs $\le$):**
   - Adjacent slots (`new_start == exist_blocked_end` or `new_blocked_end == exist_start`) return `False` (no collision). Mutants replacing `<` with `<=` are caught and killed.
   - Buffer encroachment: If the session ended but its post-session buffer overlaps another reservation, `check_slot_collision` returns `True`. Mutants altering `duration + buffer` to `duration - buffer` are killed.
2. **48-Hour Follow-Up Cutoff:**
   - Exact boundary: A reservation scheduled at exactly `48.0` hours from `now` with `AWAITING_ACKNOWLEDGMENT` evaluates to `True` (`needs_followup`). Mutants replacing `<=` with `<` fail this assertion and are killed.
   - Non-eligible appointments (already `ACKNOWLEDGED`, `CANCELLED`, or beyond 48 hours) evaluate to `False`.
3. **Delayed Payment Exceptions (`DELAYED_ALLOWED`):**
   - Active or completed sessions with delayed payment authorization remain flagged for follow-up regardless of elapsed time (`hours_until`).
