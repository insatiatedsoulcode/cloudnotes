"""
F-04 User Workspace Separation tests.

Covers:
  - Private notes visible only to owner and admin (F-04a, F-04b)
  - Public notes visible to all authenticated users
  - Admin list endpoint returns all notes regardless of visibility
  - Admin can read private notes belonging to any user
  - visibility field present in all responses
  - visibility can be set on create and changed on update
"""

from tests.conftest import make_note


def _make_public(client, headers, title="Public note", content="body"):
    res = client.post("/api/notes/",
                      json={"title": title, "content": content, "visibility": "public"},
                      headers=headers)
    assert res.status_code == 201
    return res.json()


class TestVisibilityDefault:
    def test_new_note_is_private_by_default(self, client, auth_headers):
        note = make_note(client, auth_headers)
        assert note["visibility"] == "private"

    def test_can_create_public_note(self, client, auth_headers):
        note = _make_public(client, auth_headers)
        assert note["visibility"] == "public"

    def test_can_set_visibility_on_create(self, client, auth_headers):
        res = client.post("/api/notes/",
                          json={"title": "T", "content": "C", "visibility": "private"},
                          headers=auth_headers)
        assert res.status_code == 201
        assert res.json()["visibility"] == "private"

    def test_invalid_visibility_returns_422(self, client, auth_headers):
        res = client.post("/api/notes/",
                          json={"title": "T", "content": "C", "visibility": "secret"},
                          headers=auth_headers)
        assert res.status_code == 422

    def test_can_update_visibility_to_public(self, client, auth_headers):
        note = make_note(client, auth_headers)
        res = client.put(f"/api/notes/{note['id']}",
                         json={"visibility": "public"},
                         headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["visibility"] == "public"

    def test_can_update_visibility_back_to_private(self, client, auth_headers):
        note = _make_public(client, auth_headers)
        res = client.put(f"/api/notes/{note['id']}",
                         json={"visibility": "private"},
                         headers=auth_headers)
        assert res.status_code == 200
        assert res.json()["visibility"] == "private"


class TestScopedList:
    def test_user_sees_own_private_notes_in_list(self, client, auth_headers):
        make_note(client, auth_headers, title="Mine")
        res = client.get("/api/notes/", headers=auth_headers)
        titles = [n["title"] for n in res.json()]
        assert "Mine" in titles

    def test_user_does_not_see_others_private_notes_in_list(self, client, auth_headers, second_user_headers):
        make_note(client, auth_headers, title="User1 private")
        res = client.get("/api/notes/", headers=second_user_headers)
        assert len(res.json()) == 0

    def test_user_sees_others_public_notes_in_list(self, client, auth_headers, second_user_headers):
        _make_public(client, auth_headers, title="User1 public")
        res = client.get("/api/notes/", headers=second_user_headers)
        titles = [n["title"] for n in res.json()]
        assert "User1 public" in titles

    def test_list_mixes_own_private_and_others_public(self, client, auth_headers, second_user_headers):
        make_note(client, auth_headers, title="User1 private")
        _make_public(client, auth_headers, title="User1 public")
        make_note(client, second_user_headers, title="User2 private")

        # User2 sees: their own private + user1's public
        res = client.get("/api/notes/", headers=second_user_headers)
        titles = {n["title"] for n in res.json()}
        assert "User2 private" in titles
        assert "User1 public" in titles
        assert "User1 private" not in titles


class TestVisibilityOnGet:
    def test_owner_can_get_private_note(self, client, auth_headers):
        note = make_note(client, auth_headers)
        res = client.get(f"/api/notes/{note['id']}", headers=auth_headers)
        assert res.status_code == 200

    def test_other_user_cannot_get_private_note(self, client, auth_headers, second_user_headers):
        note = make_note(client, auth_headers)
        res = client.get(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 403

    def test_other_user_can_get_public_note(self, client, auth_headers, second_user_headers):
        note = _make_public(client, auth_headers)
        res = client.get(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 200

    def test_403_does_not_leak_private_note_content(self, client, auth_headers, second_user_headers):
        note = make_note(client, auth_headers, title="Secret", content="Top secret content")
        res = client.get(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 403
        assert "Secret" not in res.text
        assert "Top secret content" not in res.text

    def test_private_to_public_change_makes_note_accessible(self, client, auth_headers, second_user_headers):
        note = make_note(client, auth_headers)
        # Initially private — other user cannot see it
        assert client.get(f"/api/notes/{note['id']}", headers=second_user_headers).status_code == 403

        # Owner makes it public
        client.put(f"/api/notes/{note['id']}",
                   json={"visibility": "public"},
                   headers=auth_headers)

        # Now accessible
        assert client.get(f"/api/notes/{note['id']}", headers=second_user_headers).status_code == 200


class TestAdminAccess:
    def test_admin_list_returns_all_notes(self, client, auth_headers, second_user_headers, admin_headers):
        make_note(client, auth_headers, title="User1 private")
        _make_public(client, second_user_headers, title="User2 public")
        res = client.get("/api/admin/notes", headers=admin_headers)
        assert res.status_code == 200
        titles = {n["title"] for n in res.json()}
        assert "User1 private" in titles
        assert "User2 public" in titles

    def test_admin_can_read_any_private_note(self, client, auth_headers, admin_headers):
        note = make_note(client, auth_headers, title="Private")
        res = client.get(f"/api/notes/{note['id']}", headers=admin_headers)
        assert res.status_code == 200

    def test_non_admin_cannot_access_admin_list(self, client, auth_headers):
        res = client.get("/api/admin/notes", headers=auth_headers)
        assert res.status_code == 403

    def test_unauthenticated_cannot_access_admin_list(self, client):
        res = client.get("/api/admin/notes")
        assert res.status_code == 401
