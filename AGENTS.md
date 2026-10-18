# Armonía del Ser: API - Agent Guidelines & Workflow Rules

This document specifies mandatory workflows, constraints, and verification gates for AI agents operating in `armonia-api`.

---

## 1. Core Operating Constraints

- **No Direct Commits to `main`**: Agents must never commit directly to `main`. All work must be developed on descriptive feature, bugfix, or chore branches (`feat/*`, `fix/*`, `chore/*`).
- **No Destructive Git Actions**: Commands such as `git reset --hard`, `git restore <file>`, `git clean -fd`, and force-pushes (`git push --force`) are strictly prohibited without the user's explicit yes.
- **Secret Redaction**: Never print, commit, or log sensitive information (Turso tokens, GCP credentials, API keys).
- **Session Modes**:
  - `learning`: The user drives and writes the reasoning, the agent asks guiding questions.
  - `delivery`: The agent may draft code and plans, presenting rationale and trade-offs.

---

## 2. Verification Gates (Pre-Commit Checklist)

Before proposing or executing any commit, run and verify:

1. **Ruff Formatting**:
   ```bash
   uv run ruff format --check .
   ```
2. **Ruff Linting**:
   ```bash
   uv run ruff check .
   ```
3. **Static Type Checking (Pyright)**:
   ```bash
   uv run pyright
   ```
4. **Automated Test Suite (Pytest)**:
   ```bash
   uv run pytest
   ```

No commit may be generated if any of these checks fail or report unhandled errors.

---

## 3. Architecture & Domain Directives

- **Database Abstraction**: Use `libsql-client` with clean fallback to local SQLite (`file:local.db`). In local testing, tests run against in-memory or temporary local SQLite instances without needing cloud credentials.
- **Anti-Ghosting Booking State Machine**:
  - `PENDING_PAYMENT`: Initial state upon client reservation. Slot held tentatively for 2 hours.
  - `CONFIRMED`: Acknowledged by Jazmin via the Admin Dashboard after checking bank deposit.
  - `EXPIRED`: Automatic timeout if no SPEI proof is acknowledged.
  - `CANCELLED`: Explicit cancellation.
  - `NO_SHOW`: Marked if client failed to attend.
- **Consumer Agnostic**: Keep service functions and database queries decoupled from the FastAPI routers so they can be seamlessly consumed by an MCP server, WhatsApp webhook worker, or background job runner in the future.
