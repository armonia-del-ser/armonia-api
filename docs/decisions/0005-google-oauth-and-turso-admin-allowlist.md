# ADR 0005: Backend Google OAuth2 Authentication and Turso Administrator Allowlist

## Status
Accepted (2026-10-18)

## Context
`armonia-dashboard` is an operational control surface used by Jasmin and her assistant to acknowledge SPEI/cash payments, authorize delayed-payment exceptions, and release booking slots. Because `armonia-dashboard` is deployed as a static application on Cloudflare Pages, client-side route guards alone cannot protect administrative operations or keep OAuth secrets safe. Furthermore, if Jasmin rotates her assistant, revoking access must take effect immediately without rebuilding or redeploying containers.

## Decision
1. **Backend-Driven Google OAuth2 Authorization Code Flow**:
   - `armonia-api` hosts `/auth/google/login` and `/auth/google/callback`, keeping `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, and `SESSION_SECRET_KEY` strictly on the backend.
   - Upon callback, `armonia-api` exchanges the authorization code with Google, verifies `email_verified == true`, and checks the email against Turso's `admin_allowlist` table.
   - `armonia-api` issues an HMAC-SHA256 signed session token (delivered via `HttpOnly` cookie and usable as a `Bearer` token).
2. **Dedicated `admin_allowlist` Table in Turso**:
   - Stores `email PRIMARY KEY`, `full_name`, `role` (`OWNER`, `ASSISTANT`, `ADMIN`), `is_active`, `created_at`, and `last_login_at`.
   - Seeded idempotently on startup from `ADMIN_BOOTSTRAP_EMAILS`.
   - Checked on **every** authenticated administrative request so setting `is_active = 0` revokes access immediately.
3. **Mandatory Audit Logging (`admin_audit_log`)**:
   - Every administrative mutation records the authenticated administrator's email, action type, target entity ID, and timestamp in `admin_audit_log` as well as on the booking/payment record (`acknowledged_by`, `exception_authorized_by`, `released_by`).

## Consequences
### Positive
- Zero OAuth client secrets or session signing keys exposed in the frontend bundle.
- Instant administrator revocation or addition via Turso without container redeployment.
- Complete accountability for who acknowledged a payment, authorized a delayed payment, or released a slot.

### Negative / Trade-offs
- Every protected administrative request performs a fast primary-key lookup against `admin_allowlist` in Turso/SQLite.
