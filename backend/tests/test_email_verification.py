"""
F-05 Email Verification tests.

Covers:
  - register() sends exactly one verification email
  - GET /api/auth/verify with valid token → 200, is_verified=True
  - GET /api/auth/verify with invalid/used/expired token → 400
  - Unverified user cannot create notes (403)
  - Unverified user CAN list/read notes
  - POST /api/auth/resend-verification → sends new email, old token invalidated
  - Already-verified user gets 400 on resend
  - Resend requires authentication
"""

from datetime import datetime, timedelta

import pytest


# ── Helpers ───────────────────────────────────────────────────────────────────

def _register(client, email="v@test.com", password="Password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    assert res.status_code == 201, res.json()
    return res.json()


def _login_headers(client, email="v@test.com", password="Password123"):
    res = client.post("/api/auth/login", data={"username": email, "password": password})
    assert res.status_code == 200, res.json()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ── Registration sends verification email ─────────────────────────────────────

class TestRegistrationSendsEmail:

    def test_register_sends_one_email(self, client, mock_email):
        _register(client)
        assert mock_email.call_count == 1

    def test_register_sends_to_correct_address(self, client, mock_email):
        _register(client, email="hello@example.com")
        assert mock_email.call_args.kwargs["to"] == "hello@example.com"

    def test_register_sends_a_token(self, client, mock_email):
        _register(client)
        token = mock_email.call_args.kwargs["token"]
        assert token and len(token) > 10

    def test_register_response_has_is_verified_false(self, client, mock_email):
        body = _register(client)
        assert body["is_verified"] is False


# ── Verify endpoint ───────────────────────────────────────────────────────────

class TestVerifyEmail:

    def test_valid_token_returns_200(self, client, mock_email):
        _register(client)
        token = mock_email.call_args.kwargs["token"]
        res = client.get(f"/api/auth/verify?token={token}")
        assert res.status_code == 200

    def test_valid_token_returns_success_message(self, client, mock_email):
        _register(client)
        token = mock_email.call_args.kwargs["token"]
        res = client.get(f"/api/auth/verify?token={token}")
        assert "verified" in res.json()["message"].lower()

    def test_profile_shows_is_verified_true_after_verify(self, client, mock_email):
        _register(client)
        token = mock_email.call_args.kwargs["token"]
        client.get(f"/api/auth/verify?token={token}")

        headers = _login_headers(client)
        profile = client.get("/api/users/me", headers=headers).json()
        assert profile["is_verified"] is True

    def test_wrong_token_returns_400(self, client, mock_email):
        _register(client)
        res = client.get("/api/auth/verify?token=this-is-not-a-valid-token")
        assert res.status_code == 400

    def test_token_cannot_be_used_twice(self, client, mock_email):
        _register(client)
        token = mock_email.call_args.kwargs["token"]
        client.get(f"/api/auth/verify?token={token}")
        res = client.get(f"/api/auth/verify?token={token}")
        assert res.status_code == 400

    def test_expired_token_returns_400(self, client, mock_email):
        """Manually expire the token in the DB and confirm it is rejected."""
        _register(client)

        from tests.conftest import _TestSession
        from app.models.email_verification import EmailVerification

        db = _TestSession()
        row = db.query(EmailVerification).first()
        row.expires_at = datetime.utcnow() - timedelta(hours=1)
        db.commit()
        db.close()

        token = mock_email.call_args.kwargs["token"]
        res = client.get(f"/api/auth/verify?token={token}")
        assert res.status_code == 400

    def test_missing_token_query_param_returns_422(self, client):
        res = client.get("/api/auth/verify")
        assert res.status_code == 422


# ── Verification gate on note creation ───────────────────────────────────────

class TestVerificationGate:

    def test_unverified_user_cannot_create_note(self, client, mock_email):
        _register(client)
        headers = _login_headers(client)
        res = client.post("/api/notes/",
                          json={"title": "T", "content": "C"},
                          headers=headers)
        assert res.status_code == 403

    def test_unverified_error_message_mentions_email(self, client, mock_email):
        _register(client)
        headers = _login_headers(client)
        res = client.post("/api/notes/",
                          json={"title": "T", "content": "C"},
                          headers=headers)
        assert "verify" in res.json()["detail"].lower()

    def test_verified_user_can_create_note(self, client, mock_email):
        _register(client)
        token = mock_email.call_args.kwargs["token"]
        client.get(f"/api/auth/verify?token={token}")

        headers = _login_headers(client)
        res = client.post("/api/notes/",
                          json={"title": "T", "content": "C"},
                          headers=headers)
        assert res.status_code == 201

    def test_unverified_user_can_list_notes(self, client, mock_email):
        """Read operations don't require verification — only writes do."""
        _register(client)
        headers = _login_headers(client)
        res = client.get("/api/notes/", headers=headers)
        assert res.status_code == 200

    def test_unverified_user_can_read_public_note(self, client, mock_email, auth_headers):
        """Verified user creates a public note; unverified user can read it."""
        # auth_headers user is already verified (registered_user fixture auto-verifies)
        pub_note = client.post(
            "/api/notes/",
            json={"title": "Public", "content": "body", "visibility": "public"},
            headers=auth_headers,
        ).json()

        _register(client, email="unverified@test.com")
        unverified_hdrs = _login_headers(client, "unverified@test.com")
        res = client.get(f"/api/notes/{pub_note['id']}", headers=unverified_hdrs)
        assert res.status_code == 200


# ── Resend verification ───────────────────────────────────────────────────────

class TestResendVerification:

    def test_resend_sends_new_email(self, client, mock_email):
        _register(client)
        mock_email.reset_mock()

        headers = _login_headers(client)
        res = client.post("/api/auth/resend-verification", headers=headers)
        assert res.status_code == 200
        assert mock_email.call_count == 1

    def test_resend_new_token_works_for_verification(self, client, mock_email):
        _register(client)
        headers = _login_headers(client)
        mock_email.reset_mock()

        client.post("/api/auth/resend-verification", headers=headers)
        new_token = mock_email.call_args.kwargs["token"]

        res = client.get(f"/api/auth/verify?token={new_token}")
        assert res.status_code == 200

    def test_resend_invalidates_old_token(self, client, mock_email):
        _register(client)
        old_token = mock_email.call_args.kwargs["token"]
        mock_email.reset_mock()

        headers = _login_headers(client)
        client.post("/api/auth/resend-verification", headers=headers)

        # Old token must now be rejected
        res = client.get(f"/api/auth/verify?token={old_token}")
        assert res.status_code == 400

    def test_already_verified_cannot_resend(self, client, mock_email):
        _register(client)
        token = mock_email.call_args.kwargs["token"]
        client.get(f"/api/auth/verify?token={token}")

        headers = _login_headers(client)
        res = client.post("/api/auth/resend-verification", headers=headers)
        assert res.status_code == 400

    def test_resend_requires_authentication(self, client):
        res = client.post("/api/auth/resend-verification")
        assert res.status_code == 401
