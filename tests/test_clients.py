from __future__ import annotations

from app.core.auth import create_session_token


def _admin_headers(email: str = "jasmin@armoniadelser.mx") -> dict[str, str]:
    token = create_session_token(email)
    return {"Authorization": f"Bearer {token}"}


def test_create_client_success(client):
    payload = {
        "full_name": "Valeria Domínguez",
        "phone_whatsapp": "+52 55 9876 5432",
        "email": "valeria@example.com",
        "notes": "Prefiere citas por la tarde.",
    }
    res = client.post("/clients", json=payload, headers=_admin_headers())
    assert res.status_code == 201
    data = res.json()
    assert data["full_name"] == "Valeria Domínguez"
    assert data["phone_whatsapp"] == "+52 55 9876 5432"
    assert data["email"] == "valeria@example.com"
    assert data["notes"] == "Prefiere citas por la tarde."
    assert "id" in data
    assert "created_at" in data


def test_create_client_phone_validation(client):
    payload = {
        "full_name": "Invalid Phone User",
        "phone_whatsapp": "invalid-number",
    }
    res = client.post("/clients", json=payload, headers=_admin_headers())
    assert res.status_code == 422


def test_create_client_duplicate_detection(client):
    payload = {
        "full_name": "Roberto Gómez",
        "phone_whatsapp": "+52 55 4433 2211",
        "email": "roberto@example.com",
    }
    first_res = client.post("/clients", json=payload, headers=_admin_headers())
    assert first_res.status_code == 201

    # Attempt registering same phone
    dup_res = client.post("/clients", json=payload, headers=_admin_headers())
    assert dup_res.status_code == 409
    assert "already exists" in dup_res.json()["detail"]


def test_create_client_requires_admin(client):
    payload = {
        "full_name": "Unauthenticated Client",
        "phone_whatsapp": "+52 55 1122 3344",
    }
    res = client.post("/clients", json=payload)
    assert res.status_code == 401


def test_list_and_search_clients(client):
    headers = _admin_headers()

    # Seed 3 distinct clients
    client.post(
        "/clients",
        headers=headers,
        json={"full_name": "Adriana Morales", "phone_whatsapp": "+52 55 7777 0001"},
    )
    client.post(
        "/clients",
        headers=headers,
        json={"full_name": "Adrián Castillo", "phone_whatsapp": "+52 55 7777 0002"},
    )
    client.post(
        "/clients",
        headers=headers,
        json={"full_name": "Beatriz Solís", "phone_whatsapp": "+52 55 8888 0003"},
    )

    # Search by partial name (case-insensitive)
    search_res = client.get("/clients?search=adri", headers=headers)
    assert search_res.status_code == 200
    results = search_res.json()
    names = [c["full_name"] for c in results]
    assert "Adriana Morales" in names
    assert "Adrián Castillo" in names
    assert "Beatriz Solís" not in names

    # Search by partial phone
    phone_res = client.get("/clients?search=8888 0003", headers=headers)
    assert phone_res.status_code == 200
    phone_results = phone_res.json()
    assert len(phone_results) == 1
    assert phone_results[0]["full_name"] == "Beatriz Solís"

    # Pagination: limit and offset
    page_res = client.get("/clients?limit=2&offset=0", headers=headers)
    assert page_res.status_code == 200
    assert len(page_res.json()) <= 2


