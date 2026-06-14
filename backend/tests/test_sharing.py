"""F-09: Note Sharing — user-to-user shares and public share links."""

import pytest

from tests.conftest import make_note


# ── Helpers ───────────────────────────────────────────────────────────────────

def _share(client, headers, note_id, email, permission="view"):
    return client.post(
        f"/api/notes/{note_id}/share",
        json={"email": email, "permission": permission},
        headers=headers,
    )


def _create_link(client, headers, note_id):
    return client.post(f"/api/notes/{note_id}/share-link", headers=headers)


# ── F-09a: Share with specific users ─────────────────────────────────────────

class TestShareWithUser:
    def test_share_note_returns_share_response(self, client, auth_headers, registered_user, second_user_headers):
        note = make_note(client, auth_headers, title="My Note", content="content")
        res = _share(client, auth_headers, note["id"], "other@test.com")
        assert res.status_code == 201
        body = res.json()
        assert body["note_id"] == note["id"]
        assert body["permission"] == "view"

    def test_share_with_nonexistent_user_returns_404(self, client, auth_headers, registered_user):
        note = make_note(client, auth_headers)
        res = _share(client, auth_headers, note["id"], "nobody@example.com")
        assert res.status_code == 404

    def test_share_with_owner_returns_400(self, client, auth_headers, registered_user):
        note = make_note(client, auth_headers)
        res = _share(client, auth_headers, note["id"], "user@test.com")
        assert res.status_code == 400

    def test_reshare_updates_permission(self, client, auth_headers, registered_user, second_user_headers):
        note = make_note(client, auth_headers)
        _share(client, auth_headers, note["id"], "other@test.com", "view")
        res = _share(client, auth_headers, note["id"], "other@test.com", "edit")
        assert res.status_code == 201
        assert res.json()["permission"] == "edit"

    def test_non_owner_cannot_share_note(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers)
        res = _share(client, second_user_headers, note["id"], "other@test.com")
        assert res.status_code == 403

    def test_shared_note_appears_in_recipients_list(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers, title="Private shared note", content="content")
        _share(client, auth_headers, note["id"], "other@test.com")

        res = client.get("/api/notes/", headers=second_user_headers)
        assert res.status_code == 200
        ids = [n["id"] for n in res.json()]
        assert note["id"] in ids

    def test_shared_note_has_is_shared_with_me_true(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers, title="Shared note", content="content")
        _share(client, auth_headers, note["id"], "other@test.com")

        res = client.get("/api/notes/", headers=second_user_headers)
        shared = next(n for n in res.json() if n["id"] == note["id"])
        assert shared["is_shared_with_me"] is True

    def test_owned_note_has_is_shared_with_me_false(self, client, auth_headers, registered_user):
        note = make_note(client, auth_headers, title="My own note", content="content")

        res = client.get("/api/notes/", headers=auth_headers)
        own = next(n for n in res.json() if n["id"] == note["id"])
        assert own["is_shared_with_me"] is False

    def test_recipient_can_get_private_note_directly(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers, title="Private note", content="secret")
        _share(client, auth_headers, note["id"], "other@test.com")

        res = client.get(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 200

    def test_unshared_user_cannot_read_private_note(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers, title="Private note", content="secret")

        res = client.get(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 403

    def test_list_shares_returns_all_recipients(self, client, auth_headers, registered_user, second_user_headers):
        note = make_note(client, auth_headers)
        _share(client, auth_headers, note["id"], "other@test.com")

        res = client.get(f"/api/notes/{note['id']}/shares", headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()) == 1
        assert res.json()[0]["permission"] == "view"

    def test_non_owner_cannot_list_shares(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers)
        res = client.get(f"/api/notes/{note['id']}/shares", headers=second_user_headers)
        assert res.status_code == 403

    def test_revoke_share_removes_access(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers, title="Temp shared", content="content")
        _share(client, auth_headers, note["id"], "other@test.com")

        share_id = client.get(f"/api/notes/{note['id']}/shares", headers=auth_headers).json()[0]["id"]
        revoke_res = client.delete(f"/api/notes/{note['id']}/share/{share_id}", headers=auth_headers)
        assert revoke_res.status_code == 204

        # Note should no longer be in recipient's list
        list_res = client.get("/api/notes/", headers=second_user_headers)
        assert note["id"] not in [n["id"] for n in list_res.json()]

    def test_revoked_share_blocks_direct_access(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers, title="Temp shared", content="content")
        _share(client, auth_headers, note["id"], "other@test.com")
        share_id = client.get(f"/api/notes/{note['id']}/shares", headers=auth_headers).json()[0]["id"]
        client.delete(f"/api/notes/{note['id']}/share/{share_id}", headers=auth_headers)

        res = client.get(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 403


class TestEditSharePermission:
    def test_edit_share_allows_update(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers, title="Editable", content="original")
        _share(client, auth_headers, note["id"], "other@test.com", "edit")

        res = client.put(
            f"/api/notes/{note['id']}",
            json={"content": "updated by shared editor"},
            headers=second_user_headers,
        )
        assert res.status_code == 200
        assert res.json()["content"] == "updated by shared editor"

    def test_view_share_cannot_update(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers, title="Read only", content="original")
        _share(client, auth_headers, note["id"], "other@test.com", "view")

        res = client.put(
            f"/api/notes/{note['id']}",
            json={"content": "attempted update"},
            headers=second_user_headers,
        )
        assert res.status_code == 403

    def test_edit_share_cannot_delete(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers, title="Protected", content="content")
        _share(client, auth_headers, note["id"], "other@test.com", "edit")

        res = client.delete(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 403


# ── F-09b: Public share links ─────────────────────────────────────────────────

class TestShareLinks:
    def test_create_share_link_returns_token_and_url(self, client, auth_headers, registered_user):
        note = make_note(client, auth_headers)
        res = _create_link(client, auth_headers, note["id"])
        assert res.status_code == 201
        body = res.json()
        assert "token" in body
        assert "url" in body
        assert "expires_at" in body
        assert body["token"] in body["url"]

    def test_access_note_via_share_link_without_auth(self, client, auth_headers, registered_user):
        note = make_note(client, auth_headers, title="Shared publicly", content="public content")
        token = _create_link(client, auth_headers, note["id"]).json()["token"]

        res = client.get(f"/api/notes/shared/{token}")
        assert res.status_code == 200
        assert res.json()["title"] == "Shared publicly"

    def test_invalid_share_link_token_returns_404(self, client):
        res = client.get("/api/notes/shared/totally-invalid-token-123")
        assert res.status_code == 404

    def test_create_link_replaces_existing_active_link(self, client, auth_headers, registered_user):
        note = make_note(client, auth_headers)
        old_token = _create_link(client, auth_headers, note["id"]).json()["token"]
        new_token = _create_link(client, auth_headers, note["id"]).json()["token"]

        # Old link is revoked
        assert client.get(f"/api/notes/shared/{old_token}").status_code == 404
        # New link works
        assert client.get(f"/api/notes/shared/{new_token}").status_code == 200

    def test_revoke_share_link(self, client, auth_headers, registered_user):
        note = make_note(client, auth_headers)
        token = _create_link(client, auth_headers, note["id"]).json()["token"]

        revoke_res = client.delete(f"/api/notes/{note['id']}/share-link", headers=auth_headers)
        assert revoke_res.status_code == 204

        assert client.get(f"/api/notes/shared/{token}").status_code == 404

    def test_revoke_nonexistent_link_returns_404(self, client, auth_headers, registered_user):
        note = make_note(client, auth_headers)
        res = client.delete(f"/api/notes/{note['id']}/share-link", headers=auth_headers)
        assert res.status_code == 404

    def test_non_owner_cannot_create_share_link(self, client, auth_headers, second_user_headers, registered_user):
        note = make_note(client, auth_headers)
        res = _create_link(client, second_user_headers, note["id"])
        assert res.status_code == 403
