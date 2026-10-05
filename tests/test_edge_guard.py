from app.config import settings


def test_token_set_enforcement_on_header_present(client, monkeypatch):
    monkeypatch.setattr(settings, "edge_token", "secret-token")
    monkeypatch.setattr(settings, "edge_enforce", True)
    resp = client.get("/datasets", headers={"x-edge-token": "secret-token"})
    assert resp.status_code != 403


def test_token_set_enforcement_on_no_header(client, monkeypatch):
    monkeypatch.setattr(settings, "edge_token", "secret-token")
    monkeypatch.setattr(settings, "edge_enforce", True)
    resp = client.get("/datasets")
    assert resp.status_code == 403
    assert resp.text == "Forbidden"


def test_token_set_enforcement_on_wrong_header(client, monkeypatch):
    monkeypatch.setattr(settings, "edge_token", "secret-token")
    monkeypatch.setattr(settings, "edge_enforce", True)
    resp = client.get("/datasets", headers={"x-edge-token": "wrong-token"})
    assert resp.status_code == 403


def test_token_set_enforcement_on_health_no_header(client, monkeypatch):
    monkeypatch.setattr(settings, "edge_token", "secret-token")
    monkeypatch.setattr(settings, "edge_enforce", True)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json().get("edge") is False


def test_token_set_enforcement_on_health_right_header(client, monkeypatch):
    monkeypatch.setattr(settings, "edge_token", "secret-token")
    monkeypatch.setattr(settings, "edge_enforce", True)
    resp = client.get("/health", headers={"x-edge-token": "secret-token"})
    assert resp.status_code == 200
    assert resp.json().get("edge") is True


def test_token_set_enforcement_off_no_header(client, monkeypatch):
    monkeypatch.setattr(settings, "edge_token", "secret-token")
    monkeypatch.setattr(settings, "edge_enforce", False)
    resp = client.get("/datasets")
    assert resp.status_code != 403


def test_no_token_configured_enforcement_on_no_header(client, monkeypatch):
    monkeypatch.setattr(settings, "edge_token", None)
    monkeypatch.setattr(settings, "edge_enforce", True)
    resp = client.get("/datasets")
    assert resp.status_code != 403