def test_get_client_360_profile(client):
    headers = _admin_headers()

    # 1. Create client
    c_res = client.post(
        "/clients",
        headers=headers,
        json={
            "full_name": "Camila Ochoa",
            "phone_whatsapp": "+52 55 6655 4433",
            "notes": "Seguimiento quincenal",
        },
    )
    assert c_res.status_code == 201
    c_data = c_res.json()
    client_id = c_data["id"]

    # 2. Fetch service
    svc_res = client.get("/services/atencion-psicologica-individual")
    svc_id = svc_res.json()["id"]

    # 3. Create active package (5 total, 1 completed -> active)
    active_pkg = client.post(
        "/packages",
        headers=headers,
        json={
            "client_id": client_id,
            "service_id": svc_id,
            "total_sessions": 5,
            "completed_sessions": 1,
            "financial_status": "PAID",
        },
    ).json()

    # 4. Create exhausted package (3 total, 3 completed -> inactive)
    client.post(
        "/packages",
        headers=headers,
        json={
            "client_id": client_id,
            "service_id": svc_id,
            "total_sessions": 3,
            "completed_sessions": 3,
            "financial_status": "PAID",
        },
    )

    # 5. Create a booking for this client
    b_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Camila Ochoa",
            "client_phone": "+52 55 6655 4433",
            "scheduled_at": "2026-11-20T10:00:00Z",
        },
    )
    assert b_res.status_code == 201

    # 6. Fetch Client 360 profile
    profile_res = client.get(f"/clients/{client_id}", headers=headers)
    assert profile_res.status_code == 200
    profile = profile_res.json()

    assert profile["id"] == client_id
    assert profile["full_name"] == "Camila Ochoa"
    assert profile["notes"] == "Seguimiento quincenal"

    # Active packages should only include package with remaining sessions
    assert len(profile["active_packages"]) == 1
    assert profile["active_packages"][0]["id"] == active_pkg["id"]
    assert profile["active_packages"][0]["remaining_sessions"] == 4

    # Booking history should contain the booking
    assert len(profile["booking_history"]) >= 1
    assert profile["booking_history"][0]["client_id"] == client_id


def test_get_client_not_found(client):
    res = client.get("/clients/non-existent-id", headers=_admin_headers())
    assert res.status_code == 404


def test_patch_client_success(client):
    headers = _admin_headers()
    created = client.post(
        "/clients",
        headers=headers,
        json={"full_name": "Daniela Ruiz", "phone_whatsapp": "+52 55 9900 1122"},
    ).json()

    patch_payload = {
        "full_name": "Daniela Ruiz de Chávez",
        "notes": "Cambio de apellido civil.",
        "email": "daniela@example.com",
    }
    patch_res = client.patch(f"/clients/{created['id']}", headers=headers, json=patch_payload)
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert updated["full_name"] == "Daniela Ruiz de Chávez"
    assert updated["notes"] == "Cambio de apellido civil."
    assert updated["email"] == "daniela@example.com"
    assert updated["phone_whatsapp"] == "+52 55 9900 1122"


def test_patch_client_duplicate_phone(client):
    headers = _admin_headers()
    client.post(
        "/clients",
        headers=headers,
        json={"full_name": "Usuario Uno", "phone_whatsapp": "+52 55 1212 1212"},
    )
    c2 = client.post(
        "/clients",
        headers=headers,
        json={"full_name": "Usuario Dos", "phone_whatsapp": "+52 55 3434 3434"},
    ).json()

    # Attempt to change c2 phone to c1 phone -> 409 Conflict
    patch_res = client.patch(
        f"/clients/{c2['id']}",
        headers=headers,
        json={"phone_whatsapp": "+52 55 1212 1212"},
    )
    assert patch_res.status_code == 409


def test_delete_client_safe_integrity_check(client):
    headers = _admin_headers()

    # Create client with booking
    svc_res = client.get("/services/atencion-psicologica-individual")
    svc_id = svc_res.json()["id"]

    b_res = client.post(
        "/bookings",
        json={
            "service_id": svc_id,
            "client_name": "Enrique Peña",
            "client_phone": "+52 55 7766 5544",
            "scheduled_at": "2026-11-25T12:00:00Z",
        },
    )
    client_id = b_res.json()["client_id"]

    # Attempt to delete client with active booking -> 409 Conflict
    del_res = client.delete(f"/clients/{client_id}", headers=headers)
    assert del_res.status_code == 409
    assert "associated" in del_res.json()["detail"].lower()


def test_delete_client_without_dependencies(client):
    headers = _admin_headers()
    c = client.post(
        "/clients",
        headers=headers,
        json={"full_name": "Fernando Morales", "phone_whatsapp": "+52 55 9988 7766"},
    ).json()
    client_id = c["id"]

    del_res = client.delete(f"/clients/{client_id}", headers=headers)
    assert del_res.status_code == 204

    # Confirm it cannot be found
    get_res = client.get(f"/clients/{client_id}", headers=headers)
    assert get_res.status_code == 404
