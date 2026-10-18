# Software Requirements Specification (SRS)

## Project: Armonía del Ser Core API (`armonia-api`)

**Document Version:** 1.0.0  
**Status:** Approved  
**Date:** 2026-10-18  
**Scope:** Backend Domain Model, Scheduling State Engine, Payment Verification, and External Integrations  

---

## 1. Introduction & Business Context

### 1.1 Purpose
This document specifies the software requirements for the backend platform of **Armonía del Ser**, an established holistic wellness and psychotherapy practice founded by Jazmín in Mexico. The system addresses operational disorganization, schedule collisions, consultation tardiness, and payment default ("ghosting") while maintaining a strict **$0/month infrastructure cost**.

### 1.2 Business Profile
- **Entity:** Armonía del Ser (operating 20+ years in Mexico).
- **Offerings:** Individual psychotherapy (*Atención Psicológica*), weekly recurring circles (*Círculos de Cacao*, *Meditación con cuencos*, *Constelaciones Familiares*), multi-session packages, and low-cost community workshops (*Curso de Abundancia*).
- **Modalities:** In-person (*Presencial*) and Virtual (*Online* via Google Meet).
- **Payment Culture:** High unbanked / cash / SPEI transfer prevalence; low credit card usage. Payments are authenticated manually via SPEI bank vouchers (comprobantes) or cash.

---

## 2. User & Stakeholder Personas

1. **Jazmín (Owner & Principal Therapist):**
   - Conducts individual and group therapies.
   - Needs automated calendar protection (buffer times) and a 1-tap payment acknowledgment queue to prevent client ghosting.
2. **Assistant / Co-Organizer:**
   - Registers clients via WhatsApp and in-person requests.
   - Tracks course attendance and marks symbolic payments ($50 MXN).
3. **Clients (Consultantes / Participantes):**
   - Discover services via word-of-mouth or Instagram/social funnels.
   - Reserve spots online or via WhatsApp, receive transparent SPEI payment instructions with unique folios, and send payment vouchers.

---

## 3. Functional Requirements

### 3.1 Service Catalog Management (`FR-CAT`)
- **FR-CAT-1:** The system shall support two distinct service types: `GROUP` (fixed recurring weekly schedule, attendee capacity ~10-25) and `ONE_ON_ONE` (dynamic appointment slots).
- **FR-CAT-2:** Each service shall define name, slug, description, modality (`PRESENCIAL` or `ONLINE`), price in MXN, duration in minutes, and active status.

### 3.2 Anti-Ghosting Reservation State Machine (`FR-RSV`)
- **FR-RSV-1:** When a reservation is created, the system shall assign it the status `PENDING_PAYMENT` with an automated time-to-live (`expires_at = now() + 2 hours`).
- **FR-RSV-2:** The system shall generate a unique human-readable reservation folio (`ADS-XXXX`).
- **FR-RSV-3:** The reservation endpoint shall return a pre-formatted WhatsApp deep link (`wa.me`) containing:
  - Therapist contact number.
  - Service title and appointment date/time.
  - Unique reservation folio (`ADS-XXXX`).
  - Total amount due in MXN.
  - Bank transfer coordinates: Bank name, CLABE, and Beneficiary name.
- **FR-RSV-4:** A reservation shall transition from `PENDING_PAYMENT` to `CONFIRMED` only upon explicit acknowledgment via the payment verification endpoint.

### 3.3 Mandatory Schedule Buffer Times (`FR-BUF`)
- **FR-BUF-1:** To resolve chronic delay cascades caused by emotional consultation overruns, individual therapy sessions (e.g. 60 min) must enforce a **mandatory buffer interval** (minimum 15–20 minutes) following the appointment.
- **FR-BUF-2:** No two individual appointments may be scheduled back-to-back without this buffer interval.

### 3.4 Multi-Session Packages & Balances (`FR-PKG`)
- **FR-PKG-1:** The system shall support client packages (e.g., 5 or 10 psychotherapy sessions).
- **FR-PKG-2:** The package entity shall track `total_sessions`, `completed_sessions`, and `remaining_sessions` to eliminate verbal confusion at session ends.
- **FR-PKG-3:** The system shall track financial status for the package (`FULLY_PAID`, `PARTIAL_DEPOSIT`, `OVERDUE`).

### 3.5 Group Course Attendance & Payment Ledger (`FR-ATT`)
- **FR-ATT-1:** The system shall provide a digital replacement for physical paper attendance sheets for recurring workshops (e.g., *Curso de Abundancia y Prosperidad*, $50 MXN/session).
- **FR-ATT-2:** For any course instance, the administrator or assistant shall be able to toggle attendance (`attended: true/false`) and record payment method (`SPEI`, `CASH`).

### 3.6 Google Calendar Two-Way Synchronization (`FR-CAL`)
- **FR-CAL-1:** Upon reservation creation (`PENDING_PAYMENT`), the API shall insert a tentative Google Calendar event with prefix `[PENDIENTE]` (Color: Yellow).
- **FR-CAL-2:** Upon payment verification (`CONFIRMED`), the API shall update the Google Calendar event to `[CONFIRMADO]` (Color: Green) and attach location/Google Meet links.
- **FR-CAL-3:** If a reservation expires without payment, the API shall delete or mark the tentative event as cancelled.

---

## 4. Non-Functional Requirements

### 4.1 Cost & Operational Efficiency
- **NFR-COST-1:** Zero persistent operational expenditure ($0/month ongoing cost).
- **NFR-COST-2:** Compute must execute on serverless containers (Google Cloud Run free tier) scaling to zero.
- **NFR-COST-3:** Data persistence must reside on edge SQLite (Turso free tier) with zero idle billing.

### 4.2 Portability & Local Testability
- **NFR-PORT-1:** In local development and continuous integration environments, the system must execute against file-based or in-memory SQLite (`file:local.db`) without requiring remote Turso credentials.

### 4.3 Extensibility & Consumer Decoupling
- **NFR-EXT-1:** The API service layer must remain agnostic of specific web frontends, enabling direct consumption by:
  - Mobile Admin Dashboard (`armonia-dashboard`).
  - Public Client Landing (`armonia-landing`).
  - Future WhatsApp Cloud API automated webhooks.
  - Future AI pair programming / Model Context Protocol (MCP) servers.

---

## 5. Verification & Quality Gates

All codebase contributions must satisfy the mandatory pre-commit verification gates:
1. `uv run ruff format --check .`
2. `uv run ruff check .`
3. `uv run pyright` (zero type errors)
4. `uv run pytest` (100% passing automated test suite)
