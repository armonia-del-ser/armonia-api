from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session, select

from app.core.auth import create_session_token
from app.core.config import AuthProvider, settings
from app.db.database import get_engine
from app.models.admin import AdminAuditLog
from app.models.payment import Payment
from app.models.service import Service, ServiceModalityEnum, ServiceTypeEnum


def _admin(email: str = "asistente@armoniadelser.mx") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_session_token(email)}"}


def _book(client, service_id: str, scheduled_at: str, phone: str, name: str = "Asistente Cacao"):
    res = client.post(
        "/bookings",
        json={
            "service_id": service_id,
            "client_name": name,
            "client_phone": phone,
            "scheduled_at": scheduled_at,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def _roster(client, day: str, service_id: str | None = None) -> list[dict]:
    params = {"date_from": day, "date_to": day}
    if service_id:
        params["service_id"] = service_id
    res = client.get("/rosters", params=params, headers=_admin())
    assert res.status_code == 200, res.text
    return res.json()


def _queue_ids(client) -> list[str]:
    return [b["id"] for b in client.get("/bookings/follow-up-queue", headers=_admin()).json()]


@pytest.fixture
def cacao(client) -> dict:
    return client.get("/services/circulo-cacao-presencial").json()


@pytest.fixture
def tiny_workshop() -> dict:
    """A GROUP service with capacity 1, inserted through the real SQLModel engine."""
    service_id = str(uuid.uuid4())
    with Session(get_engine()) as session:
        session.add(
            Service(
                id=service_id,
                slug=f"taller-mini-{service_id[:8]}",
                name="Taller Mini",
                service_type=ServiceTypeEnum.GROUP,
                modality=ServiceModalityEnum.PRESENCIAL,
                price_mxn=50,
                max_capacity=1,
                duration_minutes=60,
                buffer_minutes=0,
            )
        )
        session.commit()
    return {"id": service_id, "price_mxn": 50}


# --- GET /rosters ---------------------------------------------------------------------


def test_rosters_require_admin(client):
    assert client.get("/rosters").status_code == 401


def test_roster_groups_attendees_by_session_instant_across_iso_formats(client, cacao):
    # Same instant written two ways must land in ONE session
    a = _book(client, cacao["id"], "2027-04-06T18:00:00Z", "5510000001", "Ana")
    b = _book(client, cacao["id"], "2027-04-06T12:00:00-06:00", "5510000002", "Beto")
    released = _book(client, cacao["id"], "2027-04-06T18:00:00+00:00", "5510000003", "Ceci")
    client.post(f"/bookings/{released['id']}/release", headers=_admin(), json={})

    sessions = _roster(client, "2027-04-06", cacao["id"])
    assert len(sessions) == 1
    session = sessions[0]
    assert session["service_name"] == cacao["name"]
    assert session["max_capacity"] == cacao["max_capacity"]
    assert session["occupied_count"] == 2
    assert session["attended_count"] == 0
    ids = {att["booking_id"] for att in session["attendees"]}
    assert ids == {a["id"], b["id"]}  # released booking is not on the roster
    assert all(att["attended"] is False for att in session["attendees"])


def test_roster_excludes_individual_services(client):
    svc = client.get("/services/atencion-psicologica-individual").json()
    _book(client, svc["id"], "2027-04-07T16:00:00Z", "5510000004")
    assert _roster(client, "2027-04-07") == []


# --- POST /rosters/quick-checkin: existing bookings ------------------------------------


def test_checkin_with_cash_marks_attended_and_acknowledges_payment(client, cacao):
    booking = _book(client, cacao["id"], "2027-04-13T18:00:00Z", "5510000010")
    res = client.post(
        "/rosters/quick-checkin",
        headers=_admin(),
        json={"booking_id": booking["id"], "paid_cash": True},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["walk_in"] is False
    assert body["attendee"]["attended"] is True
    assert body["attendee"]["booking_status"] == "COMPLETED"
    assert body["attendee"]["payment_status"] == "ACKNOWLEDGED"
    assert body["payment_id"] is not None

    with Session(get_engine()) as s:
        payment = s.get(Payment, body["payment_id"])
        assert payment is not None
        assert payment.payment_method == "CASH"
        assert payment.amount_mxn == cacao["price_mxn"]
        assert payment.acknowledged_by == "asistente@armoniadelser.mx"
        audit = s.exec(select(AdminAuditLog).where(AdminAuditLog.entity_id == booking["id"])).all()
        assert [a.action_type for a in audit] == ["ROSTER_CHECKIN"]

    assert booking["id"] not in _queue_ids(client)
    assert _roster(client, "2027-04-13", cacao["id"])[0]["attended_count"] == 1


def test_checkin_twice_is_conflict(client, cacao):
    booking = _book(client, cacao["id"], "2027-04-14T18:00:00Z", "5510000011")
    payload = {"booking_id": booking["id"]}
    assert client.post("/rosters/quick-checkin", headers=_admin(), json=payload).status_code == 200
    assert client.post("/rosters/quick-checkin", headers=_admin(), json=payload).status_code == 409


def test_unpaid_checkin_becomes_traceable_delayed_payment(client, cacao):
    booking = _book(client, cacao["id"], "2027-04-15T18:00:00Z", "5510000012")
    res = client.post(
        "/rosters/quick-checkin", headers=_admin(), json={"booking_id": booking["id"]}
    )
    assert res.status_code == 200
    attendee = res.json()["attendee"]
    assert attendee["booking_status"] == "COMPLETED"
    assert attendee["payment_arrangement"] == "DELAYED_ALLOWED"
    assert attendee["payment_status"] == "AWAITING_ACKNOWLEDGMENT"
    assert res.json()["payment_id"] is None
    # Attending without paying must never silently disappear from the receivables queue
    assert booking["id"] in _queue_ids(client)


def test_checkin_corrects_a_mistaken_no_show(client, cacao):
    booking = _book(client, cacao["id"], "2027-04-16T18:00:00Z", "5510000013")
    client.post(
        f"/bookings/{booking['id']}/status",
        headers=_admin(),
        json={"booking_status": "NO_SHOW"},
    )
    res = client.post(
        "/rosters/quick-checkin",
        headers=_admin(),
        json={"booking_id": booking["id"], "paid_cash": True},
    )
    assert res.status_code == 200
    assert res.json()["attendee"]["attended"] is True


@pytest.mark.parametrize("status_path", ["release", "status"])
def test_checkin_rejects_released_or_cancelled_bookings(client, cacao, status_path):
    booking = _book(client, cacao["id"], "2027-04-17T18:00:00Z", f"55100000{20 + len(status_path)}")
    if status_path == "release":
        client.post(f"/bookings/{booking['id']}/release", headers=_admin(), json={})
    else:
        client.post(
            f"/bookings/{booking['id']}/status",
            headers=_admin(),
            json={"booking_status": "CANCELLED"},
        )
    res = client.post(
        "/rosters/quick-checkin", headers=_admin(), json={"booking_id": booking["id"]}
    )
    assert res.status_code == 400


def test_checkin_rejects_individual_bookings(client):
    svc = client.get("/services/atencion-psicologica-individual").json()
    booking = _book(client, svc["id"], "2027-04-19T16:00:00Z", "5510000030")
    res = client.post(
        "/rosters/quick-checkin", headers=_admin(), json={"booking_id": booking["id"]}
    )
    assert res.status_code == 400


def test_checkin_unknown_booking_is_404(client):
    res = client.post("/rosters/quick-checkin", headers=_admin(), json={"booking_id": "nope"})
    assert res.status_code == 404


# --- POST /rosters/quick-checkin: walk-ins ---------------------------------------------


def _walk_in(service_id: str, scheduled_at: str, phone: str, **extra) -> dict:
    return {
        "service_id": service_id,
        "scheduled_at": scheduled_at,
        "client_name": "Llegó sin reservar",
        "client_phone": phone,
        **extra,
    }


def test_paid_walk_in_creates_attended_acknowledged_booking(client, cacao):
    res = client.post(
        "/rosters/quick-checkin",
        headers=_admin(),
        json=_walk_in(cacao["id"], "2027-04-20T18:00:00Z", "5510000040", paid_cash=True),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["walk_in"] is True
    assert body["attendee"]["booking_status"] == "COMPLETED"
    assert body["attendee"]["payment_status"] == "ACKNOWLEDGED"
    assert body["attendee"]["booking_code"].startswith("ADS-")
    assert body["payment_id"] is not None

    session = _roster(client, "2027-04-20", cacao["id"])[0]
    assert [a["booking_id"] for a in session["attendees"]] == [body["attendee"]["booking_id"]]
    assert session["attended_count"] == 1


def test_unpaid_walk_in_is_visible_in_followup_queue(client, cacao):
    res = client.post(
        "/rosters/quick-checkin",
        headers=_admin(),
        json=_walk_in(cacao["id"], "2027-04-21T18:00:00Z", "5510000041"),
    )
    assert res.status_code == 200
    attendee = res.json()["attendee"]
    assert attendee["payment_arrangement"] == "DELAYED_ALLOWED"
    assert attendee["booking_id"] in _queue_ids(client)


def test_walk_in_reuses_existing_client_by_phone(client, cacao):
    existing = _book(client, cacao["id"], "2027-04-22T18:00:00Z", "5510000042")
    res = client.post(
        "/rosters/quick-checkin",
        headers=_admin(),
        json=_walk_in(cacao["id"], "2027-04-29T18:00:00Z", "5510000042"),
    )
    assert res.json()["attendee"]["client_id"] == existing["client_id"]


def test_walk_in_respects_capacity(client, tiny_workshop):
    when = "2027-04-23T18:00:00Z"
    first = client.post(
        "/rosters/quick-checkin",
        headers=_admin(),
        json=_walk_in(tiny_workshop["id"], when, "5510000050"),
    )
    assert first.status_code == 200
    second = client.post(
        "/rosters/quick-checkin",
        headers=_admin(),
        json=_walk_in(tiny_workshop["id"], when, "5510000051"),
    )
    assert second.status_code == 409


def test_walk_in_rejects_individual_service(client):
    svc = client.get("/services/atencion-psicologica-individual").json()
    res = client.post(
        "/rosters/quick-checkin",
        headers=_admin(),
        json=_walk_in(svc["id"], "2027-04-26T16:00:00Z", "5510000060"),
    )
    assert res.status_code == 400


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"paid_cash": True},
        {"booking_id": "x", "service_id": "y", "scheduled_at": "2027-04-26T16:00:00Z"},
        {"service_id": "y", "scheduled_at": "2027-04-26T16:00:00Z"},  # walk-in without client
    ],
)
def test_checkin_requires_exactly_one_mode(client, payload):
    assert client.post("/rosters/quick-checkin", headers=_admin(), json=payload).status_code == 422


# --- ADR-0006: proxy users keep FK integrity on roster writes --------------------------


def test_proxy_user_walk_in_checkin_preserves_foreign_keys(client, cacao, monkeypatch):
    monkeypatch.setattr(settings, "auth_provider", AuthProvider.PROXY_HEADERS)
    proxy = {
        "Remote-Email": "puerta@homelab.lan",
        "Remote-Name": "Recepcion",
        "Remote-Groups": "armonia-assistant",
    }
    res = client.post(
        "/rosters/quick-checkin",
        headers=proxy,
        json=_walk_in(cacao["id"], "2027-04-27T18:00:00Z", "5510000070", paid_cash=True),
    )
    assert res.status_code == 200, res.text
    with Session(get_engine()) as s:
        payment = s.get(Payment, res.json()["payment_id"])
        assert payment is not None
        assert payment.acknowledged_by == "puerta@homelab.lan"
