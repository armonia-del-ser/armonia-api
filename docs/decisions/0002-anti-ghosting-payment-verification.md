# ADR 0002: Anti-Ghosting Payment Verification Workflow via WhatsApp Deep Links

## Status
Accepted

## Context
A major operational pain point for Jazmín is financial default: clients allowed to pay *after* their therapy session often cease responding to WhatsApp messages ("ghosting").
However, implementing a traditional payment gateway like Stripe or Conekta is not viable because:
1. Credit card penetration is low among local wellness clients in Mexico; most prefer cash or SPEI bank transfers.
2. Payment gateway transaction fees (3.6% + $3 MXN + VAT) erode low-ticket therapy margins.
3. Complex checkout forms create drop-offs on mobile devices.

## Decision
We implement a **Verification Loop** using unique folios (`ADS-XXXX`) and WhatsApp deep links (`wa.me`):
1. Client reservation creates a booking in state `PENDING_PAYMENT` with an automatic 2-hour expiration window.
2. The UI immediately renders Jazmín's SPEI coordinates (Bank, CLABE, Beneficiary) and opens a WhatsApp conversation with a pre-filled message including the folio (`ADS-XXXX`).
3. Jazmín receives the transfer proof screenshot in WhatsApp, verifies the deposit in her banking app, and confirms the booking with a single tap in `armonia-dashboard`.
4. Only upon this acknowledgment does the booking transition to `CONFIRMED` and lock into Google Calendar.

## Consequences
### Positive
- **Zero Payment Default**: Eliminates the "pay after session" trap without charging gateway transaction fees.
- **Cultural Alignment**: "Apartar lugar con comprobante" is standard and culturally respected in Mexican wellness communities.
- **Low Friction**: Leverages the tool clients already use continuously (WhatsApp).

### Negative / Trade-offs
- Requires Jazmín (or her assistant) to manually cross-check deposits in her bank app before clicking "Confirmar".
