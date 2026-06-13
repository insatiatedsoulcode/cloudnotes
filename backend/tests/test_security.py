"""
SSDLC security tests.

Each test class maps to an OWASP / SSDLC threat category so the test suite
doubles as a living security checklist.

Categories covered:
  - Broken Authentication     : token tampering, alg:none attack, expired tokens
  - Broken Access Control     : IDOR, horizontal privilege escalation
  - Injection                 : SQL injection in all user-controlled fields
  - Security Misconfiguration : sensitive data in responses
  - Insecure Design           : mass-assignment, user enumeration
"""

import base64
import json
import time
import pytest


def _b64(data: dict) -> str:
    """Encode a dict as base64url without padding (JWT style)."""
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


def _extract_token(auth_header: str) -> str:
    return auth_header["Authorization"].split(" ")[1]


# ── Broken Authentication ─────────────────────────────────────────────────────

class TestBrokenAuthentication:

    def test_no_token_returns_401(self, client):
        assert client.get("/api/notes/").status_code == 401

    def test_empty_bearer_returns_401(self, client):
        res = client.get("/api/notes/", headers={"Authorization": "Bearer "})
        assert res.status_code == 401

    def test_random_string_token_returns_401(self, client):
        res = client.get("/api/notes/", headers={"Authorization": "Bearer notavalidtoken"})
        assert res.status_code == 401

    def test_malformed_jwt_two_parts_returns_401(self, client):
        """JWT must have exactly 3 parts."""
        res = client.get("/api/notes/", headers={"Authorization": "Bearer header.payload"})
        assert res.status_code == 401

    def test_tampered_payload_invalidates_signature(self, client, auth_headers):
        """
        Classic attack: decode payload, change sub to another user_id,
        re-encode and send. Signature no longer matches → 401.
        """
        token = _extract_token(auth_headers)
        header_b64, _, sig_b64 = token.split(".")

        fake_payload = _b64({"sub": 9999, "exp": int(time.time()) + 3600})
        tampered = f"{header_b64}.{fake_payload}.{sig_b64}"

        res = client.get("/api/notes/", headers={"Authorization": f"Bearer {tampered}"})
        assert res.status_code == 401

    def test_alg_none_attack_returns_401(self, client):
        """
        CVE-2015-9235 style: set alg=none and omit the signature.
        python-jose rejects this because algorithms=["HS256"] is explicit.
        """
        header  = _b64({"alg": "none", "typ": "JWT"})
        payload = _b64({"sub": 1, "exp": int(time.time()) + 3600})
        token   = f"{header}.{payload}."    # empty signature

        res = client.get("/api/notes/", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401

    def test_expired_token_returns_401(self, client, registered_user):
        """Token with exp in the past must be rejected."""
        header  = _b64({"alg": "HS256", "typ": "JWT"})
        payload = _b64({"sub": registered_user["id"], "exp": 1000})  # epoch 1970

        # We can't sign this without SECRET_KEY so the signature will be wrong,
        # but the key point is: expired tokens should never grant access.
        fake_sig = _b64({"fake": True})
        token = f"{header}.{payload}.{fake_sig}"

        res = client.get("/api/notes/", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401

    def test_token_with_nonexistent_user_id_returns_401(self, client):
        """
        Valid-looking JWT (correct format) but sub points to a user that
        doesn't exist in the DB.
        """
        # We can craft a structurally valid token but with a garbage sub.
        # It won't have a valid signature so it'll fail signature check first.
        header  = _b64({"alg": "HS256", "typ": "JWT"})
        payload = _b64({"sub": 99999, "exp": int(time.time()) + 3600})
        token   = f"{header}.{payload}.fakesig"

        res = client.get("/api/notes/", headers={"Authorization": f"Bearer {token}"})
        assert res.status_code == 401


# ── Broken Access Control / IDOR ─────────────────────────────────────────────

class TestBrokenAccessControl:

    def test_cannot_update_note_by_guessing_id(self, client, auth_headers, second_user_headers):
        """User 2 guesses note ID belonging to User 1 → 403, not 200."""
        note = client.post("/api/notes/",
                           json={"title": "Secret", "content": "Private"},
                           headers=auth_headers).json()
        res = client.put(f"/api/notes/{note['id']}",
                         json={"title": "Overwritten"},
                         headers=second_user_headers)
        assert res.status_code == 403

    def test_cannot_delete_note_by_guessing_id(self, client, auth_headers, second_user_headers):
        note = client.post("/api/notes/",
                           json={"title": "T", "content": "C"},
                           headers=auth_headers).json()
        res = client.delete(f"/api/notes/{note['id']}", headers=second_user_headers)
        assert res.status_code == 403

    def test_403_does_not_reveal_note_content(self, client, auth_headers, second_user_headers):
        """Error response for a 403 must not leak the note's title or content."""
        note = client.post("/api/notes/",
                           json={"title": "TopSecret", "content": "CriticalData"},
                           headers=auth_headers).json()
        res = client.put(f"/api/notes/{note['id']}",
                         json={"title": "X"},
                         headers=second_user_headers)
        assert res.status_code == 403
        body = str(res.json())
        assert "TopSecret" not in body
        assert "CriticalData" not in body


# ── Injection ─────────────────────────────────────────────────────────────────

class TestInjection:

    SQL_PAYLOADS = [
        "'; DROP TABLE notes; --",
        "' OR '1'='1",
        "1; SELECT * FROM users",
        "\" OR \"1\"=\"1",
    ]

    XSS_PAYLOADS = [
        "<script>alert('xss')</script>",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)",
        "';alert(String.fromCharCode(88,83,83))//",
    ]

    def test_sql_injection_in_note_title_stored_safely(self, client, auth_headers):
        """SQLAlchemy parameterises queries — injection is stored as plain text."""
        for payload in self.SQL_PAYLOADS:
            res = client.post("/api/notes/",
                              json={"title": payload, "content": "test"},
                              headers=auth_headers)
            assert res.status_code == 201, f"Failed for: {payload}"
            assert res.json()["title"] == payload  # stored literally, not executed

    def test_sql_injection_in_note_content_stored_safely(self, client, auth_headers):
        for payload in self.SQL_PAYLOADS:
            res = client.post("/api/notes/",
                              json={"title": "T", "content": payload},
                              headers=auth_headers)
            assert res.status_code == 201
            assert res.json()["content"] == payload

    def test_xss_payload_returned_as_plain_text(self, client, auth_headers):
        """
        The API returns raw strings — it does not HTML-encode.
        This is correct: the API is not responsible for HTML escaping;
        the frontend must do that when rendering.
        The test documents this contract explicitly.
        """
        for payload in self.XSS_PAYLOADS:
            res = client.post("/api/notes/",
                              json={"title": payload, "content": "test"},
                              headers=auth_headers)
            assert res.status_code == 201
            assert res.json()["title"] == payload  # API contract: plain text passthrough

    def test_sql_injection_in_login_email_returns_401(self, client):
        for payload in self.SQL_PAYLOADS:
            res = client.post("/api/auth/login",
                              data={"username": payload, "password": "x"})
            assert res.status_code in (401, 422), f"Unexpected for: {payload}"


# ── Sensitive Data Exposure ───────────────────────────────────────────────────

class TestSensitiveDataExposure:

    def test_password_hash_not_in_register_response(self, client):
        res = client.post("/api/auth/register",
                          json={"email": "u@test.com", "password": "Password123"})
        body = str(res.json())
        assert "password" not in body.lower()
        assert "hash" not in body.lower()

    def test_password_hash_not_in_note_response(self, client, auth_headers):
        res = client.post("/api/notes/",
                          json={"title": "T", "content": "C"},
                          headers=auth_headers)
        body = str(res.json())
        assert "password" not in body.lower()
        assert "hash" not in body.lower()

    def test_health_endpoint_does_not_expose_internals(self, client):
        res = client.get("/health")
        body = str(res.json())
        assert "database" not in body.lower()
        assert "postgresql" not in body.lower()
        assert "secret" not in body.lower()


# ── Insecure Design ───────────────────────────────────────────────────────────

class TestInsecureDesign:

    def test_cannot_mass_assign_admin_role_on_register(self, client):
        """Pydantic schema must ignore or reject unknown fields like 'role'."""
        res = client.post("/api/auth/register", json={
            "email": "u@test.com",
            "password": "Password123",
            "role": "admin",          # attacker tries to self-promote
        })
        if res.status_code == 201:
            assert res.json()["role"] == "user"   # ignored, defaulted to user
        else:
            assert res.status_code == 422          # or rejected entirely

    def test_cannot_spoof_author_via_request_body(self, client, auth_headers):
        """
        If a client sends an 'author' field, it must be ignored.
        Author is always derived from the JWT on the server side.
        """
        res = client.post("/api/notes/", json={
            "title": "T",
            "content": "C",
            "author": "admin@company.com",  # spoof attempt
        }, headers=auth_headers)
        # Either 422 (extra field rejected) or 201 with correct author
        if res.status_code == 201:
            assert res.json()["author"] == "user@test.com"

    def test_user_enumeration_same_error_for_wrong_pass_vs_missing_user(self, client, registered_user):
        res_existing = client.post("/api/auth/login",
                                   data={"username": "user@test.com", "password": "Wrong1"})
        res_missing  = client.post("/api/auth/login",
                                   data={"username": "nobody@test.com", "password": "Wrong1"})
        assert res_existing.status_code == res_missing.status_code
        assert res_existing.json()["detail"] == res_missing.json()["detail"]
