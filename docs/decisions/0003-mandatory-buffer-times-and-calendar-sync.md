# ADR 0003: Mandatory Buffer Times and Automated Calendar Synchronization

## Status
Accepted

## Context
Discovery feedback from long-term clients revealed chronic 10-to-35-minute delays in therapy sessions. The root causes were twofold:
1. Therapy sessions frequently overrun their scheduled duration due to emotional crises or deep patient complications.
2. Individual sessions were scheduled back-to-back with zero buffer time.
Additionally, Jazmín occasionally misremembered appointment hours or forgot to enter bookings into her calendar.

## Decision
1. **Mandatory Post-Session Buffers**: Every individual appointment slot enforces an unbookable 15-to-20-minute buffer interval immediately following the session. A 60-minute consultation blocks 75–80 minutes on the scheduling engine.
2. **Automated Google Calendar Sync**: All bookings are synced directly via Google Calendar API:
   - `PENDING_PAYMENT` events are created with `[PENDIENTE]` and highlighted in Yellow.
   - `CONFIRMED` events transition to `[CONFIRMADO]` and highlighted in Green.
   - Native calendar push notifications remind Jazmín 24 hours and 1 hour prior to each appointment.

## Consequences
### Positive
- Prevents cascade delays across consultations.
- Eliminates forgotten sessions and schedule collisions.
- Provides emotional decompression time for the therapist between patients.

### Negative / Trade-offs
- Slightly reduces theoretical maximum daily capacity (e.g., maximum 5 sessions/day instead of 6). However, the trade-off strongly favors punctuality, professional reputation, and therapist well-being.
