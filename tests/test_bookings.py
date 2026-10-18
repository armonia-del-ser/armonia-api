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
