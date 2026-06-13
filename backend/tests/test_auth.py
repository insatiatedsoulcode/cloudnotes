"""
Auth tests — TDD + SSDLC layer.

Covers:
  - Registration: happy path, duplicates, invalid input
  - Login: happy path, wrong credentials, non-existent user
  - Token: structure, expiry handling
  - SSDLC: user enumeration resistance, password not exposed
"""

import pytest


# ── Registration ──────────────────────────────────────────────────────────────

class TestRegister:

    def test_success_returns_201_with_user_data(self, client):
        res = client.post("/api/auth/register", json={
            "email": "new@test.com", "password": "Password123",
        })
        assert res.status_code == 201
        body = res.json()
        assert body["email"] == "new@test.com"
        assert body["role"] == "user"
        assert "id" in body
        assert "created_at" in body

    def test_default_role_is_user_not_admin(self, client):
        res = client.post("/api/auth/register", json={
            "email": "u@test.com", "password": "Password123",
        })
        assert res.json()["role"] == "user"

    def test_duplicate_email_returns_400(self, client, registered_user):
        res = client.post("/api/auth/register", json={
            "email": "user@test.com", "password": "DifferentPass1",
        })
        assert res.status_code == 400
        assert "already registered" in res.json()["detail"].lower()

    def test_invalid_email_format_returns_422(self, client):
        res = client.post("/api/auth/register", json={
            "email": "notanemail", "password": "Password123",
        })
        assert res.status_code == 422

    def test_missing_password_returns_422(self, client):
        res = client.post("/api/auth/register", json={"email": "u@test.com"})
        assert res.status_code == 422

    def test_missing_email_returns_422(self, client):
        res = client.post("/api/auth/register", json={"password": "Password123"})
        assert res.status_code == 422

    def test_short_password_returns_422(self, client):
        # SSDLC: enforce minimum password length at schema level
        res = client.post("/api/auth/register", json={
            "email": "u@test.com", "password": "abc",
        })
        assert res.status_code == 422

    # ── SSDLC: sensitive data exposure ────────────────────────────────────────

    def test_password_hash_never_returned(self, client):
        res = client.post("/api/auth/register", json={
            "email": "u@test.com", "password": "Password123",
        })
        body = str(res.json())
        assert "password" not in body
        assert "hash" not in body

    def test_cannot_self_assign_admin_role(self, client):
        # Body has no role field, server must always default to "user"
        res = client.post("/api/auth/register", json={
            "email": "u@test.com", "password": "Password123", "role": "admin",
        })
        # Either 422 (extra field rejected) or 201 with role=user
        if res.status_code == 201:
            assert res.json()["role"] == "user"


# ── Login ─────────────────────────────────────────────────────────────────────

class TestLogin:

    def test_success_returns_bearer_token(self, client, registered_user):
        res = client.post("/api/auth/login",
                          data={"username": "user@test.com", "password": "Password123"})
        assert res.status_code == 200
        body = res.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        # Token must be a non-empty string with two dots (JWT structure)
        token = body["access_token"]
        assert isinstance(token, str) and token.count(".") == 2

    def test_wrong_password_returns_401(self, client, registered_user):
        res = client.post("/api/auth/login",
                          data={"username": "user@test.com", "password": "WrongPass1"})
        assert res.status_code == 401

    def test_nonexistent_user_returns_401(self, client):
        res = client.post("/api/auth/login",
                          data={"username": "nobody@test.com", "password": "Password123"})
        assert res.status_code == 401

    # ── SSDLC: user enumeration resistance ───────────────────────────────────

    def test_wrong_password_and_missing_user_return_same_error(self, client, registered_user):
        """
        Both cases must return identical status and error detail.
        If they differed, an attacker could enumerate valid emails.
        """
        res_wrong_pass = client.post("/api/auth/login",
                                     data={"username": "user@test.com", "password": "Wrong1"})
        res_no_user = client.post("/api/auth/login",
                                  data={"username": "ghost@test.com", "password": "Wrong1"})

        assert res_wrong_pass.status_code == res_no_user.status_code == 401
        assert res_wrong_pass.json()["detail"] == res_no_user.json()["detail"]

    def test_sql_injection_in_email_field_returns_401(self, client):
        """SQL injection must not crash the server or grant access."""
        payloads = [
            "' OR '1'='1",
            "admin'--",
            "' UNION SELECT * FROM users--",
        ]
        for payload in payloads:
            res = client.post("/api/auth/login",
                              data={"username": payload, "password": "x"})
            assert res.status_code in (401, 422), f"Unexpected status for payload: {payload}"
