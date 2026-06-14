"""
F-16: API Versioning tests.

- /api/v1/ routes are the primary versioned paths.
- /api/ routes remain as backwards-compatible aliases.
- Accept-Version: v1 header is accepted.
- Unknown Accept-Version values are rejected with 400.
"""

import pytest
from tests.conftest import make_note


# ── /api/v1/ primary routes ───────────────────────────────────────────────────

def test_health_check_accessible(client):
    assert client.get("/health").status_code == 200


def test_v1_auth_register_works(client):
    res = client.post("/api/v1/auth/register", json={
        "email": "v1user@test.com", "password": "Password123",
    })
    assert res.status_code == 201


def test_v1_notes_list_requires_auth(client):
    res = client.get("/api/v1/notes/")
    assert res.status_code == 401


def test_v1_notes_crud(client, registered_user, auth_headers):
    # Create via v1
    res = client.post("/api/v1/notes/",
                      json={"title": "v1 note", "content": "body"},
                      headers=auth_headers)
    assert res.status_code == 201
    note_id = res.json()["id"]

    # Read via v1
    res = client.get(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["title"] == "v1 note"

    # Update via v1
    res = client.put(f"/api/v1/notes/{note_id}",
                     json={"title": "updated"}, headers=auth_headers)
    assert res.status_code == 200

    # Delete via v1
    res = client.delete(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert res.status_code == 204


def test_v1_tags_endpoint_works(client, auth_headers):
    res = client.get("/api/v1/tags/", headers=auth_headers)
    assert res.status_code == 200


def test_v1_admin_endpoint_works(client, admin_headers):
    res = client.get("/api/v1/admin/stats", headers=admin_headers)
    assert res.status_code == 200


# ── /api/ backwards-compat alias ─────────────────────────────────────────────

def test_legacy_api_prefix_still_works(client, auth_headers):
    res = client.get("/api/notes/", headers=auth_headers)
    assert res.status_code == 200


def test_legacy_and_v1_return_same_data(client, auth_headers):
    note = make_note(client, auth_headers, title="compat")
    v1 = client.get(f"/api/v1/notes/{note['id']}", headers=auth_headers).json()
    legacy = client.get(f"/api/notes/{note['id']}", headers=auth_headers).json()
    assert v1["id"] == legacy["id"]
    assert v1["title"] == legacy["title"]


# ── Accept-Version header ─────────────────────────────────────────────────────

def test_accept_version_v1_header_is_accepted(client, auth_headers):
    res = client.get("/api/notes/", headers={**auth_headers, "Accept-Version": "v1"})
    assert res.status_code == 200


def test_accept_version_unknown_returns_400(client):
    res = client.get("/api/notes/", headers={"Accept-Version": "v99"})
    assert res.status_code == 400
    assert "v99" in res.json()["detail"]


def test_accept_version_missing_is_fine(client, auth_headers):
    res = client.get("/api/notes/", headers=auth_headers)
    assert res.status_code == 200


def test_accept_version_v2_returns_400(client):
    res = client.get("/health", headers={"Accept-Version": "v2"})
    assert res.status_code == 400
