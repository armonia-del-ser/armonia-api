from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.auth import create_session_token
from app.core.config import settings


def _admin_headers(email: str = "jasmin@armoniadelser.mx") -> dict[str, str]:
    token = create_session_token(email)
    return {"Authorization": f"Bearer {token}"}


def test_admin_auth_and_turso_allowlist_enforcement(client):
    # 1. Unauthenticated request to protected endpoint returns 401
    unauth_res = client.get("/bookings/follow-up-queue")
    assert unauth_res.status_code == 401

    # 2. Signed token for non-allowlisted email returns 403
    intruder_headers = _admin_headers("intruder@example.com")
    forbidden_res = client.get("/bookings/follow-up-queue", headers=intruder_headers)
    assert forbidden_res.status_code == 403

    # 3. Bootstrap allowlisted admin (Jasmin) succeeds on /auth/me
    me_res = client.get("/auth/me", headers=_admin_headers("jasmin@armoniadelser.mx"))
    assert me_res.status_code == 200
    assert me_res.json()["email"] == "jasmin@armoniadelser.mx"
    assert me_res.json()["role"] == "OWNER"

    # 4. Add a temporary assistant to allowlist, verify access, then revoke (is_active=False)
    add_res = client.post(
        "/auth/allowlist",
        headers=_admin_headers("jasmin@armoniadelser.mx"),
        json={
            "email": "temp.assistant@armoniadelser.mx",
            "full_name": "Asistente Temporal",
            "role": "ASSISTANT",
            "is_active": True,
        },
    )
    assert add_res.status_code == 201

    temp_headers = _admin_headers("temp.assistant@armoniadelser.mx")
    assert client.get("/auth/me", headers=temp_headers).status_code == 200

    # Revoke access in Turso allowlist -> immediate 403 on next request
    revoke_res = client.patch(
        "/auth/allowlist/temp.assistant@armoniadelser.mx",
        headers=_admin_headers("jasmin@armoniadelser.mx"),
        json={"is_active": False},
    )
    assert revoke_res.status_code == 200
    assert client.get("/auth/me", headers=temp_headers).status_code == 403


def test_48h_followup_queue_and_deliberate_release(client):
    svc = client.get("/services/atencion-psicologica-individual").json()
    now = datetime.now(UTC)

    # Booking A: 24 hours from now (within 48h window) -> Should appear in follow-up queue
    slot_24h = (now + timedelta(hours=24)).replace(microsecond=0).isoformat()
    b_near = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Mariana Vega",
            "client_phone": "7751234567",
            "scheduled_at": slot_24h,
        },
    ).json()
    assert b_near["needs_payment_followup"] is True

    # Booking B: 96 hours from now (outside 48h window) -> Should NOT appear in 48h queue yet
    slot_96h = (now + timedelta(hours=96)).replace(microsecond=0).isoformat()
    b_far = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Roberto Solís",
            "client_phone": "7757654321",
            "scheduled_at": slot_96h,
        },
    ).json()
    assert b_far["needs_payment_followup"] is False

    queue_res = client.get(
        "/bookings/follow-up-queue?window_hours=48",
        headers=_admin_headers("asistente@armoniadelser.mx"),
    )
    assert queue_res.status_code == 200
    queue_ids = [b["id"] for b in queue_res.json()]
    assert b_near["id"] in queue_ids
    assert b_far["id"] not in queue_ids

    # Assistant follows up via WhatsApp and client prefers to release the slot
    rel_res = client.post(
        f"/bookings/{b_near['id']}/release",
        headers=_admin_headers("asistente@armoniadelser.mx"),
        json={"reason": "Cliente solicitó liberar espacio tras seguimiento por WhatsApp"},
    )
    assert rel_res.status_code == 200
    released = rel_res.json()
    assert released["booking_status"] == "RELEASED"
    assert released["payment_status"] == "NOT_APPLICABLE"
    assert released["released_by"] == "asistente@armoniadelser.mx"

    # Released booking no longer appears in the follow-up queue
    queue_after = client.get(
        "/bookings/follow-up-queue?window_hours=48",
        headers=_admin_headers("asistente@armoniadelser.mx"),
    ).json()
    assert b_near["id"] not in [b["id"] for b in queue_after]

    # And another client can now book the exact released slot!
    rebook_res = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Elena Torres",
            "client_phone": "7759990000",
            "scheduled_at": slot_24h,
        },
    )
    assert rebook_res.status_code == 201


