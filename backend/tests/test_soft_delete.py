"""
F-11: Soft Delete tests.

- DELETE sets deleted_at; the note is not physically removed.
- Deleted notes are excluded from GET /notes/, GET /notes/{id}, PUT /notes/{id}.
- Admin trash endpoint returns only deleted notes.
- Admin restore endpoint undeletes a note.
- Share-link access is blocked for deleted notes.
- Attachment operations are blocked for deleted notes.
"""

import pytest
from tests.conftest import make_note


# ── Core soft-delete behaviour ────────────────────────────────────────────────

def test_delete_returns_204(client, auth_headers):
    note = make_note(client, auth_headers)
    res = client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    assert res.status_code == 204


def test_deleted_note_absent_from_list(client, auth_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.get("/api/notes/", headers=auth_headers)
    assert res.status_code == 200
    ids = [n["id"] for n in res.json()]
    assert note["id"] not in ids


def test_deleted_note_returns_404_on_get(client, auth_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.get(f"/api/notes/{note['id']}", headers=auth_headers)
    assert res.status_code == 404


def test_deleted_note_returns_404_on_update(client, auth_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.put(f"/api/notes/{note['id']}", json={"title": "new"}, headers=auth_headers)
    assert res.status_code == 404


def test_delete_already_deleted_returns_404(client, auth_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    assert res.status_code == 404


def test_live_notes_still_accessible_after_other_deleted(client, auth_headers):
    kept = make_note(client, auth_headers, title="keep")
    deleted = make_note(client, auth_headers, title="gone")
    client.delete(f"/api/notes/{deleted['id']}", headers=auth_headers)
    res = client.get(f"/api/notes/{kept['id']}", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["id"] == kept["id"]


# ── Admin trash / restore ─────────────────────────────────────────────────────

def test_admin_trash_returns_deleted_notes(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.get("/api/admin/notes/trash", headers=admin_headers)
    assert res.status_code == 200
    ids = [n["id"] for n in res.json()]
    assert note["id"] in ids


def test_admin_trash_excludes_live_notes(client, auth_headers, admin_headers):
    live = make_note(client, auth_headers, title="live")
    deleted = make_note(client, auth_headers, title="deleted")
    client.delete(f"/api/notes/{deleted['id']}", headers=auth_headers)
    res = client.get("/api/admin/notes/trash", headers=admin_headers)
    ids = [n["id"] for n in res.json()]
    assert live["id"] not in ids
    assert deleted["id"] in ids


def test_admin_restore_undeletes_note(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.post(f"/api/admin/notes/{note['id']}/restore", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["deleted_at"] is None
    # Note should now appear in the owner's list
    list_res = client.get("/api/notes/", headers=auth_headers)
    ids = [n["id"] for n in list_res.json()]
    assert note["id"] in ids


def test_admin_restore_nonexistent_returns_404(client, admin_headers):
    res = client.post("/api/admin/notes/99999/restore", headers=admin_headers)
    assert res.status_code == 404


def test_admin_restore_live_note_returns_404(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    res = client.post(f"/api/admin/notes/{note['id']}/restore", headers=admin_headers)
    assert res.status_code == 404


def test_admin_list_notes_excludes_deleted(client, auth_headers, admin_headers):
    live = make_note(client, auth_headers, title="live")
    deleted = make_note(client, auth_headers, title="deleted")
    client.delete(f"/api/notes/{deleted['id']}", headers=auth_headers)
    res = client.get("/api/admin/notes", headers=admin_headers)
    ids = [n["id"] for n in res.json()]
    assert live["id"] in ids
    assert deleted["id"] not in ids


# ── Sharing blocked for deleted notes ─────────────────────────────────────────

def test_share_link_on_deleted_note_returns_404(client, auth_headers):
    note = make_note(client, auth_headers)
    # Create link while live
    link_res = client.post(f"/api/notes/{note['id']}/share-link", headers=auth_headers)
    assert link_res.status_code == 201
    token = link_res.json()["token"]

    # Delete the note
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)

    # Token access should now 404
    res = client.get(f"/api/notes/shared/{token}")
    assert res.status_code == 404


def test_share_with_user_on_deleted_note_returns_404(client, auth_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    # Register a target user (no need to log in as them)
    client.post("/api/auth/register", json={"email": "other@test.com", "password": "Password123"})
    res = client.post(
        f"/api/notes/{note['id']}/share",
        json={"email": "other@test.com", "permission": "view"},
        headers=auth_headers,
    )
    assert res.status_code == 404


# ── Attachments blocked for deleted notes ─────────────────────────────────────

def test_upload_on_deleted_note_returns_404(client, auth_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.post(
        f"/api/notes/{note['id']}/attachments",
        files={"file": ("test.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert res.status_code == 404


def test_list_attachments_on_deleted_note_returns_404(client, auth_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.get(f"/api/notes/{note['id']}/attachments", headers=auth_headers)
    assert res.status_code == 404
