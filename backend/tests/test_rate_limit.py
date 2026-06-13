"""
F-02 Rate Limiting tests.

Strategy:
- Each test starts with a clean limiter (reset_rate_limiter autouse fixture in conftest).
- We exhaust the limit within the test, then assert the next call returns 429.
- We verify the 429 response is JSON (not plain text) and includes the correct fields.
"""

import pytest
from tests.conftest import make_note


class TestLoginRateLimit:
    def test_fifth_login_still_succeeds(self, client):
        """Requests 1–5 within the 5/minute window must all get through."""
        client.post("/api/auth/register", json={"email": "a@test.com", "password": "Pass1234"})
        for _ in range(5):
            res = client.post("/api/auth/login",
                              data={"username": "a@test.com", "password": "wrong"})
            assert res.status_code in (200, 401)  # valid response, not 429

    def test_sixth_login_returns_429(self, client):
        """The 6th login attempt within 1 minute must be blocked with 429."""
        client.post("/api/auth/register", json={"email": "b@test.com", "password": "Pass1234"})
        for _ in range(5):
            client.post("/api/auth/login",
                        data={"username": "b@test.com", "password": "wrong"})

        res = client.post("/api/auth/login",
                          data={"username": "b@test.com", "password": "wrong"})
        assert res.status_code == 429

    def test_429_response_is_json(self, client):
        """429 must return JSON, not a plain-text or HTML body."""
        client.post("/api/auth/register", json={"email": "c@test.com", "password": "Pass1234"})
        for _ in range(5):
            client.post("/api/auth/login",
                        data={"username": "c@test.com", "password": "wrong"})

        res = client.post("/api/auth/login",
                          data={"username": "c@test.com", "password": "wrong"})
        assert res.status_code == 429
        body = res.json()
        assert "detail" in body

    def test_429_includes_retry_after_header(self, client):
        """429 must include Retry-After header so clients know when to retry."""
        client.post("/api/auth/register", json={"email": "d@test.com", "password": "Pass1234"})
        for _ in range(5):
            client.post("/api/auth/login",
                        data={"username": "d@test.com", "password": "wrong"})

        res = client.post("/api/auth/login",
                          data={"username": "d@test.com", "password": "wrong"})
        assert res.status_code == 429
        assert "retry-after" in res.headers


class TestRegisterRateLimit:
    def test_third_register_still_succeeds(self, client):
        """Requests 1–3 within the 3/minute window must all get through."""
        for i in range(3):
            res = client.post("/api/auth/register",
                              json={"email": f"reg{i}@test.com", "password": "Pass1234"})
            assert res.status_code in (201, 400)  # 400 = duplicate email, not 429

    def test_fourth_register_returns_429(self, client):
        """The 4th registration attempt within 1 minute must be blocked."""
        for i in range(3):
            client.post("/api/auth/register",
                        json={"email": f"r{i}@test.com", "password": "Pass1234"})

        res = client.post("/api/auth/register",
                          json={"email": "r99@test.com", "password": "Pass1234"})
        assert res.status_code == 429


class TestNotesWriteRateLimit:
    """Notes write endpoints are limited to 30/minute per user (JWT-based key)."""

    def _exhaust_create_limit(self, client, headers, n=30):
        for i in range(n):
            client.post("/api/notes/",
                        json={"title": f"Note {i}", "content": "content"},
                        headers=headers)

    def test_note_create_blocked_after_30(self, client, auth_headers):
        self._exhaust_create_limit(client, auth_headers, n=30)
        res = client.post("/api/notes/",
                          json={"title": "Overflow", "content": "blocked"},
                          headers=auth_headers)
        assert res.status_code == 429

    def test_different_users_have_independent_limits(self, client, auth_headers, second_user_headers):
        """User A exhausting their limit must not affect User B."""
        self._exhaust_create_limit(client, auth_headers, n=30)

        # User A is now blocked
        res_a = client.post("/api/notes/",
                            json={"title": "A overflow", "content": "x"},
                            headers=auth_headers)
        assert res_a.status_code == 429

        # User B should still be under their own independent limit
        res_b = client.post("/api/notes/",
                            json={"title": "B note", "content": "y"},
                            headers=second_user_headers)
        assert res_b.status_code == 201


class TestGlobalDefaultLimit:
    def test_health_endpoint_not_rate_limited(self, client):
        """Ensure repeated calls to read-only endpoints are not blocked."""
        for _ in range(10):
            res = client.get("/health")
            assert res.status_code == 200

    def test_read_endpoints_not_blocked_by_write_limit(self, client, auth_headers):
        """GET requests use global limit (60/min), not the write limit (30/min)."""
        note = make_note(client, auth_headers)
        for _ in range(35):   # exceeds the 30/min write limit
            res = client.get(f"/api/notes/{note['id']}", headers=auth_headers)
            assert res.status_code == 200  # GET is never blocked by write limit
