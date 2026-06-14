"""
F-11: Audit Log tests.

- note_create, note_update, note_delete actions are recorded.
- user_register and user_login actions are recorded.
- share_create and share_update actions are recorded.
- Admin audit-log endpoint returns entries and supports filters.
- Audit log entries survive even if business data is gone (append-only principle,
  but since we TRUNCATE between tests we just verify the row is created in the same tx).
"""

import pytest
from tests.conftest import make_note


# ── Note action audit entries ─────────────────────────────────────────────────

def test_create_note_logs_audit_entry(client, auth_headers, admin_headers):
    make_note(client, auth_headers, title="audit me")
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    assert res.status_code == 200
    actions = [e["action"] for e in res.json()]
    assert "note_create" in actions


def test_create_note_audit_has_resource_id(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    entries = [e for e in res.json() if e["action"] == "note_create"]
    assert any(e["resource_id"] == note["id"] for e in entries)


def test_update_note_logs_audit_entry(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    client.put(f"/api/notes/{note['id']}", json={"title": "updated"}, headers=auth_headers)
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    entries = [e for e in res.json() if e["action"] == "note_update"]
    assert any(e["resource_id"] == note["id"] for e in entries)


def test_update_note_audit_captures_before_after(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers, title="old title")
    client.put(f"/api/notes/{note['id']}", json={"title": "new title"}, headers=auth_headers)
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    entries = [e for e in res.json() if e["action"] == "note_update" and e["resource_id"] == note["id"]]
    assert entries
    details = entries[0]["details"]
    assert "before" in details
    assert "after" in details
    assert details["before"]["title"] == "old title"
    assert details["after"]["title"] == "new title"


def test_delete_note_logs_audit_entry(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    entries = [e for e in res.json() if e["action"] == "note_delete"]
    assert any(e["resource_id"] == note["id"] for e in entries)


def test_restore_note_logs_audit_entry(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    client.post(f"/api/admin/notes/{note['id']}/restore", headers=admin_headers)
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    actions = [e["action"] for e in res.json()]
    assert "note_restore" in actions


# ── Auth action audit entries ─────────────────────────────────────────────────

def test_register_logs_audit_entry(client, registered_user, admin_headers):
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    actions = [e["action"] for e in res.json()]
    assert "user_register" in actions


def test_login_logs_audit_entry(client, auth_headers, admin_headers):
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    actions = [e["action"] for e in res.json()]
    assert "user_login" in actions


# ── Share action audit entries ────────────────────────────────────────────────

def test_share_create_logs_audit_entry(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    client.post("/api/auth/register", json={"email": "share_target@test.com", "password": "Password123"})
    client.post(
        f"/api/notes/{note['id']}/share",
        json={"email": "share_target@test.com", "permission": "view"},
        headers=auth_headers,
    )
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    actions = [e["action"] for e in res.json()]
    assert "share_create" in actions


def test_share_update_logs_audit_entry(client, auth_headers, admin_headers):
    note = make_note(client, auth_headers)
    client.post("/api/auth/register", json={"email": "share2@test.com", "password": "Password123"})
    # First share (creates share_create entry)
    client.post(f"/api/notes/{note['id']}/share",
                json={"email": "share2@test.com", "permission": "view"}, headers=auth_headers)
    # Second share with same user (creates share_update entry)
    client.post(f"/api/notes/{note['id']}/share",
                json={"email": "share2@test.com", "permission": "edit"}, headers=auth_headers)
    res = client.get("/api/admin/audit-logs", headers=admin_headers)
    actions = [e["action"] for e in res.json()]
    assert "share_update" in actions


# ── Admin audit-log filters ───────────────────────────────────────────────────

def test_audit_log_filter_by_action(client, auth_headers, admin_headers):
    make_note(client, auth_headers)
    res = client.get("/api/admin/audit-logs?action=note_create", headers=admin_headers)
    assert res.status_code == 200
    for entry in res.json():
        assert entry["action"] == "note_create"


def test_audit_log_filter_by_user_id(client, registered_user, auth_headers, admin_headers):
    make_note(client, auth_headers)
    user_id = registered_user["id"]
    res = client.get(f"/api/admin/audit-logs?user_id={user_id}", headers=admin_headers)
    assert res.status_code == 200
    for entry in res.json():
        assert entry["user_id"] == user_id


def test_audit_log_pagination(client, auth_headers, admin_headers):
    for i in range(3):
        make_note(client, auth_headers, title=f"note {i}")
    res = client.get("/api/admin/audit-logs?skip=0&limit=2", headers=admin_headers)
    assert res.status_code == 200
    assert len(res.json()) <= 2


def test_audit_log_requires_admin(client, auth_headers):
    res = client.get("/api/admin/audit-logs", headers=auth_headers)
    assert res.status_code == 403
