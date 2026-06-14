"""
F-07 Refresh Token (Token Rotation) + Session Management tests.

Covers:
  - Login issues access token (JSON body) + refresh token (HTTP-only cookie)
  - POST /api/auth/refresh rotates the cookie: old token revoked, new pair issued
  - POST /api/auth/refresh without cookie → 401
  - POST /api/auth/refresh with expired token → 401
  - POST /api/auth/logout → token revoked, cookie cleared, subsequent refresh → 401
  - Reuse detection: replaying a rotated token revokes the entire session family
  - Suspended account cannot refresh
  - Password reset revokes all refresh tokens
  - Password change (PUT /users/me) revokes all refresh tokens
  - GET /api/auth/sessions — lists active sessions with IP, UA, is_current
  - DELETE /api/auth/sessions/{id} — revoke one session
  - DELETE /api/auth/sessions — logout everywhere (revoke all)
"""

import pytest
from tests.conftest import _auto_verify, _TestSession


# ── Helpers ───────────────────────────────────────────────────────────────────

def _register(client, email="rt@test.com", password="Pass123!"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.json()
    return res.json()


def _login(client, email="rt@test.com", password="Pass123!"):
    """Returns (access_token, refresh_cookie_value)."""
    res = client.post("/api/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200, res.json()
    access = res.json()["access_token"]
    refresh = res.cookies.get("refresh_token")
    # Clear jar so we control cookies explicitly in tests
    client.cookies.clear()
    return access, refresh


def _auth(access_token):
    return {"Authorization": f"Bearer {access_token}"}


# ── Login issues both tokens ──────────────────────────────────────────────────

class TestLogin:

    def test_login_returns_access_token_in_body(self, client):
        _register(client)
        res = client.post("/api/auth/login",
                          data={"username": "rt@test.com", "password": "Pass123!"})
        assert res.status_code == 200
        assert "access_token" in res.json()

    def test_login_sets_refresh_cookie(self, client):
        _register(client)
        res = client.post("/api/auth/login",
                          data={"username": "rt@test.com", "password": "Pass123!"})
        assert res.cookies.get("refresh_token") is not None

    def test_access_token_grants_api_access(self, client):
        _register(client)
        access, _ = _login(client)
        res = client.get("/api/notes/", headers=_auth(access))
        assert res.status_code == 200

    def test_refresh_token_is_not_in_response_body(self, client):
        _register(client)
        res = client.post("/api/auth/login",
                          data={"username": "rt@test.com", "password": "Pass123!"})
        body = res.json()
        assert "refresh_token" not in body


# ── Refresh endpoint ──────────────────────────────────────────────────────────

class TestRefresh:

    def test_valid_cookie_returns_new_access_token(self, client):
        _register(client)
        _, refresh = _login(client)
        res = client.post("/api/auth/refresh",
                          cookies={"refresh_token": refresh})
        assert res.status_code == 200
        assert "access_token" in res.json()

    def test_refresh_rotates_the_cookie(self, client):
        _register(client)
        _, refresh_v1 = _login(client)
        res = client.post("/api/auth/refresh",
                          cookies={"refresh_token": refresh_v1})
        refresh_v2 = res.cookies.get("refresh_token")
        assert refresh_v2 is not None
        assert refresh_v2 != refresh_v1

    def test_new_access_token_is_valid(self, client):
        _register(client)
        _, refresh = _login(client)
        new_access = client.post(
            "/api/auth/refresh", cookies={"refresh_token": refresh}
        ).json()["access_token"]
        assert client.get("/api/notes/", headers=_auth(new_access)).status_code == 200

    def test_old_refresh_token_rejected_after_rotation(self, client):
        _register(client)
        _, refresh_v1 = _login(client)
        client.post("/api/auth/refresh", cookies={"refresh_token": refresh_v1})

        # v1 is now revoked — should trigger reuse detection
        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh_v1})
        assert res.status_code == 401

    def test_refresh_without_cookie_returns_401(self, client):
        _register(client)
        res = client.post("/api/auth/refresh")
        assert res.status_code == 401

    def test_refresh_with_garbage_token_returns_401(self, client):
        res = client.post("/api/auth/refresh",
                          cookies={"refresh_token": "totally-invalid-garbage"})
        assert res.status_code == 401

    def test_expired_token_returns_401(self, client):
        """Simulate expiry by directly setting expires_at in the past."""
        _register(client)
        _, refresh = _login(client)

        from app.models.refresh_token import RefreshToken
        from app.email import hash_token
        from datetime import timedelta

        db = _TestSession()
        hashed = hash_token(refresh)
        rt = db.query(RefreshToken).filter(RefreshToken.token_hash == hashed).first()
        rt.expires_at = rt.created_at - timedelta(hours=1)
        db.commit()
        db.close()

        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh})
        assert res.status_code == 401

    def test_suspended_user_cannot_refresh(self, client):
        _register(client)
        access, refresh = _login(client)

        # Suspend the account
        client.delete("/api/users/me", headers=_auth(access))

        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh})
        assert res.status_code == 401


