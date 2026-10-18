from __future__ import annotations


def test_booking_and_payment_flow(client):
    # 1. Fetch a service
    svc_res = client.get("/services/circulo-cacao-presencial")
    assert svc_res.status_code == 200
    svc = svc_res.json()

    # 2. Create reservation
    booking_payload = {
        "service_id": svc["id"],
        "client_name": "Carlos Méndez",
        "client_phone": "5512345678",
        "client_email": "carlos@example.com",
        "scheduled_at": "2026-10-26T18:00:00Z",
        "notes": "Primera vez en círculo de cacao",
    }
    b_res = client.post("/bookings", json=booking_payload)
    assert b_res.status_code == 201
    booking = b_res.json()

    assert booking["status"] == "PENDING_PAYMENT"
    assert booking["booking_code"].startswith("ADS-")
    assert booking["amount_mxn"] == 350
    assert "wa.me" in booking["whatsapp_redirect_url"]
    assert "ADS-" in booking["whatsapp_redirect_url"]

    # 3. Verify payment (Admin action)
    pay_payload = {
        "booking_id": booking["id"],
        "amount_mxn": 350,
        "payment_method": "SPEI",
        "notes": "Transferencia recibida BBVA",
    }
    p_res = client.post("/payments/verify", json=pay_payload)
    assert p_res.status_code == 201
    payment = p_res.json()
    assert payment["status"] == "VERIFIED"
    assert payment["booking_id"] == booking["id"]

    # 4. Confirm booking status updated
    list_res = client.get("/bookings?status=CONFIRMED")
    assert list_res.status_code == 200
    confirmed_bookings = list_res.json()
    matching = [b for b in confirmed_bookings if b["id"] == booking["id"]]
    assert len(matching) == 1
    assert matching[0]["status"] == "CONFIRMED"


def test_one_on_one_buffer_collision(client):
    svc_res = client.get("/services/atencion-psicologica-individual")
    assert svc_res.status_code == 200
    svc = svc_res.json()
    assert svc["duration_minutes"] == 60
    assert svc["buffer_minutes"] == 15

    # Book 10:00 AM - 11:00 AM (+ 15m buffer = blocked until 11:15 AM)
    first_res = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Ana López",
            "client_phone": "5511112222",
            "scheduled_at": "2026-10-27T10:00:00Z",
        },
    )
    assert first_res.status_code == 201

    # Attempt booking at 11:05 AM (within 15-min mandatory buffer) -> 409 Conflict
    collision_res = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Pedro Ramírez",
            "client_phone": "5533334444",
            "scheduled_at": "2026-10-27T11:05:00Z",
        },
    )
    assert collision_res.status_code == 409

    # Book at 11:15 AM (exact end of buffer) -> 201 Created
    valid_res = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Pedro Ramírez",
            "client_phone": "5533334444",
            "scheduled_at": "2026-10-27T11:15:00Z",
        },
    )
    assert valid_res.status_code == 201


def test_package_creation_and_redemption(client):
    svc_res = client.get("/services/atencion-psicologica-individual")
    svc = svc_res.json()

    # Create initial booking to register client
    initial_b = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Lucía Fernández",
            "client_phone": "5599998888",
            "scheduled_at": "2026-11-01T09:00:00Z",
        },
    ).json()
    client_id = initial_b["client_id"]

    # Create a 10-session package with 7 already completed
    pkg_res = client.post(
        "/packages",
        json={
            "client_id": client_id,
            "service_id": svc["id"],
            "total_sessions": 10,
            "completed_sessions": 7,
            "price_paid_mxn": 5000,
            "financial_status": "PAID",
            "notes": "Paquete 10 sesiones psicoterapia",
        },
    )
    assert pkg_res.status_code == 201
    pkg = pkg_res.json()
    assert pkg["remaining_sessions"] == 3

    # Redeem session 8 of 10 via booking
    redeem_res = client.post(
        "/bookings",
        json={
            "service_id": svc["id"],
            "client_name": "Lucía Fernández",
            "client_phone": "5599998888",
            "scheduled_at": "2026-11-08T09:00:00Z",
            "package_id": pkg["id"],
        },
    )
    assert redeem_res.status_code == 201
    redeemed_booking = redeem_res.json()
    assert redeemed_booking["status"] == "CONFIRMED"
    assert redeemed_booking["amount_mxn"] == 0
    assert "8%20de%2010" in redeemed_booking["whatsapp_redirect_url"]

    # Verify package counter incremented to 8 completed / 2 remaining
    pkg_get = client.get(f"/packages/{pkg['id']}")
    assert pkg_get.status_code == 200
    assert pkg_get.json()["completed_sessions"] == 8
    assert pkg_get.json()["remaining_sessions"] == 2
