from __future__ import annotations


def test_list_seeded_services(client):
    response = client.get("/services")
    assert response.status_code == 200
    services = response.json()
    assert len(services) >= 9

    slugs = [s["slug"] for s in services]
    assert "circulo-cacao-presencial" in slugs
    assert "atencion-psicologica-individual" in slugs
    assert "constelaciones-familiares-online" in slugs


def test_get_service_by_slug(client):
    response = client.get("/services/circulo-cacao-presencial")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Círculo de Cacao (Presencial)"
    assert data["price_mxn"] == 350
    assert data["service_type"] == "GROUP"