# ── Reuse detection ───────────────────────────────────────────────────────────

class TestReuseDetection:

    def test_replaying_rotated_token_returns_401(self, client):
        _register(client)
        _, refresh_v1 = _login(client)

        # Legitimate rotation: v1 → v2
        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh_v1})
        assert res.status_code == 200

        # Replay v1 (already revoked)
        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh_v1})
        assert res.status_code == 401

    def test_reuse_revokes_entire_family(self, client):
        _register(client)
        _, refresh_v1 = _login(client)

        # Legitimate rotation: v1 → v2
        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh_v1})
        refresh_v2 = res.cookies.get("refresh_token")
        client.cookies.clear()

        # Replay v1 → triggers family revocation
        client.post("/api/auth/refresh", cookies={"refresh_token": refresh_v1})

        # v2 (which was legitimately issued) must also be revoked now
        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh_v2})
        assert res.status_code == 401


# ── Logout ────────────────────────────────────────────────────────────────────

class TestLogout:

    def test_logout_returns_204(self, client):
        _register(client)
        _, refresh = _login(client)
        res = client.post("/api/auth/logout", cookies={"refresh_token": refresh})
        assert res.status_code == 204

    def test_refresh_fails_after_logout(self, client):
        _register(client)
        _, refresh = _login(client)
        client.post("/api/auth/logout", cookies={"refresh_token": refresh})
        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh})
        assert res.status_code == 401

    def test_logout_clears_cookie(self, client):
        _register(client)
        _, refresh = _login(client)
        res = client.post("/api/auth/logout", cookies={"refresh_token": refresh})
        # Cookie should be cleared (empty value or absent)
        cleared = res.cookies.get("refresh_token")
        assert not cleared

    def test_logout_without_cookie_is_harmless(self, client):
        """Logout with no cookie must not crash — idempotent."""
        res = client.post("/api/auth/logout")
        assert res.status_code == 204


# ── Password change / reset revokes sessions ──────────────────────────────────

