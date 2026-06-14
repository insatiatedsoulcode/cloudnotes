"""
F-17: Input Sanitization tests.

- title > 255 chars → 422
- content > 50,000 chars → 422
- Null byte in title → 422
- Control characters in title → 422
- password > 128 chars → 422
- email > 255 chars → 422
- Wrong Content-Type on JSON endpoint → 415
- Whitespace stripped from title
"""

import pytest


def _register(client, email="san@test.com", password="Password123"):
    res = client.post("/api/auth/register", json={"email": email, "password": password})
    return res


def _login(client, email="san@test.com", password="Password123"):
    res = client.post("/api/auth/login", data={"username": email, "password": password})
    return res


# ── Title length ──────────────────────────────────────────────────────────────

def test_title_max_255_chars_accepted(client, auth_headers):
    res = client.post("/api/notes/",
                      json={"title": "a" * 255, "content": "body"},
                      headers=auth_headers)
    assert res.status_code == 201


def test_title_256_chars_rejected(client, auth_headers):
    res = client.post("/api/notes/",
                      json={"title": "a" * 256, "content": "body"},
                      headers=auth_headers)
    assert res.status_code == 422


def test_title_whitespace_stripped(client, auth_headers):
    res = client.post("/api/notes/",
                      json={"title": "  hello  ", "content": "body"},
                      headers=auth_headers)
    assert res.status_code == 201
    assert res.json()["title"] == "hello"


def test_title_null_byte_rejected(client, auth_headers):
    res = client.post("/api/notes/",
                      json={"title": "bad\x00title", "content": "body"},
                      headers=auth_headers)
    assert res.status_code == 422


def test_title_control_char_rejected(client, auth_headers):
    res = client.post("/api/notes/",
                      json={"title": "bad\x01title", "content": "body"},
                      headers=auth_headers)
    assert res.status_code == 422


def test_title_newline_in_content_allowed(client, auth_headers):
    res = client.post("/api/notes/",
                      json={"title": "valid", "content": "line1\nline2\ttabbed"},
                      headers=auth_headers)
    assert res.status_code == 201


# ── Content length ────────────────────────────────────────────────────────────

def test_content_at_50000_chars_accepted(client, auth_headers):
    res = client.post("/api/notes/",
                      json={"title": "t", "content": "a" * 50_000},
                      headers=auth_headers)
    assert res.status_code == 201


def test_content_over_50000_chars_rejected(client, auth_headers):
    res = client.post("/api/notes/",
                      json={"title": "t", "content": "a" * 50_001},
                      headers=auth_headers)
    assert res.status_code == 422


def test_content_null_byte_rejected(client, auth_headers):
    res = client.post("/api/notes/",
                      json={"title": "t", "content": "bad\x00content"},
                      headers=auth_headers)
    assert res.status_code == 422


# ── Password length ───────────────────────────────────────────────────────────

def test_password_128_chars_accepted(client):
    res = _register(client, email="longpw@test.com", password="A" * 128)
    assert res.status_code == 201


def test_password_129_chars_rejected(client):
    res = _register(client, email="tolong@test.com", password="A" * 129)
    assert res.status_code == 422
    assert "128" in str(res.json())


def test_password_under_8_chars_rejected(client):
    res = _register(client, email="short@test.com", password="Abc123")
    assert res.status_code == 422


# ── Email length ──────────────────────────────────────────────────────────────

def test_email_max_255_accepted(client):
    # 243 chars local part + @x.com = 249 chars total — valid
    local = "a" * 243
    res = _register(client, email=f"{local}@x.com")
    assert res.status_code == 201


def test_email_over_255_rejected(client):
    local = "a" * 250
    res = _register(client, email=f"{local}@x.com")
    assert res.status_code == 422


# ── Content-Type enforcement ──────────────────────────────────────────────────

def test_wrong_content_type_on_post_returns_415(client):
    res = client.post(
        "/api/notes/",
        content=b'{"title":"t","content":"c"}',
        headers={"Content-Type": "text/plain", "Authorization": "Bearer fake"},
    )
    assert res.status_code == 415


def test_json_content_type_accepted(client, auth_headers):
    res = client.post(
        "/api/notes/",
        json={"title": "ct test", "content": "body"},
        headers=auth_headers,
    )
    assert res.status_code == 201


def test_form_content_type_not_rejected_by_middleware(client):
    # OAuth2 login uses application/x-www-form-urlencoded — must not be blocked.
    _register(client)
    from tests.conftest import _auto_verify, _TestSession
    from app.models.user import User
    db = _TestSession()
    u = db.query(User).filter(User.email == "san@test.com").first()
    u.is_verified = True
    db.commit()
    db.close()
    res = _login(client)
    assert res.status_code == 200


# ── Update validators mirror create validators ────────────────────────────────

def test_update_title_too_long_rejected(client, auth_headers):
    from tests.conftest import make_note
    note = make_note(client, auth_headers)
    res = client.put(f"/api/notes/{note['id']}",
                     json={"title": "x" * 256}, headers=auth_headers)
    assert res.status_code == 422


def test_update_content_null_byte_rejected(client, auth_headers):
    from tests.conftest import make_note
    note = make_note(client, auth_headers)
    res = client.put(f"/api/notes/{note['id']}",
                     json={"content": "bad\x00"}, headers=auth_headers)
    assert res.status_code == 422
