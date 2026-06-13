"""
F-04c User Profile tests.

Covers:
  - GET /api/users/me — returns own profile including is_active
  - PUT /api/users/me — changes password, requires current password
  - DELETE /api/users/me — soft-deletes account (is_active=False)
  - Suspended accounts (is_active=False) cannot access the API
"""


class TestGetProfile:
    def test_returns_own_profile(self, client, auth_headers, registered_user):
        res = client.get("/api/users/me", headers=auth_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["email"] == registered_user["email"]
        assert body["id"] == registered_user["id"]
        assert body["is_active"] is True

    def test_requires_authentication(self, client):
        assert client.get("/api/users/me").status_code == 401

    def test_profile_does_not_expose_password_hash(self, client, auth_headers):
        res = client.get("/api/users/me", headers=auth_headers)
        assert "password_hash" not in res.json()
        assert "password" not in res.json()


class TestUpdateProfile:
    def test_can_change_password(self, client, auth_headers):
        res = client.put("/api/users/me",
                         json={"current_password": "Password123",
                               "new_password": "NewPass456"},
                         headers=auth_headers)
        assert res.status_code == 200

    def test_new_password_works_on_login(self, client, auth_headers, registered_user):
        client.put("/api/users/me",
                   json={"current_password": "Password123",
                         "new_password": "NewPass456"},
                   headers=auth_headers)
        res = client.post("/api/auth/login",
                          data={"username": registered_user["email"],
                                "password": "NewPass456"})
        assert res.status_code == 200
        assert "access_token" in res.json()

    def test_old_password_rejected_after_change(self, client, auth_headers, registered_user):
        client.put("/api/users/me",
                   json={"current_password": "Password123",
                         "new_password": "NewPass456"},
                   headers=auth_headers)
        res = client.post("/api/auth/login",
                          data={"username": registered_user["email"],
                                "password": "Password123"})
        assert res.status_code == 401

    def test_wrong_current_password_returns_400(self, client, auth_headers):
        res = client.put("/api/users/me",
                         json={"current_password": "WrongPassword",
                               "new_password": "NewPass456"},
                         headers=auth_headers)
        assert res.status_code == 400

    def test_new_password_too_short_returns_422(self, client, auth_headers):
        res = client.put("/api/users/me",
                         json={"current_password": "Password123",
                               "new_password": "short"},
                         headers=auth_headers)
        assert res.status_code == 422


class TestDeactivateAccount:
    def test_delete_me_returns_204(self, client, auth_headers):
        res = client.delete("/api/users/me", headers=auth_headers)
        assert res.status_code == 204

    def test_deactivated_user_cannot_call_api(self, client, auth_headers):
        client.delete("/api/users/me", headers=auth_headers)
        res = client.get("/api/notes/", headers=auth_headers)
        assert res.status_code == 403

    def test_deactivated_account_detail_message(self, client, auth_headers):
        client.delete("/api/users/me", headers=auth_headers)
        res = client.get("/api/notes/", headers=auth_headers)
        assert "suspended" in res.json()["detail"].lower()
