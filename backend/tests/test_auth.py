"""Auth flow tests: login, me, refresh rotation, logout revocation, failures."""


def test_login_wrong_password(client, test_user):
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": test_user["username"], "password": "wrong-password"},
    )
    assert resp.status_code == 401


def test_login_unknown_user(client, test_user):
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": "nobody", "password": "whatever"},
    )
    assert resp.status_code == 401


def test_login_success_shape(tokens):
    assert set(tokens.keys()) == {"access_token", "refresh_token", "token_type"}
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]
    assert tokens["refresh_token"]


def test_me(client, tokens, test_user):
    resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == test_user["username"]
    assert isinstance(body["id"], int)


def test_me_requires_token(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_rejects_garbage_token(client):
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert resp.status_code == 401


def test_refresh_rotation(client, tokens):
    old_refresh = tokens["refresh_token"]

    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert resp.status_code == 200
    new_tokens = resp.json()
    assert set(new_tokens.keys()) == {"access_token", "refresh_token", "token_type"}
    assert new_tokens["token_type"] == "bearer"
    assert new_tokens["refresh_token"] != old_refresh

    # Old refresh token was rotated out — reuse must fail.
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert reuse.status_code == 401

    # New access token works.
    me = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_tokens['access_token']}"},
    )
    assert me.status_code == 200

    # New refresh token works too.
    resp2 = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": new_tokens["refresh_token"]}
    )
    assert resp2.status_code == 200


def test_refresh_invalid_token(client, test_user):
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "bogus-token"})
    assert resp.status_code == 401


def test_logout_revokes_refresh_token(client, tokens):
    refresh = tokens["refresh_token"]

    resp = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert resp.status_code == 204

    # Revoked token can no longer be used to refresh.
    reuse = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert reuse.status_code == 401

    # Logout is idempotent.
    again = client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
    assert again.status_code == 204