class TestPasswordRevokesTokens:

    def test_password_reset_revokes_refresh_tokens(
        self, client, mock_password_reset_email
    ):
        _register(client)
        _, refresh = _login(client)

        # Request and consume a password reset
        client.post("/api/auth/forgot-password", json={"email": "rt@test.com"})
        reset_token = mock_password_reset_email.call_args.kwargs["token"]
        client.post("/api/auth/reset-password",
                    json={"token": reset_token, "new_password": "NewPass456!"})

        # Old refresh token should now be revoked
        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh})
        assert res.status_code == 401

    def test_password_change_revokes_refresh_tokens(self, client):
        _register(client)
        _auto_verify(1)  # user_id=1 (first user after TRUNCATE)
        access, refresh = _login(client)

        # Change password via profile endpoint
        client.put(
            "/api/users/me",
            json={"current_password": "Pass123!", "new_password": "Changed789!"},
            headers=_auth(access),
        )

        # Old refresh token should now be revoked
        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh})
        assert res.status_code == 401

    def test_can_login_and_refresh_after_password_reset(
        self, client, mock_password_reset_email
    ):
        """After reset, user logs in fresh and gets a new working session."""
        _register(client)
        client.post("/api/auth/forgot-password", json={"email": "rt@test.com"})
        reset_token = mock_password_reset_email.call_args.kwargs["token"]
        client.post("/api/auth/reset-password",
                    json={"token": reset_token, "new_password": "NewPass456!"})

        # Login with new password
        res_login = client.post("/api/auth/login",
                                data={"username": "rt@test.com", "password": "NewPass456!"})
        assert res_login.status_code == 200
        new_refresh = res_login.cookies.get("refresh_token")
        client.cookies.clear()

        # New refresh token works
        res = client.post("/api/auth/refresh", cookies={"refresh_token": new_refresh})
        assert res.status_code == 200


# ── Session management ────────────────────────────────────────────────────────

class TestSessionList:

    def test_list_sessions_requires_auth(self, client):
        res = client.get("/api/auth/sessions")
        assert res.status_code == 401

    def test_login_creates_one_session(self, client):
        _register(client)
        res_login = client.post("/api/auth/login",
                                data={"username": "rt@test.com", "password": "Pass123!"})
        access = res_login.json()["access_token"]

        res = client.get("/api/auth/sessions", headers=_auth(access))
        assert res.status_code == 200
        assert len(res.json()) == 1

    def test_two_logins_create_two_sessions(self, client):
        _register(client)
        client.post("/api/auth/login", data={"username": "rt@test.com", "password": "Pass123!"})
        res2 = client.post("/api/auth/login", data={"username": "rt@test.com", "password": "Pass123!"})
        access = res2.json()["access_token"]

        sessions = client.get("/api/auth/sessions", headers=_auth(access)).json()
        assert len(sessions) == 2

    def test_session_response_has_expected_fields(self, client):
        _register(client)
        res_login = client.post("/api/auth/login",
                                data={"username": "rt@test.com", "password": "Pass123!"})
        access = res_login.json()["access_token"]

        session = client.get("/api/auth/sessions", headers=_auth(access)).json()[0]
        assert "id" in session
        assert "created_at" in session
        assert "expires_at" in session
        assert "is_current" in session

    def test_is_current_true_when_cookie_present(self, client):
        _register(client)
        # Login — keep cookie in jar this time (don't clear)
        res_login = client.post("/api/auth/login",
                                data={"username": "rt@test.com", "password": "Pass123!"})
        access = res_login.json()["access_token"]
        # Cookie is auto-stored in client jar; GET /sessions will send it
        sessions = client.get("/api/auth/sessions", headers=_auth(access)).json()
        assert any(s["is_current"] for s in sessions)

    def test_is_current_false_without_cookie(self, client):
        _register(client)
        access, _ = _login(client)  # _login() clears the cookie jar
        sessions = client.get("/api/auth/sessions", headers=_auth(access)).json()
        assert not any(s["is_current"] for s in sessions)

    def test_revoked_sessions_not_listed(self, client):
        _register(client)
        access, refresh = _login(client)

        # Logout (revokes the token)
        client.post("/api/auth/logout", cookies={"refresh_token": refresh})

        sessions = client.get("/api/auth/sessions", headers=_auth(access)).json()
        assert len(sessions) == 0

    def test_only_own_sessions_listed(self, client):
        """User A must never see User B's sessions."""
        _register(client, email="user_a@test.com")
        _register(client, email="user_b@test.com")

        # Log in as both
        r_a = client.post("/api/auth/login", data={"username": "user_a@test.com", "password": "Pass123!"})
        r_b = client.post("/api/auth/login", data={"username": "user_b@test.com", "password": "Pass123!"})
        access_a = r_a.json()["access_token"]
        access_b = r_b.json()["access_token"]

        sessions_a = client.get("/api/auth/sessions", headers=_auth(access_a)).json()
        sessions_b = client.get("/api/auth/sessions", headers=_auth(access_b)).json()

        # Each user sees exactly 1 session (their own)
        assert len(sessions_a) == 1
        assert len(sessions_b) == 1
        assert sessions_a[0]["id"] != sessions_b[0]["id"]


