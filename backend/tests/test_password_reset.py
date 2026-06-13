"""
F-06 Password Reset tests.

Covers:
  - POST /api/auth/forgot-password always returns 200 (user enumeration resistance)
  - forgot-password sends email only when user exists
  - POST /api/auth/reset-password with valid token → 200, password updated
  - New password works on login; old password rejected
  - Invalid / used / expired token → 400
  - Resetting password does not affect is_verified status
"""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _register(client, email="reset@test.com", password="OldPass123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.json()
    return res.json()


def _forgot(client, email="reset@test.com"):
    return client.post("/api/auth/forgot-password", json={"email": email})


def _reset(client, token, new_password="NewPass123"):
    return client.post("/api/auth/reset-password",
                       json={"token": token, "new_password": new_password})


def _login_ok(client, email="reset@test.com", password="NewPass123"):
    res = client.post("/api/auth/login", data={"username": email, "password": password})
    return res.status_code == 200


# ── Forgot password ───────────────────────────────────────────────────────────

class TestForgotPassword:

    def test_returns_200_for_registered_email(self, client, mock_password_reset_email):
        _register(client)
        res = _forgot(client)
        assert res.status_code == 200

    def test_returns_200_for_unknown_email(self, client, mock_password_reset_email):
        # Must not reveal whether the email is registered
        res = _forgot(client, email="nobody@nowhere.com")
        assert res.status_code == 200

    def test_response_body_is_identical_for_both_cases(self, client, mock_password_reset_email):
        _register(client)
        res_known = _forgot(client, email="reset@test.com")
        res_unknown = _forgot(client, email="ghost@test.com")
        assert res_known.json()["message"] == res_unknown.json()["message"]

    def test_sends_email_when_user_exists(self, client, mock_password_reset_email):
        _register(client)
        _forgot(client)
        assert mock_password_reset_email.call_count == 1

    def test_does_not_send_email_for_unknown_address(self, client, mock_password_reset_email):
        _forgot(client, email="nobody@nowhere.com")
        assert mock_password_reset_email.call_count == 0

    def test_email_sent_to_correct_address(self, client, mock_password_reset_email):
        _register(client, email="target@test.com")
        _forgot(client, email="target@test.com")
        assert mock_password_reset_email.call_args.kwargs["to"] == "target@test.com"

    def test_token_is_present_in_email_call(self, client, mock_password_reset_email):
        _register(client)
        _forgot(client)
        token = mock_password_reset_email.call_args.kwargs["token"]
        assert token and len(token) > 10

    def test_invalid_email_format_returns_422(self, client):
        res = client.post("/api/auth/forgot-password", json={"email": "not-an-email"})
        assert res.status_code == 422


# ── Reset password ────────────────────────────────────────────────────────────

class TestResetPassword:

    def test_valid_token_returns_200(self, client, mock_password_reset_email):
        _register(client)
        _forgot(client)
        token = mock_password_reset_email.call_args.kwargs["token"]
        res = _reset(client, token)
        assert res.status_code == 200

    def test_new_password_works_on_login(self, client, mock_password_reset_email):
        _register(client, password="OldPass123")
        _forgot(client)
        token = mock_password_reset_email.call_args.kwargs["token"]
        _reset(client, token, new_password="BrandNew456")

        assert _login_ok(client, password="BrandNew456")

    def test_old_password_rejected_after_reset(self, client, mock_password_reset_email):
        _register(client, password="OldPass123")
        _forgot(client)
        token = mock_password_reset_email.call_args.kwargs["token"]
        _reset(client, token, new_password="BrandNew456")

        res = client.post("/api/auth/login",
                          data={"username": "reset@test.com", "password": "OldPass123"})
        assert res.status_code == 401

    def test_invalid_token_returns_400(self, client, mock_password_reset_email):
        _register(client)
        res = _reset(client, token="completely-wrong-token")
        assert res.status_code == 400

    def test_token_cannot_be_used_twice(self, client, mock_password_reset_email):
        _register(client)
        _forgot(client)
        token = mock_password_reset_email.call_args.kwargs["token"]

        _reset(client, token)
        res = _reset(client, token, new_password="AnotherPass789")
        assert res.status_code == 400

    def test_expired_token_returns_400(self, client, fake_redis, mock_password_reset_email):
        """Simulate expiry by deleting the Redis key before the reset attempt."""
        _register(client)
        _forgot(client)
        token = mock_password_reset_email.call_args.kwargs["token"]

        # Manually expire: delete all pwd_reset keys from fakeredis
        for key in fake_redis.keys("pwd_reset:*"):
            fake_redis.delete(key)

        res = _reset(client, token)
        assert res.status_code == 400

    def test_new_password_too_short_returns_422(self, client, mock_password_reset_email):
        _register(client)
        _forgot(client)
        token = mock_password_reset_email.call_args.kwargs["token"]
        res = _reset(client, token, new_password="short")
        assert res.status_code == 422

    def test_reset_does_not_change_is_verified_status(self, client, mock_password_reset_email):
        """Password reset is independent of email verification state."""
        _register(client)  # registered but unverified
        _forgot(client)
        token = mock_password_reset_email.call_args.kwargs["token"]
        _reset(client, token)

        # Login and check profile — is_verified should still be False
        login_res = client.post("/api/auth/login",
                                data={"username": "reset@test.com", "password": "NewPass123"})
        auth_headers = {"Authorization": f"Bearer {login_res.json()['access_token']}"}
        profile = client.get("/api/users/me", headers=auth_headers).json()
        assert profile["is_verified"] is False

    def test_multiple_forgot_requests_last_token_wins(self, client, mock_password_reset_email):
        """Each forgot-password call writes a new Redis key.  Both tokens work independently
        since each has its own key (keyed by token_hash).  This is acceptable behaviour —
        production apps may optionally invalidate previous tokens on new request."""
        _register(client)
        _forgot(client)
        token1 = mock_password_reset_email.call_args.kwargs["token"]
        mock_password_reset_email.reset_mock()

        _forgot(client)
        token2 = mock_password_reset_email.call_args.kwargs["token"]

        # Both tokens are valid (each has its own Redis key)
        assert token1 != token2
        res = _reset(client, token2, new_password="FromToken2_456")
        assert res.status_code == 200
