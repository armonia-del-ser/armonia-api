from __future__ import annotations

import pytest

from app.core.auth import create_session_token
from app.core.config import settings

DAY = "2027-03-01"  # Monday, America/Mexico_City (UTC-6)


@pytest.fixture
def short_business_day(monkeypatch):
    monkeypatch.setattr(settings, "business_timezone", "America/Mexico_City")
    monkeypatch.setattr(settings, "availability_open_time", "09:00")
    monkeypatch.setattr(settings, "availability_close_time", "13:00")
    monkeypatch.setattr(settings, "availability_slot_step_minutes", 30)
    monkeypatch.setattr(settings, "availability_working_weekdays", [0, 1, 2, 3, 4])


def _individual_service(client) -> dict:
    return client.get("/services/atencion-psicologica-individual").json()


def _book(client, service_id: str, scheduled_at: str, phone: str):
    return client.post(
        "/bookings",
        json={
            "service_id": service_id,
            "client_name": "Cliente Disponibilidad",
            "client_phone": phone,
            "scheduled_at": scheduled_at,
        },
    )


def _slot_starts(body: dict) -> list[str]:
    return [slot["start"] for day in body["days"] for slot in day["slots"]]


def test_availability_excludes_slots_colliding_with_reserved_buffer(client, short_business_day):
    svc = _individual_service(client)
    assert _book(client, svc["id"], f"{DAY}T10:00:00-06:00", "7750001001").status_code == 201

    res = client.get(
        "/availability", params={"service_id": svc["id"], "date_from": DAY, "date_to": DAY}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["service_id"] == svc["id"]
    assert body["duration_minutes"] == 60
    assert body["buffer_minutes"] == 15
    assert body["timezone"] == "America/Mexico_City"
    assert _slot_starts(body) == [f"{DAY}T11:30:00-06:00", f"{DAY}T12:00:00-06:00"]
    assert body["days"][0]["slots"][0]["end"] == f"{DAY}T12:30:00-06:00"


def test_released_bookings_free_their_slots(client, short_business_day):
    day = "2027-03-02"
    svc = _individual_service(client)
    booking = _book(client, svc["id"], f"{day}T09:00:00-06:00", "7750001002").json()
    params = {"service_id": svc["id"], "date_from": day, "date_to": day}
    assert f"{day}T09:00:00-06:00" not in _slot_starts(
        client.get("/availability", params=params).json()
    )

    headers = {"Authorization": f"Bearer {create_session_token('jasmin@armoniadelser.mx')}"}
    rel = client.post(f"/bookings/{booking['id']}/release", headers=headers, json={})
    assert rel.status_code == 200
    assert f"{day}T09:00:00-06:00" in _slot_starts(
        client.get("/availability", params=params).json()
    )


def test_every_offered_slot_is_accepted_by_booking_engine(client, short_business_day):
    day = "2027-03-03"
    svc = _individual_service(client)
    params = {"service_id": svc["id"], "date_from": day, "date_to": day}
    first = _slot_starts(client.get("/availability", params=params).json())[0]
    assert _book(client, svc["id"], first, "7750001003").status_code == 201

    # Next 30-minute step now collides (60 + 15 buffer) and must disappear
    after = _slot_starts(client.get("/availability", params=params).json())
    assert first not in after
    assert f"{day}T09:30:00-06:00" not in after
    assert f"{day}T10:00:00-06:00" not in after
    assert after[0] == f"{day}T10:30:00-06:00"


def test_availability_groups_slots_by_local_day(client, short_business_day):
    svc = _individual_service(client)
    res = client.get(
        "/availability",
        params={"service_id": svc["id"], "date_from": "2027-03-05", "date_to": "2027-03-08"},
    )
    assert res.status_code == 200
    # Fri 5 and Mon 8 are working days; the weekend is omitted
    assert [d["date"] for d in res.json()["days"]] == ["2027-03-05", "2027-03-08"]


def test_availability_rejects_group_services(client):
    svc = client.get("/services/circulo-cacao-presencial").json()
    res = client.get(
        "/availability", params={"service_id": svc["id"], "date_from": DAY, "date_to": DAY}
    )
    assert res.status_code == 400


def test_availability_unknown_service_is_404(client):
    res = client.get(
        "/availability", params={"service_id": "nope", "date_from": DAY, "date_to": DAY}
    )
    assert res.status_code == 404


def test_availability_rejects_inverted_range(client):
    svc = _individual_service(client)
    res = client.get(
        "/availability",
        params={"service_id": svc["id"], "date_from": "2027-03-02", "date_to": "2027-03-01"},
    )
    assert res.status_code == 422


def test_availability_rejects_range_over_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "availability_max_range_days", 7)
    svc = _individual_service(client)
    res = client.get(
        "/availability",
        params={"service_id": svc["id"], "date_from": "2027-03-01", "date_to": "2027-03-08"},
    )
    assert res.status_code == 422
