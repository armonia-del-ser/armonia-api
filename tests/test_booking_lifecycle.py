from __future__ import annotations

from app.core.auth import create_session_token


def _admin_headers(email: str = "jasmin@armoniadelser.mx") -> dict[str, str]:
    token = create_session_token(email)
    return {"Authorization": f"Bearer {token}"}


def test_reschedule_reserved_booking_success(client):
    headers = _admin_headers()
    svc_res = client.get("/services/atencion-psicologica-individual")
    svc_id = svc_res.json()["id"]

    # 1. Create booking
    b_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Gabriel Sosa",
            "client_phone": "+52 55 1234 9999",
            "scheduled_at": "2026-11-10T10:00:00Z",
        },
    )
    assert b_res.status_code == 201
    booking = b_res.json()
    booking_id = booking["id"]

    # 2. Reschedule to new slot
    new_time = "2026-11-12T16:00:00Z"
    resched_res = client.post(
        f"/bookings/{booking_id}/reschedule",
        headers=headers,
        json={
            "new_scheduled_at": new_time,
            "notes": "Cliente solicitó cambio de fecha por viaje laboral.",
        },
    )
    assert resched_res.status_code == 200
    resched_data = resched_res.json()
    assert resched_data["scheduled_at"] == new_time
    assert resched_data["booking_status"] == "RESERVED"
    assert "2026-11-12" in resched_data["whatsapp_redirect_url"]


def test_reschedule_collision_with_buffer_conflict(client):
    headers = _admin_headers()
    svc_res = client.get("/services/atencion-psicologica-individual")
    svc_id = svc_res.json()["id"]

    # Booking 1 at 10:00 (1h duration + 15m buffer -> blocked until 11:15)
    b1_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Hugo Luna",
            "client_phone": "+52 55 8899 0011",
            "scheduled_at": "2026-11-15T10:00:00Z",
        },
    )
    assert b1_res.status_code == 201

    # Booking 2 at 14:00
    b2_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Ignacio Vega",
            "client_phone": "+52 55 8899 0022",
            "scheduled_at": "2026-11-15T14:00:00Z",
        },
    )
    assert b2_res.status_code == 201
    b2_id = b2_res.json()["id"]

    # Attempt rescheduling B2 into B1's buffer (11:05) -> 409 Conflict
    collision_res = client.post(
        f"/bookings/{b2_id}/reschedule",
        headers=headers,
        json={"new_scheduled_at": "2026-11-15T11:05:00Z"},
    )
    assert collision_res.status_code == 409
    assert "colchón" in collision_res.json()["detail"].lower()

    # Reschedule B2 to exact end of buffer (11:15) -> 200 Success
    valid_res = client.post(
        f"/bookings/{b2_id}/reschedule",
        headers=headers,
        json={"new_scheduled_at": "2026-11-15T11:15:00Z"},
    )
    assert valid_res.status_code == 200
    assert valid_res.json()["scheduled_at"] == "2026-11-15T11:15:00Z"


def test_reschedule_non_reserved_booking_fails(client):
    headers = _admin_headers()
    svc_res = client.get("/services/atencion-psicologica-individual")
    svc_id = svc_res.json()["id"]

    b_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Julio Cortázar",
            "client_phone": "+52 55 4444 5555",
            "scheduled_at": "2026-11-18T10:00:00Z",
        },
    )
    booking_id = b_res.json()["id"]

    # Release booking slot
    client.post(
        f"/bookings/{booking_id}/release",
        headers=headers,
        json={"reason": "Cliente canceló"},
    )

    # Attempt to reschedule released booking -> 400 Bad Request
    resched_res = client.post(
        f"/bookings/{booking_id}/reschedule",
        headers=headers,
        json={"new_scheduled_at": "2026-11-19T10:00:00Z"},
    )
    assert resched_res.status_code == 400
    assert "only reserved" in resched_res.json()["detail"].lower()


def test_reschedule_not_found(client):
    res = client.post(
        "/bookings/non-existent-id/reschedule",
        headers=_admin_headers(),
        json={"new_scheduled_at": "2026-11-19T10:00:00Z"},
    )
    assert res.status_code == 404


def test_complete_reserved_booking_success(client):
    headers = _admin_headers()
    svc_res = client.get("/services/circulo-cacao-presencial")
    svc_id = svc_res.json()["id"]

    # 1. Create booking
    b_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Karla Morales",
            "client_phone": "+52 55 9988 1122",
            "scheduled_at": "2026-11-22T17:00:00Z",
        },
    )
    assert b_res.status_code == 201
    booking_id = b_res.json()["id"]

    # 2. Mark complete
    complete_res = client.post(
        f"/bookings/{booking_id}/complete",
        headers=headers,
        json={"notes": "Sesión completada exitosamente."},
    )
    assert complete_res.status_code == 200
    complete_data = complete_res.json()
    assert complete_data["booking_status"] == "COMPLETED"


