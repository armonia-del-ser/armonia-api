# ADR 0002: Separated Booking Lifecycle, Delayed-Payment Exceptions, and 48-Hour Follow-Up Visibility

## Status
Accepted (Amended 2026-10-18 per Operational Clarification with Jasmin's Assistant)

## Context
Initially, we assumed that all bookings should require prepayment within a strict 2-hour automatic expiration window (`PENDING_PAYMENT` $\rightarrow$ `EXPIRED`). However, operational clarification with Jasmin's assistant revealed three critical realities:
1. **Prepayment is the default, not an absolute rule**: While most sessions require payment before the appointment, Jasmin occasionally allows trusted clients to pay later. Those sessions must proceed while keeping the outstanding payment explicitly traceable as a delayed payment (`DELAYED_ALLOWED`) rather than silently marking it paid.
2. **Releasing a slot is always a deliberate human decision**: Automatically expiring a booking after 2 hours conflicts with how Jasmin and her assistant operate. Instead, the dashboard must surface unacknowledged bookings as the session approaches (48 hours prior) so the assistant can manually follow up on WhatsApp and decide whether to acknowledge payment, authorize a delayed-payment exception, or deliberately release the slot (`RELEASED`).
3. **Booking status and payment status are distinct facts**: Coupling schedule status (`RESERVED`, `RELEASED`, `COMPLETED`) and financial state (`AWAITING_ACKNOWLEDGMENT`, `ACKNOWLEDGED`) into a single column makes delayed-payment exceptions and post-session receivables impossible to represent cleanly.

## Decision
We separate booking and payment state into three orthogonal fields on `bookings`, supported by an explicit 48-hour follow-up queue and audit trail:
1. **Three Orthogonal State Axes**:
   - `booking_status`: `RESERVED`, `RELEASED`, `CANCELLED`, `COMPLETED`, `NO_SHOW`
   - `payment_arrangement`: `PREPAID_DEFAULT`, `DELAYED_ALLOWED`, `PACKAGE_REDEEMED`
   - `payment_status`: `AWAITING_ACKNOWLEDGMENT`, `ACKNOWLEDGED`, `NOT_APPLICABLE`
2. **48-Hour Follow-Up Queue (Derived Query Condition)**:
   - At 48 hours before `scheduled_at` (configurable via `PAYMENT_FOLLOWUP_THRESHOLD_HOURS`), any `RESERVED` booking with `payment_status = 'AWAITING_ACKNOWLEDGMENT'` surfaces in `GET /bookings/follow-up-queue`.
   - No background worker mutates or expires the booking; the threshold controls operational visibility.
3. **Audited Administrative Actions**:
   - **Acknowledge Payment**: Verifies SPEI/cash receipt and sets `payment_status = 'ACKNOWLEDGED'`, recording `acknowledged_by` and `acknowledged_at`.
   - **Authorize Delayed Payment**: Sets `payment_arrangement = 'DELAYED_ALLOWED'` while keeping `payment_status = 'AWAITING_ACKNOWLEDGMENT'`, recording `exception_authorized_by`, `exception_authorized_at`, and `exception_notes`.
   - **Release Slot**: Sets `booking_status = 'RELEASED'` (and `payment_status = 'NOT_APPLICABLE'` if no session occurred), recording `released_by`, `released_at`, and `release_reason`, immediately freeing the slot for another client.

## Consequences
### Positive
- **Operational Honesty**: Delayed-payment exceptions remain visible as receivables until actually paid and acknowledged.
- **Human-in-the-Loop Control**: Neither Jasmin nor her assistant loses a booking to an unexpected timer, while the 48-hour queue ensures no unpaid slot slips through unnoticed.
- **Zero Background Infrastructure**: Deriving the 48-hour queue on read requires zero cron jobs or always-on workers, preserving the $0 Cloud Run scale-to-zero profile.

### Negative / Trade-offs
- Requires Jasmin's assistant to review the 48-hour follow-up queue and click "Liberar espacio" (`RELEASED`) when a client declines to complete payment.
