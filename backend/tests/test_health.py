"""Health endpoint contract test."""


def test_health(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "app": "archiviator", "version": "0.1.0"}