def test_complete_non_reserved_booking_fails(client):
    headers = _admin_headers()
    svc_res = client.get("/services/circulo-cacao-presencial")
    svc_id = svc_res.json()["id"]

    b_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Lorena Gil",
            "client_phone": "+52 55 1199 8877",
            "scheduled_at": "2026-11-23T17:00:00Z",
        },
    )
    booking_id = b_res.json()["id"]

    # Cancel booking
    client.post(
        f"/bookings/{booking_id}/status",
        headers=headers,
        json={"booking_status": "CANCELLED"},
    )

    # Attempt to complete cancelled booking -> 400 Bad Request
    complete_res = client.post(f"/bookings/{booking_id}/complete", headers=headers)
    assert complete_res.status_code == 400
    assert "only reserved" in complete_res.json()["detail"].lower()


def test_complete_booking_with_package_records_completion(client):
    headers = _admin_headers()
    svc_res = client.get("/services/atencion-psicologica-individual")
    svc_id = svc_res.json()["id"]

    # 1. Create client
    c_res = client.post(
        "/clients",
        headers=headers,
        json={"full_name": "Mariana Garza", "phone_whatsapp": "+52 55 3322 1100"},
    )
    client_id = c_res.json()["id"]

    # 2. Create package (5 sessions, 0 completed)
    pkg_res = client.post(
        "/packages",
        headers=headers,
        json={
            "client_id": client_id,
            "service_id": svc_id,
            "total_sessions": 5,
            "completed_sessions": 0,
            "financial_status": "PAID",
        },
    )
    pkg_id = pkg_res.json()["id"]

    # 3. Create booking redeemed under package (counter becomes 1)
    b_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Mariana Garza",
            "client_phone": "+52 55 3322 1100",
            "scheduled_at": "2026-11-28T10:00:00Z",
            "package_id": pkg_id,
        },
    )
    assert b_res.status_code == 201
    booking_id = b_res.json()["id"]

    # Verify package has 1 completed session
    pkg_check = client.get(f"/packages/{pkg_id}", headers=headers).json()
    assert pkg_check["completed_sessions"] == 1
    assert pkg_check["remaining_sessions"] == 4

    # 4. Complete consultation
    comp_res = client.post(
        f"/bookings/{booking_id}/complete",
        headers=headers,
        json={"notes": "Primera sesión del paquete completada."},
    )
    assert comp_res.status_code == 200
    assert comp_res.json()["booking_status"] == "COMPLETED"
    assert comp_res.json()["package_id"] == pkg_id

    # Package counter remains 1 (not double-counted)
    pkg_after = client.get(f"/packages/{pkg_id}", headers=headers).json()
    assert pkg_after["completed_sessions"] == 1
    assert pkg_after["remaining_sessions"] == 4


def test_complete_booking_links_package_and_advances_counter(client):
    headers = _admin_headers()
    svc_res = client.get("/services/atencion-psicologica-individual")
    svc_id = svc_res.json()["id"]

    # 1. Create client
    c_res = client.post(
        "/clients",
        headers=headers,
        json={"full_name": "Nicolás Bravo", "phone_whatsapp": "+52 55 6677 8899"},
    )
    client_id = c_res.json()["id"]

    # 2. Create package (5 sessions, 0 completed)
    pkg_res = client.post(
        "/packages",
        headers=headers,
        json={
            "client_id": client_id,
            "service_id": svc_id,
            "total_sessions": 5,
            "completed_sessions": 0,
            "financial_status": "PAID",
        },
    )
    pkg_id = pkg_res.json()["id"]

    # 3. Create regular booking without package (PREPAID_DEFAULT)
    b_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Nicolás Bravo",
            "client_phone": "+52 55 6677 8899",
            "scheduled_at": "2026-11-29T10:00:00Z",
        },
    )
    assert b_res.status_code == 201
    booking = b_res.json()
    assert booking["payment_arrangement"] == "PREPAID_DEFAULT"
    assert booking["package_id"] is None

    # 4. At consultation end, client redeems package session
    comp_res = client.post(
        f"/bookings/{booking['id']}/complete",
        headers=headers,
        json={"package_id": pkg_id, "notes": "Pago aplicado a paquete."},
    )
    assert comp_res.status_code == 200
    comp_data = comp_res.json()
    assert comp_data["booking_status"] == "COMPLETED"
    assert comp_data["package_id"] == pkg_id
    assert comp_data["payment_arrangement"] == "PACKAGE_REDEEMED"

    # Package counter was advanced from 0 to 1
    pkg_after = client.get(f"/packages/{pkg_id}", headers=headers).json()
    assert pkg_after["completed_sessions"] == 1
    assert pkg_after["remaining_sessions"] == 4
