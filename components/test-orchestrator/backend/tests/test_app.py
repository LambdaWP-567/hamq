import pytest
from fastapi.testclient import TestClient
from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_version(client):
    r = client.get("/api/version")
    assert r.status_code == 200
    assert "version" in r.json()


def test_login_ok(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_login_bad(client):
    r = client.post("/api/auth/login", json={"username": "wrong", "password": "wrong"})
    assert r.status_code == 401


def test_status_requires_auth(client):
    r = client.get("/api/status")
    assert r.status_code == 401


def test_status_with_token(client):
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin"})
    token = r.json()["access_token"]
    r2 = client.get("/api/status", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    data = r2.json()
    assert "running" in data
    assert "sent_counter" in data
    assert "missing_count" in data
