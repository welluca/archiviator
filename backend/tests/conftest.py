"""Test fixtures. ARCHIVIATOR_DATA_DIR is pointed at a temp dir BEFORE any app import."""

import os
import tempfile

# Must happen before any 'app.*' import anywhere in the test session.
_TEST_DATA_DIR = tempfile.mkdtemp(prefix="archiviator-test-data-")
os.environ["ARCHIVIATOR_DATA_DIR"] = _TEST_DATA_DIR

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from app.config import get_settings
    from app.database import reset_engine
    from app.main import create_app

    # Belt and braces: make sure no cached settings/engine from a stray import survive.
    get_settings.cache_clear()
    reset_engine()
    assert str(get_settings().data_dir) == _TEST_DATA_DIR

    app = create_app()
    with TestClient(app) as c:  # lifespan runs migrations against the temp dir
        yield c

    reset_engine()


@pytest.fixture(scope="session")
def test_user(client):
    """A user created via the CLI function (schema already migrated by the app lifespan)."""
    from app.cli import create_user

    creds = {"username": "testuser", "password": "s3cret-test-pass"}
    create_user(creds["username"], creds["password"])
    return creds


@pytest.fixture()
def tokens(client, test_user):
    """A fresh login token pair."""
    resp = client.post(
        "/api/v1/auth/login",
        data={"username": test_user["username"], "password": test_user["password"]},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()
