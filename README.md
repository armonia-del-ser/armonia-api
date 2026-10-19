# Armonía del Ser: Core API (`armonia-api`)

Backend API service for **Armonía del Ser**—a holistic therapy, meditation, and personal growth center founded by **Jasmin** in Mexico.

Built with **FastAPI** and **Turso (libSQL)** to serve as the operational source of truth between **Google Calendar**, **Turso**, and the **Admin Dashboard (`armonia-dashboard`)** protected with a server-side allowlist for **Google OAuth**.

---

## Architecture & Design

```
[Clients / Landing UI]          [Admin Dashboard (Jasmin & Assistant)]
          │                                  │ (Google OAuth + Turso Allowlist)
          ▼                                  ▼
┌──────────────────────────────────────────────────────────┐
│                   FastAPI Core Service                   │
│  - Separated Booking & Payment State Engine              │
│  - 48-Hour Payment Follow-Up Queue & Delayed Exceptions  │
│  - Deliberate Slot Release & Audit Trail                 │
│  - Google OAuth2 + Turso Allowlist Guard                 │
└──────────────┬─────────────────────────────┬─────────────┘
               │                             │
               ▼                             ▼
       [Turso Database]            [Google Calendar API]
  (SQLite / libSQL at edge)      (Schedule coordination &
                                  recoverable sync health)
```

### Key Principles

1. **Separated Booking & Payment States**:
   - `booking_status` (`RESERVED`, `RELEASED`, `CANCELLED`, `COMPLETED`, `NO_SHOW`) is modeled orthogonally from `payment_arrangement` (`PREPAID_DEFAULT`, `DELAYED_ALLOWED`, `PACKAGE_REDEEMED`) and `payment_status` (`AWAITING_ACKNOWLEDGMENT`, `ACKNOWLEDGED`, `NOT_APPLICABLE`).
2. **Prepayment by Default, Explicit Delayed-Payment Exceptions**:
   - Most bookings require prepayment (`PREPAID_DEFAULT`). Authorized administrators can explicitly authorize a delayed-payment exception (`DELAYED_ALLOWED`), keeping `payment_status = 'AWAITING_ACKNOWLEDGMENT'` until payment is actually settled.
3. **Deliberate Slot Release & 48-Hour Follow-Up Visibility**:
   - Bookings never expire automatically on a timer. At 48 hours prior to a session, unacknowledged bookings appear in `GET /bookings/follow-up-queue` so the assistant can manually follow up via WhatsApp and either acknowledge payment, authorize delayed payment, or deliberately release the slot (`RELEASED`).
4. **Google OAuth + Turso Allowlist**:
   - Administrative endpoints verify the caller's Google OAuth session against Turso's `admin_allowlist` table on every request and record all mutations in `admin_audit_log`.
5. **Zero-Cost Infrastructure**:
   - Runs containerized on **Google Cloud Run** free tier (scale-to-zero, $0/month).
   - Data stored in **Turso** free tier, with local fallback to file-based SQLite (`file:local.db`).

---

## Data Model Overview

| Entity | Purpose |
| :--- | :--- |
| `admin_allowlist` | Authorized administrator emails (`OWNER`, `ASSISTANT`, `ADMIN`), active status, and last login timestamp. |
| `services` | Catalog of offerings (Círculos de Cacao, Meditaciones, Constelaciones, Psicoterapia), format (`ONLINE` / `PRESENCIAL`), type (`GROUP` / `INDIVIDUAL`), capacity, mandatory buffer, and price in MXN. |
| `clients` | Client directory (name, phone / WhatsApp, email, notes). |
| `bookings` | Appointments tracking `booking_status`, `payment_arrangement`, `payment_status`, folio (`ADS-XXXX`), exception/release/acknowledgment audit metadata, and Google Calendar sync health. |
| `payments` | Audit record of SPEI/OXXO/cash payment acknowledgment (`acknowledged_by`, `acknowledged_at`, notes). |
| `admin_audit_log` | Immutable log of administrative actions (`ACKNOWLEDGE_PAYMENT`, `AUTHORIZE_DELAYED_PAYMENT`, `RELEASE_BOOKING`, etc.). |

---

## Local Development Quickstart

### Prerequisites
- Python 3.13+
- [`uv`](https://github.com/astral-sh/uv)

### 1. Setup Environment
```bash
cp .env.example .env
```
By default, `.env` uses `DATABASE_URL=file:local.db` for zero-configuration local SQLite testing.

### 2. Install Dependencies
```bash
uv sync
```

### 3. Initialize Database & Seed Services
```bash
uv run python -m app.db.init_db
```

### 4. Run Development Server
```bash
uv run uvicorn app.main:app --reload --port 8000
```
Interactive API docs are available at `http://localhost:8000/docs`.

---

## Verification Gates

All changes must pass local verification before proposing commits:
```bash
uv run ruff format --check .
uv run ruff check .
uv run pyright
uv run pytest
```