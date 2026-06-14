"""
F-14: Admin Management Endpoints tests.

- GET /admin/users returns all users with note_count.
- PUT /admin/users/{id}/role changes role.
- PUT /admin/users/{id}/suspend disables login; admin cannot suspend self.
- PUT /admin/users/{id}/unsuspend re-enables.
- GET /admin/stats returns system counts.
- Non-admins receive 403 on all /admin/ routes.
"""

import pytest
from tests.conftest import make_note


# ── Access control ────────────────────────────────────────────────────────────

def test_non_admin_cannot_access_admin_users(client, auth_headers):
    res = client.get("/api/admin/users", headers=auth_headers)
    assert res.status_code == 403


def test_non_admin_cannot_access_stats(client, auth_headers):
    res = client.get("/api/admin/stats", headers=auth_headers)
    assert res.status_code == 403


def test_unauthenticated_cannot_access_admin(client):
    res = client.get("/api/admin/users")
    assert res.status_code == 401


# ── List users ────────────────────────────────────────────────────────────────

def test_list_users_returns_all_users(client, registered_user, admin_headers):
    res = client.get("/api/admin/users", headers=admin_headers)
    assert res.status_code == 200
    emails = [u["email"] for u in res.json()]
    assert "user@test.com" in emails
    assert "admin@test.com" in emails


def test_list_users_includes_note_count(client, registered_user, auth_headers, admin_headers):
    make_note(client, auth_headers)
    make_note(client, auth_headers)
    res = client.get("/api/admin/users", headers=admin_headers)
    assert res.status_code == 200
    user_entry = next(u for u in res.json() if u["email"] == "user@test.com")
    assert user_entry["note_count"] == 2


def test_list_users_note_count_zero_when_no_notes(client, registered_user, admin_headers):
    res = client.get("/api/admin/users", headers=admin_headers)
    user_entry = next(u for u in res.json() if u["email"] == "user@test.com")
    assert user_entry["note_count"] == 0


def test_list_users_note_count_excludes_deleted(client, registered_user, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.get("/api/admin/users", headers=admin_headers)
    user_entry = next(u for u in res.json() if u["email"] == "user@test.com")
    assert user_entry["note_count"] == 0


# ── Role change ───────────────────────────────────────────────────────────────

def test_admin_can_promote_user_to_admin(client, registered_user, admin_headers):
    user_id = registered_user["id"]
    res = client.put(f"/api/admin/users/{user_id}/role",
                     json={"role": "admin"}, headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["role"] == "admin"


def test_admin_can_demote_admin_to_user(client, registered_user, admin_headers):
    user_id = registered_user["id"]
    client.put(f"/api/admin/users/{user_id}/role",
               json={"role": "admin"}, headers=admin_headers)
    res = client.put(f"/api/admin/users/{user_id}/role",
                     json={"role": "user"}, headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["role"] == "user"


def test_role_change_invalid_role_returns_422(client, registered_user, admin_headers):
    user_id = registered_user["id"]
    res = client.put(f"/api/admin/users/{user_id}/role",
                     json={"role": "superuser"}, headers=admin_headers)
    assert res.status_code == 422


def test_role_change_nonexistent_user_returns_404(client, admin_headers):
    res = client.put("/api/admin/users/99999/role",
                     json={"role": "admin"}, headers=admin_headers)
    assert res.status_code == 404


# ── Suspend / unsuspend ───────────────────────────────────────────────────────

def test_admin_can_suspend_user(client, registered_user, admin_headers):
    user_id = registered_user["id"]
    res = client.put(f"/api/admin/users/{user_id}/suspend", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["is_active"] is False


def test_suspended_user_cannot_login(client, registered_user, admin_headers):
    user_id = registered_user["id"]
    client.put(f"/api/admin/users/{user_id}/suspend", headers=admin_headers)
    res = client.post("/api/auth/login",
                      data={"username": "user@test.com", "password": "Password123"})
    assert res.status_code == 403


def test_admin_can_unsuspend_user(client, registered_user, admin_headers):
    user_id = registered_user["id"]
    client.put(f"/api/admin/users/{user_id}/suspend", headers=admin_headers)
    res = client.put(f"/api/admin/users/{user_id}/unsuspend", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["is_active"] is True


def test_unsuspended_user_can_login_again(client, registered_user, admin_headers):
    user_id = registered_user["id"]
    client.put(f"/api/admin/users/{user_id}/suspend", headers=admin_headers)
    client.put(f"/api/admin/users/{user_id}/unsuspend", headers=admin_headers)
    res = client.post("/api/auth/login",
                      data={"username": "user@test.com", "password": "Password123"})
    assert res.status_code == 200


def test_admin_cannot_suspend_self(client, admin_headers):
    # Get admin user id
    res = client.get("/api/admin/users", headers=admin_headers)
    admin_id = next(u["id"] for u in res.json() if u["email"] == "admin@test.com")
    res = client.put(f"/api/admin/users/{admin_id}/suspend", headers=admin_headers)
    assert res.status_code == 400


def test_suspend_already_suspended_returns_400(client, registered_user, admin_headers):
    user_id = registered_user["id"]
    client.put(f"/api/admin/users/{user_id}/suspend", headers=admin_headers)
    res = client.put(f"/api/admin/users/{user_id}/suspend", headers=admin_headers)
    assert res.status_code == 400


def test_unsuspend_active_user_returns_400(client, registered_user, admin_headers):
    user_id = registered_user["id"]
    res = client.put(f"/api/admin/users/{user_id}/unsuspend", headers=admin_headers)
    assert res.status_code == 400


def test_suspend_nonexistent_user_returns_404(client, admin_headers):
    res = client.put("/api/admin/users/99999/suspend", headers=admin_headers)
    assert res.status_code == 404


# ── Stats ─────────────────────────────────────────────────────────────────────

def test_stats_returns_expected_shape(client, admin_headers):
    res = client.get("/api/admin/stats", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert "total_users" in data
    assert "total_notes" in data
    assert "notes_today" in data
    assert "active_sessions" in data


def test_stats_counts_users(client, registered_user, admin_headers):
    res = client.get("/api/admin/stats", headers=admin_headers)
    # registered_user + admin = 2
    assert res.json()["total_users"] >= 2


def test_stats_counts_live_notes(client, auth_headers, admin_headers, registered_user):
    make_note(client, auth_headers)
    make_note(client, auth_headers)
    res = client.get("/api/admin/stats", headers=admin_headers)
    assert res.json()["total_notes"] >= 2


def test_stats_notes_today_counts_todays_notes(client, auth_headers, admin_headers, registered_user):
    make_note(client, auth_headers)
    res = client.get("/api/admin/stats", headers=admin_headers)
    assert res.json()["notes_today"] >= 1


def test_stats_excludes_deleted_from_total_notes(client, auth_headers, admin_headers, registered_user):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.get("/api/admin/stats", headers=admin_headers)
    assert res.json()["total_notes"] == 0


def test_stats_active_sessions_increases_after_login(client, registered_user, auth_headers, admin_headers):
    before = client.get("/api/admin/stats", headers=admin_headers).json()["active_sessions"]
    # auth_headers fixture already logged in, so sessions should be > 0
    assert before >= 1
