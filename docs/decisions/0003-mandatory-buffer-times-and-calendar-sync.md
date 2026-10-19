# ADR 0003: Mandatory Buffer Times and Recoverable Google Calendar Synchronization

## Status
Accepted (Amended 2026-10-18)

## Context
Discovery feedback from long-term clients revealed chronic 10-to-35-minute delays in therapy sessions caused by emotional consultation overruns and back-to-back scheduling without buffers. Additionally, Jasmin relies on Google Calendar to view her daily schedule on her phone, while `armonia-api` (backed by Turso) must remain the authoritative record of business state.

## Decision
1. **Mandatory Post-Session Buffers**: Every individual appointment (`ONE_ON_ONE`) enforces an unbookable 15-to-20-minute buffer interval immediately following the session. A 60-minute consultation blocks 75 minutes on the scheduling engine for any `RESERVED` booking.
2. **Backend-Owned Truth with Google Calendar Coordination**:
   - `armonia-api` owns the authoritative booking and payment decision in Turso; Google Calendar reflects the schedule:
     - `[PAGO PENDIENTE]` when `booking_status = 'RESERVED'`, `payment_arrangement = 'PREPAID_DEFAULT'`, and `payment_status = 'AWAITING_ACKNOWLEDGMENT'`.
     - `[PAGO DIFERIDO]` when `booking_status = 'RESERVED'`, `payment_arrangement = 'DELAYED_ALLOWED'`, and `payment_status = 'AWAITING_ACKNOWLEDGMENT'`.
     - `[CONFIRMADO]` when `payment_status = 'ACKNOWLEDGED'` or `payment_arrangement = 'PACKAGE_REDEEMED'`.
     - Event deleted/cancelled when `booking_status` transitions to `RELEASED` or `CANCELLED`.
3. **Visible & Recoverable Integration State**:
   - Each booking stores `gcal_event_id`, `gcal_sync_status` (`PENDING`, `SYNCED`, `FAILED`, `NOT_CONFIGURED`), `gcal_sync_error`, and `gcal_synced_at`.
   - If the Google Calendar API fails transiently, the Turso record is preserved with `gcal_sync_status = 'FAILED'` and administrators can retry synchronization via `POST /bookings/{id}/sync-calendar`.

## Consequences
### Positive
- Prevents cascade delays across consultations and frees slots immediately when a booking is `RELEASED`.
- Prevents silent divergence between Turso and Google Calendar by surfacing `gcal_sync_status` and `gcal_sync_error` directly to the dashboard.
- Works cleanly in local development and tests (`NOT_CONFIGURED` fallback when GCP credentials are absent).

### Negative / Trade-offs
- Slightly reduces theoretical maximum daily capacity (e.g., maximum 5 sessions/day instead of 6) in exchange for punctuality and therapist well-being.
