"""F-10: File attachment upload, listing, and deletion."""

import pytest
from unittest.mock import patch

from app.main import app
from app.storage import LocalStorage, get_storage
from tests.conftest import make_note

# Minimal valid magic-byte prefixes for each supported type.
_PNG  = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
_GIF  = b"GIF89a" + b"\x00" * 20
_PDF  = b"%PDF-1.4 test content"
_TXT  = b"Hello, this is plain text content."
_EXE  = b"MZ\x90\x00\x03\x00\x00\x00"   # PE magic — not in allowed list


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def temp_storage(tmp_path):
    """Override the storage dependency to write to a temp dir instead of ./uploads."""
    storage = LocalStorage(base_dir=str(tmp_path), base_url="http://testserver/uploads")
    app.dependency_overrides[get_storage] = lambda: storage
    yield storage
    del app.dependency_overrides[get_storage]


def _upload(client, headers, note_id, content, filename, content_type="application/octet-stream"):
    return client.post(
        f"/api/notes/{note_id}/attachments",
        files={"file": (filename, content, content_type)},
        headers=headers,
    )


# ── Upload ────────────────────────────────────────────────────────────────────

class TestUpload:
    def test_upload_png(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = _upload(client, auth_headers, note["id"], _PNG, "photo.png", "image/png")
        assert res.status_code == 201
        body = res.json()
        assert body["filename"] == "photo.png"
        assert body["content_type"] == "image/png"
        assert body["size_bytes"] == len(_PNG)
        assert "url" in body

    def test_upload_jpeg(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = _upload(client, auth_headers, note["id"], _JPEG, "image.jpg")
        assert res.status_code == 201
        assert res.json()["content_type"] == "image/jpeg"

    def test_upload_pdf(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = _upload(client, auth_headers, note["id"], _PDF, "doc.pdf", "application/pdf")
        assert res.status_code == 201
        assert res.json()["content_type"] == "application/pdf"

    def test_upload_text(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = _upload(client, auth_headers, note["id"], _TXT, "notes.txt", "text/plain")
        assert res.status_code == 201
        assert res.json()["content_type"] == "text/plain"

    def test_file_stored_on_disk(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        _upload(client, auth_headers, note["id"], _PNG, "photo.png")
        # At least one file should have been written under tmp_path
        files = list(temp_storage._base.rglob("*"))
        assert any(f.is_file() for f in files)

    def test_upload_unsupported_type_returns_422(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = _upload(client, auth_headers, note["id"], _EXE, "virus.exe", "application/octet-stream")
        assert res.status_code == 422

    def test_upload_too_large_returns_413(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        with patch("app.routers.attachments._MAX_SIZE_BYTES", 10):
            res = _upload(client, auth_headers, note["id"], b"x" * 11, "big.txt", "text/plain")
        assert res.status_code == 413

    def test_upload_to_nonexistent_note_returns_404(self, client, auth_headers, registered_user, temp_storage):
        res = _upload(client, auth_headers, 99999, _TXT, "file.txt")
        assert res.status_code == 404

    def test_non_owner_cannot_upload(self, client, auth_headers, second_user_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = _upload(client, second_user_headers, note["id"], _TXT, "file.txt")
        assert res.status_code == 403

    def test_upload_requires_auth(self, client, registered_user, temp_storage):
        note_id = 1
        res = client.post(f"/api/notes/{note_id}/attachments",
                          files={"file": ("f.txt", _TXT, "text/plain")})
        assert res.status_code == 401

    def test_filename_sanitized(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = _upload(client, auth_headers, note["id"], _TXT, "../../../etc/passwd")
        assert res.status_code == 201
        # Path traversal components must be stripped
        assert ".." not in res.json()["filename"]
        assert "/" not in res.json()["filename"]

    def test_gif_upload(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = _upload(client, auth_headers, note["id"], _GIF, "anim.gif", "image/gif")
        assert res.status_code == 201
        assert res.json()["content_type"] == "image/gif"

    def test_magic_bytes_checked_not_extension(self, client, auth_headers, registered_user, temp_storage):
        # EXE bytes renamed to .png — must be rejected despite the .png extension
        note = make_note(client, auth_headers)
        res = _upload(client, auth_headers, note["id"], _EXE, "disguised.png", "image/png")
        assert res.status_code == 422


# ── List ─────────────────────────────────────────────────────────────────────

class TestListAttachments:
    def test_list_returns_uploaded_files(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        _upload(client, auth_headers, note["id"], _PNG, "a.png")
        _upload(client, auth_headers, note["id"], _TXT, "b.txt")

        res = client.get(f"/api/notes/{note['id']}/attachments", headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()) == 2

    def test_list_empty_when_no_attachments(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = client.get(f"/api/notes/{note['id']}/attachments", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_shared_user_can_list_attachments(self, client, auth_headers, second_user_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        _upload(client, auth_headers, note["id"], _TXT, "shared.txt")
        client.post(f"/api/notes/{note['id']}/share",
                    json={"email": "other@test.com", "permission": "view"},
                    headers=auth_headers)

        res = client.get(f"/api/notes/{note['id']}/attachments", headers=second_user_headers)
        assert res.status_code == 200
        assert len(res.json()) == 1

    def test_unshared_user_cannot_list_attachments(self, client, auth_headers, second_user_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = client.get(f"/api/notes/{note['id']}/attachments", headers=second_user_headers)
        assert res.status_code == 403

    def test_list_response_has_url(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        _upload(client, auth_headers, note["id"], _PNG, "img.png")
        data = client.get(f"/api/notes/{note['id']}/attachments", headers=auth_headers).json()
        assert data[0]["url"].startswith("http")


# ── Delete ────────────────────────────────────────────────────────────────────

class TestDeleteAttachment:
    def test_owner_can_delete(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        att = _upload(client, auth_headers, note["id"], _TXT, "file.txt").json()

        res = client.delete(f"/api/notes/{note['id']}/attachments/{att['id']}", headers=auth_headers)
        assert res.status_code == 204

        listing = client.get(f"/api/notes/{note['id']}/attachments", headers=auth_headers).json()
        assert listing == []

    def test_delete_removes_file_from_storage(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        att = _upload(client, auth_headers, note["id"], _TXT, "file.txt").json()

        files_before = list(temp_storage._base.rglob("*"))
        assert any(f.is_file() for f in files_before)

        client.delete(f"/api/notes/{note['id']}/attachments/{att['id']}", headers=auth_headers)

        files_after = [f for f in temp_storage._base.rglob("*") if f.is_file()]
        assert len(files_after) == 0

    def test_non_owner_cannot_delete(self, client, auth_headers, second_user_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        att = _upload(client, auth_headers, note["id"], _TXT, "file.txt").json()

        res = client.delete(f"/api/notes/{note['id']}/attachments/{att['id']}", headers=second_user_headers)
        assert res.status_code == 403

    def test_delete_nonexistent_returns_404(self, client, auth_headers, registered_user, temp_storage):
        note = make_note(client, auth_headers)
        res = client.delete(f"/api/notes/{note['id']}/attachments/99999", headers=auth_headers)
        assert res.status_code == 404
