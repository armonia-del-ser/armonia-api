# Armonía del Ser: Core API (`armonia-api`)

Backend API service for **Armonía del Ser**—a holistic therapy, meditation, and personal growth center in Mexico.

Built with **FastAPI** and **Turso (libSQL)** to manage services, appointments, client records, and payment acknowledgments at zero infrastructure cost.

---

## Architecture & Design

```
[Clients / Landing UI]          [Admin Dashboard (Jazmín)]
          │                                  │
          ▼                                  ▼
┌──────────────────────────────────────────────────────────┐
│                   FastAPI Core Service                   │
│  - Services Catalog (Group & 1-on-1)                     │
│  - Booking State Machine (Pending -> Confirmed)          │
│  - Payment Verification & Acknowledgment                 │
│  - Dynamic WhatsApp Deep-Link Generator                  │
└──────────────┬─────────────────────────────┬─────────────┘
               │                             │
               ▼                             ▼
       [Turso Database]            [Google Calendar API]
  (SQLite / libSQL at edge)      (Tentative [PENDIENTE] hold
                                   -> Locked [CONFIRMADO])
```

### Key Principles

1. **Anti-Ghosting Payment Workflow**:
   - A client reserves a spot -> Booking is saved as `PENDING_PAYMENT` with a unique folio (`ADS-XXXX`).
   - A tentative hold is placed on Google Calendar.
   - Client is redirected to WhatsApp with pre-filled transfer details (SPEI CLABE + Folio).
   - Once Jazmín verifies the deposit in her banking app, she acknowledges it via the Admin Dashboard (`armonia-dashboard`).
   - Booking transitions to `CONFIRMED`, locking the calendar event and sending confirmation details.
2. **Zero-Cost Infrastructure**:
   - Runs containerized on **Google Cloud Run** free tier (scale-to-zero, $0/month).
   - Data stored in **Turso** free tier (up to 9 GB storage, billions of monthly row reads).
   - In local development and automated testing, seamlessly falls back to standard file-based SQLite (`file:local.db`).
3. **Consumer Agnostic**:
   - Designed to serve both web frontends (`armonia-dashboard`, `armonia-landing`) and future headless consumers (an MCP server for AI pair programming, a WhatsApp Business Cloud API webhook, or an LLM booking assistant).

---

## Data Model Overview

| Entity | Purpose |
| :--- | :--- |
| `services` | Catalog of offerings (Círculos de Cacao, Meditaciones, Constelaciones, Psicoterapia), format (`ONLINE` / `PRESENCIAL`), type (`GROUP` / `ONE_ON_ONE`), capacity, and price in MXN. |
| `clients` | Client directory (name, phone / WhatsApp, email, notes). |
| `bookings` | Appointments linked to a service and client, tracking status (`PENDING_PAYMENT`, `CONFIRMED`, `CANCELLED`, `EXPIRED`, `NO_SHOW`), folio, and expiration. |
| `payments` | Audit record of SPEI/OXXO payment verification, notes, and acknowledgment timestamp. |

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