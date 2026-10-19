# Repository Technical Blueprint: `armonia-api`

This file defines the local toolchain, code implementation boundaries, testing invariants, and structural index for `armonia-api`. For cross-repo Git branching rules, TDD lifecycle, or Gitea (`tea`) issue tracking, consult the workspace root [`../AGENTS.md`](../AGENTS.md).

---

## 1. Local Toolchain & Nix Environment (`flake.nix` + `uv`)

This repository is provisioned via a declarative Nix `devShell` (`flake.nix` + `.envrc`) and managed exclusively via `uv`.
- **Nix DevShell:** Ensure commands run inside the Nix environment (`direnv` activates automatically on `cd`, or prefix with `nix develop -c <cmd>`).
- **Package Management:** Do not invoke raw `python`, `pip`, or `virtualenv` commands directly. Always use `uv run`, `uv add`, or `uv sync` so `pyproject.toml` and `uv.lock` remain synchronized.
- **Verification Gates (Pre-Commit Checklist):**
  Before proposing or executing any commit, run and pass all four checks with zero errors or warnings:
  ```bash
  uv run ruff format --check .
  uv run ruff check .
  uv run pyright
  uv run pytest
  ```

---

## 2. Codebase Implementation Rules & Layered Architecture

To keep `armonia-api` infrastructure-agnostic (portable across Turso `libSQL`, local SQLite, PostgreSQL, or future storage engines), enforce strict separation of concerns across `app/`:

### Routers (`app/routers/`)
- **HTTP Transport Only:** Routers handle path/query parameters, request schema validation, FastAPI auth dependencies (`require_admin`), HTTP status codes, and response serialization.
- **Zero Direct Data Access:** Never embed raw SQL statements or direct ORM `Session` queries inside router endpoints. Delegate business workflows to `app/services/` and persistence to `app/repositories/`.

### Services (`app/services/`)
- **Consumer-Agnostic Domain Logic:** Business rules (48-hour follow-up evaluation, 1-on-1 mandatory buffer collision math, WhatsApp deep-link generation, and Google Calendar synchronization) live in `app/services/`.
- **Framework Independence:** Keep service functions decoupled from `fastapi.Depends` and HTTP exceptions so CLI scripts, background jobs, or tests can invoke them directly.

### Repositories & Models (`app/repositories/` & `app/models/`)
- **Data Access Boundary:** Repositories encapsulate all database reads/writes and translate between `SQLModel` table rows and domain/schema objects.
- **Engine Portability:** Configure database connectivity in `app/db/database.py` using `SQLModel` + `sqlalchemy-libsql` (`sqlite+libsql://` for Turso Cloud, falling back cleanly to `sqlite:///local.db` for local execution).

### Schemas (`app/schemas/`)
- **Strict API Contracts:** Maintain explicit Pydantic v2 / SQLModel schemas separating input payloads (`*Create`, `*Update`, `*Request`) from output responses (`*Read`, `*Response`).

### Core & Auth (`app/core/`)
- **Server-Side Security Boundary:** Google OAuth secrets, HMAC session signing, and Turso `admin_allowlist` + `admin_audit_log` verification (`app/core/auth.py`) remain strictly server-side.

---

## 3. Local Test Invariants (`tests/`)

- **Real Local SQLite for Persistence Tests:** Integration and repository tests must run against an isolated local SQLite instance (`file:test_armonia.db` / `sqlite:///test_armonia.db` configured in `tests/conftest.py`). Never make network requests to live Turso Cloud clusters during `pytest` runs, and never mock out SQL/database queries in repository tests (which creates tautological tests).
- **Mocking External I/O Boundaries (`pytest-mock`):** Always isolate external network side-effects—specifically Google Calendar API synchronization (`app/services/calendar.py`) and external OAuth token exchanges—using `pytest-mock` (`mocker` fixture) so the test suite runs deterministically offline.
- **Fixtures Policy:** Centralize database lifecycle setup, test clients, and mock administrator principals inside `tests/conftest.py`.
- **Mutation Testing Audit (`mutmut`):** Once domain rules are extracted into `app/services/`, use `mutmut` (`uv run mutmut run`) scoped to `app/services/` as a pre-PR quality audit to verify that unit tests catch boundary and off-by-one mutations (e.g., 15-minute buffer collision intervals and 48-hour follow-up cutoffs).

---

## 4. Local Structural Maps & Documentation Index

Before modifying domain rules, state transitions, or database schemas, read these canonical specifications to prevent logic drift:
- **Software Requirements Specification:** [`docs/SRS.md`](./docs/SRS.md)
- **System Topology & State Machines (Booking / Payment / 48h Queue):** [`docs/architecture.md`](./docs/architecture.md)
- **Architectural Decision Records (ADRs):** [`docs/decisions/0001-*.md`](./docs/decisions/) through [`0005-*.md`](./docs/decisions/)
- **Relational Schema Reference:** [`app/db/schema.sql`](./app/db/schema.sql) (and `app/models/` during/after the SQLModel migration)
