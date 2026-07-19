"""SPA static serving: non-/api routes must fall back to index.html (QR deep links depend on it)."""

from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"


@pytest.mark.skipif(not DIST.exists(), reason="frontend not built")
def test_spa_fallback_serves_index_for_client_routes(client):
    for route in ("/login", "/a/A-0001", "/some/deep/route"):
        resp = client.get(route)
        assert resp.status_code == 200, route
        assert "text/html" in resp.headers["content-type"], route


@pytest.mark.skipif(not DIST.exists(), reason="frontend not built")
def test_api_unknown_route_still_404s_as_json(client):
    resp = client.get("/api/v1/definitely-not-a-real-endpoint")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
