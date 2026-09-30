import pytest


def test_health_responde_ok(client):
    res = client.get("/health/")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "commit" in data


def test_health_no_se_cachea(client):
    res = client.get("/health/")
    assert "no-cache" in res.headers.get("Cache-Control", "")


def test_health_rechaza_post(client):
    assert client.post("/health/").status_code == 405


@pytest.mark.django_db
def test_ready_con_bd(client):
    res = client.get("/ready/")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
