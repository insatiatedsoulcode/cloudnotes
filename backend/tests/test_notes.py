"""
Notes CRUD tests — TDD layer.

Covers:
  - All endpoints require authentication
  - Create: sets author and owner_id from JWT, not from request body
  - List: returns notes newest-first
  - Get: 404 for missing notes
  - Update / Delete: owner can modify their own notes
  - RBAC: user cannot modify another user's notes (403)
  - RBAC: admin can modify any note
"""

import pytest
from tests.conftest import make_note


# ── Authentication guard (every endpoint) ────────────────────────────────────

class TestRequiresAuth:

    def test_list_without_token_returns_401(self, client):
        assert client.get("/api/notes/").status_code == 401

    def test_create_without_token_returns_401(self, client):
        assert client.post("/api/notes/",
                           json={"title": "T", "content": "C"}).status_code == 401

    def test_get_without_token_returns_401(self, client):
        assert client.get("/api/notes/1").status_code == 401

    def test_update_without_token_returns_401(self, client):
        assert client.put("/api/notes/1",
                          json={"title": "X"}).status_code == 401

    def test_delete_without_token_returns_401(self, client):
        assert client.delete("/api/notes/1").status_code == 401


# ── List ──────────────────────────────────────────────────────────────────────

class TestListNotes:

    def test_empty_list_on_fresh_db(self, client, auth_headers):
        res = client.get("/api/notes/", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_returns_notes_after_creation(self, client, auth_headers):
        make_note(client, auth_headers, title="A")
        make_note(client, auth_headers, title="B")
        res = client.get("/api/notes/", headers=auth_headers)
        assert len(res.json()) == 2

    def test_returns_newest_first(self, client, auth_headers):
        make_note(client, auth_headers, title="First")
        make_note(client, auth_headers, title="Second")
        titles = [n["title"] for n in client.get("/api/notes/", headers=auth_headers).json()]
        assert titles == ["Second", "First"]

    def test_user_sees_own_private_notes(self, client, auth_headers):
        """Owner always sees their own private notes."""
        make_note(client, auth_headers, title="My private note")
        res = client.get("/api/notes/", headers=auth_headers)
        assert len(res.json()) == 1

    def test_private_notes_not_visible_to_other_users(self, client, auth_headers, second_user_headers):
        """Private notes (default) must NOT appear in another user's list."""
        make_note(client, auth_headers, title="User1 private note")
        res = client.get("/api/notes/", headers=second_user_headers)
        assert len(res.json()) == 0


# ── Create ────────────────────────────────────────────────────────────────────

class TestCreateNote:

    def test_returns_201_with_full_note(self, client, auth_headers):
        res = client.post("/api/notes/",
                          json={"title": "My note", "content": "Hello"},
                          headers=auth_headers)
        assert res.status_code == 201
        body = res.json()
        assert body["title"] == "My note"
        assert body["content"] == "Hello"
        assert "id" in body
        assert "created_at" in body
        assert "updated_at" in body

    def test_author_set_from_jwt_not_request_body(self, client, auth_headers):
        """SSDLC: client cannot spoof the author field."""
        res = client.post("/api/notes/",
                          json={"title": "T", "content": "C"},
                          headers=auth_headers)
        assert res.json()["author"] == "user@test.com"

    def test_owner_id_set_from_jwt(self, client, auth_headers, registered_user):
        res = client.post("/api/notes/",
                          json={"title": "T", "content": "C"},
                          headers=auth_headers)
        assert res.json()["owner_id"] == registered_user["id"]

    def test_missing_title_returns_422(self, client, auth_headers):
        res = client.post("/api/notes/", json={"content": "C"}, headers=auth_headers)
        assert res.status_code == 422

    def test_missing_content_returns_422(self, client, auth_headers):
        res = client.post("/api/notes/", json={"title": "T"}, headers=auth_headers)
        assert res.status_code == 422

    def test_empty_title_returns_422(self, client, auth_headers):
        res = client.post("/api/notes/", json={"title": "", "content": "C"}, headers=auth_headers)
        assert res.status_code == 422


# ── Get ───────────────────────────────────────────────────────────────────────

class TestGetNote:

    def test_get_existing_note(self, client, auth_headers):
        note = make_note(client, auth_headers)
        res = client.get(f"/api/notes/{note['id']}", headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["id"] == note["id"]

    def test_get_nonexistent_note_returns_404(self, client, auth_headers):
        res = client.get("/api/notes/9999", headers=auth_headers)
        assert res.status_code == 404

    def test_owner_can_get_own_private_note(self, client, auth_headers):
        note = make_note(client, auth_headers)
        res = client.get(f"/api/notes/{note['id']}", headers=auth_headers)
        assert res.status_code == 200

    def test_other_user_cannot_get_private_note(self, client, auth_headers, second_user_headers):
        note = make_note(client, auth_headers)  # private by default
        res = client.get(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 403


# ── Update ────────────────────────────────────────────────────────────────────

class TestUpdateNote:

    def test_owner_can_update_title(self, client, auth_headers):
        note = make_note(client, auth_headers)
        res = client.put(f"/api/notes/{note['id']}",
                         json={"title": "New title"},
                         headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["title"] == "New title"

    def test_owner_can_update_content(self, client, auth_headers):
        note = make_note(client, auth_headers)
        res = client.put(f"/api/notes/{note['id']}",
                         json={"content": "New content"},
                         headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["content"] == "New content"

    def test_updated_at_changes_after_update(self, client, auth_headers):
        note = make_note(client, auth_headers)
        res = client.put(f"/api/notes/{note['id']}",
                         json={"title": "Changed"},
                         headers=auth_headers)
        assert res.json()["updated_at"] >= note["updated_at"]

    def test_update_nonexistent_note_returns_404(self, client, auth_headers):
        res = client.put("/api/notes/9999",
                         json={"title": "X"},
                         headers=auth_headers)
        assert res.status_code == 404

    def test_empty_body_is_a_no_op(self, client, auth_headers):
        note = make_note(client, auth_headers, title="Original")
        res = client.put(f"/api/notes/{note['id']}", json={}, headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["title"] == "Original"


# ── Delete ────────────────────────────────────────────────────────────────────

class TestDeleteNote:

    def test_owner_can_delete_own_note(self, client, auth_headers):
        note = make_note(client, auth_headers)
        res = client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
        assert res.status_code == 204

    def test_deleted_note_is_gone(self, client, auth_headers):
        note = make_note(client, auth_headers)
        client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
        res = client.get(f"/api/notes/{note['id']}", headers=auth_headers)
        assert res.status_code == 404

    def test_delete_nonexistent_note_returns_404(self, client, auth_headers):
        res = client.delete("/api/notes/9999", headers=auth_headers)
        assert res.status_code == 404


# ── RBAC ─────────────────────────────────────────────────────────────────────

class TestOwnershipAndRBAC:

    def test_user_cannot_update_another_users_note(self, client, auth_headers, second_user_headers):
        note = make_note(client, auth_headers)
        res = client.put(f"/api/notes/{note['id']}",
                         json={"title": "Hijacked"},
                         headers=second_user_headers)
        assert res.status_code == 403

    def test_user_cannot_delete_another_users_note(self, client, auth_headers, second_user_headers):
        note = make_note(client, auth_headers)
        res = client.delete(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 403

    def test_note_title_unchanged_after_forbidden_update(self, client, auth_headers, second_user_headers):
        note = make_note(client, auth_headers, title="Original")
        client.put(f"/api/notes/{note['id']}",
                   json={"title": "Hijacked"},
                   headers=second_user_headers)
        fetched = client.get(f"/api/notes/{note['id']}", headers=auth_headers).json()
        assert fetched["title"] == "Original"

    def test_admin_can_update_any_note(self, client, auth_headers, admin_headers):
        note = make_note(client, auth_headers)
        res = client.put(f"/api/notes/{note['id']}",
                         json={"title": "Admin edit"},
                         headers=admin_headers)
        assert res.status_code == 200
        assert res.json()["title"] == "Admin edit"

    def test_admin_can_delete_any_note(self, client, auth_headers, admin_headers):
        note = make_note(client, auth_headers)
        res = client.delete(f"/api/notes/{note['id']}", headers=admin_headers)
        assert res.status_code == 204