class TestRevokeSession:

    def test_revoke_own_session_returns_204(self, client):
        _register(client)
        access, _ = _login(client)
        session_id = client.get("/api/auth/sessions", headers=_auth(access)).json()[0]["id"]

        res = client.delete(f"/api/auth/sessions/{session_id}", headers=_auth(access))
        assert res.status_code == 204

    def test_revoked_session_disappears_from_list(self, client):
        _register(client)
        access, _ = _login(client)
        session_id = client.get("/api/auth/sessions", headers=_auth(access)).json()[0]["id"]

        client.delete(f"/api/auth/sessions/{session_id}", headers=_auth(access))

        sessions = client.get("/api/auth/sessions", headers=_auth(access)).json()
        assert not any(s["id"] == session_id for s in sessions)

    def test_revoke_another_users_session_returns_404(self, client):
        _register(client, email="user_a@test.com")
        _register(client, email="user_b@test.com")

        r_a = client.post("/api/auth/login", data={"username": "user_a@test.com", "password": "Pass123!"})
        r_b = client.post("/api/auth/login", data={"username": "user_b@test.com", "password": "Pass123!"})
        access_a = r_a.json()["access_token"]
        access_b = r_b.json()["access_token"]

        # Get user_b's session id
        session_b_id = client.get("/api/auth/sessions", headers=_auth(access_b)).json()[0]["id"]

        # User A tries to revoke User B's session
        res = client.delete(f"/api/auth/sessions/{session_b_id}", headers=_auth(access_a))
        assert res.status_code == 404

    def test_revoke_nonexistent_session_returns_404(self, client):
        _register(client)
        access, _ = _login(client)
        res = client.delete("/api/auth/sessions/99999", headers=_auth(access))
        assert res.status_code == 404

    def test_refresh_fails_after_session_revoked(self, client):
        _register(client)
        access, refresh = _login(client)
        session_id = client.get("/api/auth/sessions", headers=_auth(access)).json()[0]["id"]

        client.delete(f"/api/auth/sessions/{session_id}", headers=_auth(access))

        res = client.post("/api/auth/refresh", cookies={"refresh_token": refresh})
        assert res.status_code == 401

    def test_revoke_requires_auth(self, client):
        res = client.delete("/api/auth/sessions/1")
        assert res.status_code == 401


class TestRevokeAllSessions:

    def test_revoke_all_returns_204(self, client):
        _register(client)
        access, _ = _login(client)
        res = client.delete("/api/auth/sessions", headers=_auth(access))
        assert res.status_code == 204

    def test_no_sessions_after_revoke_all(self, client):
        _register(client)
        # Create two sessions
        client.post("/api/auth/login", data={"username": "rt@test.com", "password": "Pass123!"})
        res2 = client.post("/api/auth/login", data={"username": "rt@test.com", "password": "Pass123!"})
        access = res2.json()["access_token"]

        client.delete("/api/auth/sessions", headers=_auth(access))

        sessions = client.get("/api/auth/sessions", headers=_auth(access)).json()
        assert len(sessions) == 0

    def test_all_refresh_tokens_fail_after_revoke_all(self, client):
        _register(client)
        _, refresh1 = _login(client)
        _, refresh2 = _login(client)
        access, _ = _login(client)

        client.delete("/api/auth/sessions", headers=_auth(access))

        assert client.post("/api/auth/refresh", cookies={"refresh_token": refresh1}).status_code == 401
        assert client.post("/api/auth/refresh", cookies={"refresh_token": refresh2}).status_code == 401

    def test_revoke_all_requires_auth(self, client):
        res = client.delete("/api/auth/sessions")
        assert res.status_code == 401