def test_delayed_payment_exception_and_post_session_settlement(client):
    svc = client.get("/services/circulo-cacao-online").json()
    now = datetime.now(UTC)
    slot_time = (now + timedelta(hours=120)).replace(microsecond=0).isoformat()

    # 1. Create booking
    booking = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Sofía Luna",
            "client_phone": "5544332211",
            "scheduled_at": slot_time,
        },
    ).json()
    assert booking["payment_arrangement"] == "PREPAID_DEFAULT"
    assert booking["payment_status"] == "AWAITING_ACKNOWLEDGMENT"

    # 2. Jasmin authorizes delayed-payment exception
    exc_res = client.post(
        f"/bookings/{booking['id']}/authorize-delayed-payment",
        headers=_admin_headers("jasmin@armoniadelser.mx"),
        json={"notes": "Paciente frecuente, pagará el viernes en efectivo"},
    )
    assert exc_res.status_code == 200
    exc_booking = exc_res.json()
    assert exc_booking["payment_arrangement"] == "DELAYED_ALLOWED"
    # Must NOT silently mark payment as completed!
    assert exc_booking["payment_status"] == "AWAITING_ACKNOWLEDGMENT"
    assert exc_booking["exception_authorized_by"] == "jasmin@armoniadelser.mx"
    assert exc_booking["needs_payment_followup"] is True

    # 3. Session occurs -> marked COMPLETED, payment is STILL AWAITING_ACKNOWLEDGMENT
    comp_res = client.post(
        f"/bookings/{booking['id']}/status",
        headers=_admin_headers("jasmin@armoniadelser.mx"),
        json={"booking_status": "COMPLETED", "notes": "Sesión realizada"},
    )
    assert comp_res.status_code == 200
    comp_booking = comp_res.json()
    assert comp_booking["booking_status"] == "COMPLETED"
    assert comp_booking["payment_status"] == "AWAITING_ACKNOWLEDGMENT"

    # Still traceable in follow-up / receivables queue!
    queue = client.get("/bookings/follow-up-queue", headers=_admin_headers()).json()
    assert booking["id"] in [b["id"] for b in queue]

    # 4. Client finally pays -> Admin acknowledges payment
    ack_res = client.post(
        "/payments/acknowledge",
        headers=_admin_headers("jasmin@armoniadelser.mx"),
        json={
            "booking_id": booking["id"],
            "amount_mxn": svc["price_mxn"],
            "payment_method": "CASH",
            "notes": "Pago diferido liquidado en efectivo",
        },
    )
    assert ack_res.status_code == 201

    # Now removed from follow-up queue and marked ACKNOWLEDGED
    queue_after = client.get("/bookings/follow-up-queue", headers=_admin_headers()).json()
    assert booking["id"] not in [b["id"] for b in queue_after]


def test_calendar_sync_failure_visibility_and_manual_recovery(client, monkeypatch):
    svc = client.get("/services/meditacion-guiada-sabado").json()

    # Simulate transient Google Calendar failure during booking creation
    monkeypatch.setattr(settings, "google_service_account_json", "fail-gcal")
    b_res = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Jorge Ríos",
            "client_phone": "5588776655",
            "scheduled_at": "2026-11-14T07:00:00Z",
        },
    )
    # Booking creation succeeds in Turso while surfacing FAILED calendar sync status
    assert b_res.status_code == 201
    booking = b_res.json()
    assert booking["gcal_sync_status"] == "FAILED"
    assert "503" in (booking["gcal_sync_error"] or "")

    # Restore Calendar connectivity and retry sync from admin endpoint
    monkeypatch.setattr(settings, "google_service_account_json", "mock-gcal")
    retry_res = client.post(
        f"/bookings/{booking['id']}/sync-calendar",
        headers=_admin_headers(),
    )
    assert retry_res.status_code == 200
    recovered = retry_res.json()
    assert recovered["gcal_sync_status"] == "SYNCED"
    assert recovered["gcal_sync_error"] is None
    assert recovered["gcal_event_id"] is not None
