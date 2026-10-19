# Software Requirements Specification (SRS)

## Project: Armonía del Ser Core API (`armonia-api`)

**Document Version:** 1.1.0  
**Status:** Approved (Revised per Operational Clarification with Jasmin's Assistant)  
**Date:** 2026-10-18  
**Scope:** Backend Domain Model, Separated Booking & Payment State Engine, 48-Hour Follow-Up Queue, Google OAuth + Turso Admin Allowlist, and Google Calendar Synchronization  

---

## 1. Introduction & Business Context

### 1.1 Purpose
This document specifies the software requirements for the backend platform of **Armonía del Ser**, an established holistic wellness and psychotherapy practice founded by **Jasmin** in Mexico.

The primary goal of the first deliverable is a tight, reliable backend sitting between **Google Calendar**, **Turso (libSQL)**, and the **Admin Dashboard (`armonia-dashboard`)** protected with a server-side allowlist for **Google OAuth**. Rather than making automated business decisions on Jasmin's behalf, the platform maintains the single operational source of truth and gives Jasmin and her assistant clear visibility to record and follow through on their decisions, while maintaining a strict **$0/month infrastructure cost**.

### 1.2 Business Profile
- **Entity:** Armonía del Ser (operating 20+ years in Tulancingo, Hgo., Mexico).
- **Offerings:** Individual psychotherapy (*Atención Psicológica*), weekly recurring circles (*Círculos de Cacao*, *Meditación con cuencos*, *Constelaciones Familiares*), multi-session packages, and low-cost community workshops (*Curso de Abundancia*).
- **Modalities:** In-person (*Presencial*) and Virtual (*Online* via Google Meet).
- **Payment Culture:** High unbanked / cash / SPEI transfer prevalence; low credit card usage. Payments are verified manually via SPEI bank vouchers (comprobantes) or cash and acknowledged in the dashboard.
- **Communication Channel:** WhatsApp (`+52 775 148 7912`) is used manually by Jasmin's assistant to follow up with clients; a WhatsApp bot is explicitly out of scope for the first deliverable.

---

## 2. User & Stakeholder Personas

1. **Jasmin (Owner & Principal Therapist):**
   - Conducts individual and group therapies.
   - Needs mandatory schedule buffer times (15–20 minutes), accurate Google Calendar coordination, and visibility into which sessions are paid or authorized for delayed payment.
2. **Assistant / Co-Organizer:**
   - Registers clients via WhatsApp and in-person requests.
   - Reviews the 48-hour payment follow-up queue, manually contacts clients via WhatsApp to confirm payment intentions, acknowledges SPEI/cash payments, records authorized delayed-payment exceptions, or deliberately releases slots.
   - Tracks course attendance and marks symbolic workshop payments ($50 MXN).
3. **Clients (Consultantes / Participantes):**
   - Discover services via word-of-mouth or social funnels.
   - Reserve spots online or via WhatsApp, receive transparent SPEI payment instructions with unique folios (`ADS-XXXX`), and coordinate with the assistant on WhatsApp.

---

## 3. Functional Requirements

### 3.1 Service Catalog Management (`FR-CAT`)
- **FR-CAT-1:** The system shall support two distinct service types: `GROUP` (fixed recurring weekly schedule, attendee capacity ~10-25) and `ONE_ON_ONE` (dynamic appointment slots).
- **FR-CAT-2:** Each service shall define name, slug, description, modality (`PRESENCIAL` or `ONLINE`), price in MXN, duration in minutes, mandatory buffer in minutes, and active status.

### 3.2 Orthogonal Booking & Payment State Model (`FR-RSV`)
To avoid coupling schedule reservation state with financial settlement or exceptions, every booking tracks three distinct, orthogonal axes:
- **FR-RSV-1 (`booking_status`):** Represents whether the schedule slot is active:
  - `RESERVED`: Active booking holding a schedule slot.
  - `RELEASED`: Slot deliberately released by an authorized administrator so another client can take the place.
  - `CANCELLED`: Explicitly cancelled by client or therapist.
  - `COMPLETED`: Session took place.
  - `NO_SHOW`: Client failed to attend.
- **FR-RSV-2 (`payment_arrangement`):** Represents the agreed timing/mechanism of payment:
  - `PREPAID_DEFAULT`: Standard rule; payment is expected before the session.
  - `DELAYED_ALLOWED`: Explicit administrative exception allowing the session to proceed with payment outstanding (traceable as a delayed payment).
  - `PACKAGE_REDEEMED`: Covered by an existing multi-session package credit.
- **FR-RSV-3 (`payment_status`):** Represents actual financial settlement:
  - `AWAITING_ACKNOWLEDGMENT`: Payment has not yet been verified/acknowledged by an administrator.
  - `ACKNOWLEDGED`: Administrator verified the SPEI/cash deposit and recorded the acknowledgment.
  - `NOT_APPLICABLE`: Covered by a package redemption or slot released/cancelled prior to session with no outstanding balance.
- **FR-RSV-4 (Prepayment Default & Delayed-Payment Exception):**
  - Prepayment is the default (`PREPAID_DEFAULT`), not an absolute requirement.
  - An authorized administrator may explicitly record a delayed-payment exception (`DELAYED_ALLOWED`), capturing `exception_authorized_by`, `exception_authorized_at`, and `exception_notes`.
  - Authorizing `DELAYED_ALLOWED` **must never** silently mark `payment_status` as `ACKNOWLEDGED`.
- **FR-RSV-5 (Deliberate Slot Release — No Automatic Expiration):**
  - The backend **must not** automatically expire or release a booking based on a timer or background job.
  - Only an authorized administrator can transition a booking to `RELEASED` (recording `released_by`, `released_at`, and `release_reason`).
- **FR-RSV-6 (48-Hour Follow-Up Visibility Queue):**
  - At a configurable threshold before `scheduled_at` (initially **48 hours**), any `RESERVED` booking with `payment_status = 'AWAITING_ACKNOWLEDGMENT'` shall surface in a dedicated dashboard follow-up endpoint (`GET /bookings/follow-up-queue`).
  - The 48-hour threshold is a derived, queryable visibility condition — it does not mutate the booking state.
  - Bookings with `payment_arrangement = 'DELAYED_ALLOWED'` and `payment_status = 'AWAITING_ACKNOWLEDGMENT'` also remain visible in the follow-up/receivables view until acknowledged.
- **FR-RSV-7 (Payment Acknowledgment as Audited Action):**
  - When an administrator verifies payment in their banking workflow and submits acknowledgment, the system records `acknowledged_by` (admin email) and `acknowledged_at` (UTC timestamp) on both the payment record and the booking.
- **FR-RSV-8 (WhatsApp Deep Link & Folio):**
  - Every booking generates a unique human-readable folio (`ADS-XXXX`) and a pre-formatted `wa.me` deep link for manual client communication.

### 3.3 Mandatory Schedule Buffer Times (`FR-BUF`)
- **FR-BUF-1:** Individual therapy sessions (e.g. 60 min) must enforce a **mandatory buffer interval** (minimum 15–20 minutes) following the appointment.
- **FR-BUF-2:** No two active (`RESERVED`) individual appointments may overlap when including their post-session buffer intervals. Releasing (`RELEASED`) or cancelling (`CANCELLED`) a booking frees its slot and buffer immediately.

### 3.4 Multi-Session Packages & Balances (`FR-PKG`)
- **FR-PKG-1:** The system shall support client packages (e.g., 5 or 10 psychotherapy sessions).
- **FR-PKG-2:** The package entity shall track `total_sessions`, `completed_sessions`, and `remaining_sessions`.
- **FR-PKG-3:** The system shall track financial status for the package (`PAID`, `PARTIAL`, `PENDING`).

### 3.5 Group Course Attendance & Payment Ledger (`FR-ATT`)
- **FR-ATT-1:** The system shall provide a digital replacement for physical paper attendance sheets for recurring workshops (e.g., *Curso de Abundancia y Prosperidad*, $50 MXN/session).
- **FR-ATT-2:** Administrators shall be able to record and review workshop attendance and payments.

### 3.6 Google Calendar Coordination (`FR-CAL`)
- **FR-CAL-1:** `armonia-api` owns the authoritative business record in Turso while Google Calendar represents the schedule.
- **FR-CAL-2:** Calendar events reflect the booking and payment arrangement state:
  - `[PAGO PENDIENTE]` when `RESERVED` + `PREPAID_DEFAULT` + `AWAITING_ACKNOWLEDGMENT`.
  - `[PAGO DIFERIDO]` when `RESERVED` + `DELAYED_ALLOWED` + `AWAITING_ACKNOWLEDGMENT`.
  - `[CONFIRMADO]` when `RESERVED` + (`ACKNOWLEDGED` or `PACKAGE_REDEEMED`).
  - Deleted/cancelled from Google Calendar when `booking_status` transitions to `RELEASED` or `CANCELLED`.
- **FR-CAL-3 (Visible & Recoverable Integration State):** Every booking tracks `gcal_event_id`, `gcal_sync_status` (`PENDING`, `SYNCED`, `FAILED`, `NOT_CONFIGURED`), `gcal_sync_error`, and `gcal_synced_at`. Calendar API failures must not silently corrupt or roll back the Turso business record, and administrators can trigger a retry (`POST /bookings/{id}/sync-calendar`).

### 3.7 Administrator Authentication & Allowlist (`FR-AUTH`)
- **FR-AUTH-1:** The backend shall implement Google OAuth2 Authorization Code flow (`/auth/google/login`, `/auth/google/callback`) keeping OAuth client secrets and session-signing secrets exclusively on the server.
- **FR-AUTH-2:** The backend shall verify the Google identity and ensure `email_verified == true`.
- **FR-AUTH-3:** Every authenticated session and administrative request shall verify the user's email against a server-controlled `admin_allowlist` table in Turso (`is_active = 1`), seeded at startup from `ADMIN_BOOTSTRAP_EMAILS`.
- **FR-AUTH-4:** All sensitive administrative mutations (payment acknowledgment, delayed-payment authorization, booking release, status changes) shall record the acting administrator's email in `admin_audit_log` and on the target record.

---

## 4. Non-Functional Requirements

### 4.1 Cost & Operational Efficiency
- **NFR-COST-1:** Zero persistent operational expenditure ($0/month ongoing cost).
- **NFR-COST-2:** Compute executes on serverless containers (Google Cloud Run free tier) scaling to zero — no background cron workers required for the 48-hour visibility threshold.
- **NFR-COST-3:** Data persistence resides on edge SQLite (Turso free tier) with zero idle billing.

### 4.2 Portability & Local Testability
- **NFR-PORT-1:** In local development and CI environments, the system executes against file-based SQLite (`file:local.db`) without requiring remote Turso or live Google Cloud credentials.

---

## 5. Verification & Quality Gates

All codebase contributions must satisfy the mandatory pre-commit verification gates:
1. `uv run ruff format --check .`
2. `uv run ruff check .`
3. `uv run pyright` (zero type errors)
4. `uv run pytest` (100% passing automated test suite)
