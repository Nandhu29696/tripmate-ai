"""Serving the built React app."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import spa
from app import app
from tests.conftest import FAKE_DIST


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.parametrize("path", ["/", "/login", "/forgot", "/reset", "/account", "/trips/trip_abc", "/some/deep/client/route"])
def test_client_side_routes_get_the_app_shell(client, path):
    response = client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert 'id="root"' in response.text
    assert response.headers["cache-control"] == "no-cache"  # a new deploy is picked up immediately


def test_hashed_assets_are_cached_for_a_year(client):
    response = client.get("/assets/app-abc123.js")
    assert response.status_code == 200
    assert response.text == "console.log('app');"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_missing_asset_is_a_404_not_the_html_shell(client):
    response = client.get("/assets/does-not-exist.js")
    assert response.status_code == 404
    assert "root" not in response.text


def test_root_files_such_as_the_favicon_are_served(client):
    response = client.get("/favicon.svg")
    assert response.status_code == 200
    assert "svg" in response.text


@pytest.mark.parametrize("path", ["/api/nope", "/api/travel/unknown/extra", "/auth/nope", "/api"])
def test_unknown_api_paths_stay_json_404s(client, path):
    response = client.get(path)
    assert response.status_code == 404
    assert response.json() == {"success": False, "error": "Not found."}


def test_real_routes_are_never_shadowed(client):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/api/session").json()["authenticated"] is False
    assert client.get("/auth/verify", follow_redirects=False).status_code == 303
    assert client.get("/auth/google/login", follow_redirects=False).status_code == 303


@pytest.mark.parametrize("path", ["/../config.py", "/..%2fconfig.py", "/%2e%2e/config.py", "/assets/../../config.py", "//etc/passwd"])
def test_path_traversal_cannot_read_files_outside_the_build(client, path):
    response = client.get(path)
    assert "BASE_DIR" not in response.text and "get_session_secret" not in response.text
    assert response.status_code in {200, 404}  # the shell or a 404, never a source file


def test_security_headers_apply_to_the_shell_too(client):
    headers = client.get("/login").headers
    assert "script-src 'self'" in headers["content-security-policy"]
    assert headers["x-frame-options"] == "DENY"
    assert headers["x-content-type-options"] == "nosniff"


def test_a_missing_build_gives_a_clear_placeholder_not_a_crash(tmp_path):
    bare = FastAPI()
    spa.mount_spa(bare, tmp_path / "no-build-here")
    response = TestClient(bare).get("/login")
    assert response.status_code == 503
    assert "not been built" in response.text


def test_the_test_build_is_what_is_being_served():
    assert (FAKE_DIST / "index.html").is_file()
