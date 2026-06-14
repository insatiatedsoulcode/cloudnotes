"""
F-13: Note Tags tests.

- Tags are stored with notes and returned in responses.
- Tags are normalised to lowercase and deduplicated on write.
- GET /api/notes/?tag=X filters notes by tag.
- GET /api/tags/ returns tags with counts for the current user's notes.
- Tag filter respects the same visibility/ownership scoping as the note list.
"""

import pytest
from tests.conftest import make_note


# ── Tags stored and returned ──────────────────────────────────────────────────

def test_create_note_with_tags(client, auth_headers):
    note = make_note(client, auth_headers, tags=["cloud", "aws"])
    assert set(note["tags"]) == {"cloud", "aws"}


def test_create_note_without_tags_defaults_to_empty(client, auth_headers):
    note = make_note(client, auth_headers)
    assert note["tags"] == []


def test_tags_normalised_to_lowercase(client, auth_headers):
    note = make_note(client, auth_headers, tags=["Cloud", "AWS", "PYTHON"])
    assert set(note["tags"]) == {"cloud", "aws", "python"}


def test_tags_deduplicated_on_create(client, auth_headers):
    note = make_note(client, auth_headers, tags=["cloud", "Cloud", "CLOUD"])
    assert note["tags"] == ["cloud"]


def test_tags_whitespace_stripped(client, auth_headers):
    note = make_note(client, auth_headers, tags=["  cloud  ", " aws"])
    assert set(note["tags"]) == {"cloud", "aws"}


def test_tags_empty_strings_ignored(client, auth_headers):
    note = make_note(client, auth_headers, tags=["cloud", "", "   "])
    assert note["tags"] == ["cloud"]


def test_get_note_includes_tags(client, auth_headers):
    note = make_note(client, auth_headers, tags=["python", "fastapi"])
    res = client.get(f"/api/notes/{note['id']}", headers=auth_headers)
    assert res.status_code == 200
    assert set(res.json()["tags"]) == {"python", "fastapi"}


def test_list_notes_includes_tags(client, auth_headers):
    make_note(client, auth_headers, tags=["cloud"])
    res = client.get("/api/notes/", headers=auth_headers)
    assert res.status_code == 200
    assert any("cloud" in n["tags"] for n in res.json())


# ── Update tags ───────────────────────────────────────────────────────────────

def test_update_note_sets_tags(client, auth_headers):
    note = make_note(client, auth_headers, tags=["cloud"])
    res = client.put(f"/api/notes/{note['id']}", json={"tags": ["aws", "s3"]}, headers=auth_headers)
    assert res.status_code == 200
    assert set(res.json()["tags"]) == {"aws", "s3"}


def test_update_note_clears_tags(client, auth_headers):
    note = make_note(client, auth_headers, tags=["cloud", "aws"])
    res = client.put(f"/api/notes/{note['id']}", json={"tags": []}, headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["tags"] == []


def test_update_note_without_tags_field_preserves_tags(client, auth_headers):
    note = make_note(client, auth_headers, tags=["cloud"])
    res = client.put(f"/api/notes/{note['id']}", json={"title": "new title"}, headers=auth_headers)
    assert res.status_code == 200
    assert "cloud" in res.json()["tags"]


def test_update_tags_normalised(client, auth_headers):
    note = make_note(client, auth_headers)
    res = client.put(f"/api/notes/{note['id']}", json={"tags": ["AWS", "Cloud"]}, headers=auth_headers)
    assert res.status_code == 200
    assert set(res.json()["tags"]) == {"aws", "cloud"}


# ── Tag filter on list ────────────────────────────────────────────────────────

def test_filter_by_tag_returns_matching_notes(client, auth_headers):
    make_note(client, auth_headers, title="cloud note", tags=["cloud", "aws"])
    make_note(client, auth_headers, title="python note", tags=["python"])
    res = client.get("/api/notes/?tag=cloud", headers=auth_headers)
    assert res.status_code == 200
    titles = [n["title"] for n in res.json()]
    assert "cloud note" in titles
    assert "python note" not in titles


def test_filter_by_tag_case_insensitive(client, auth_headers):
    make_note(client, auth_headers, title="found", tags=["cloud"])
    res = client.get("/api/notes/?tag=CLOUD", headers=auth_headers)
    assert res.status_code == 200
    assert any(n["title"] == "found" for n in res.json())


def test_filter_by_tag_returns_empty_when_no_match(client, auth_headers):
    make_note(client, auth_headers, tags=["python"])
    res = client.get("/api/notes/?tag=cloud", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_filter_by_tag_respects_visibility_scope(client, auth_headers, second_user_headers):
    # Private note from user B — should not appear in user A's filtered list
    make_note(client, second_user_headers, title="other private", tags=["cloud"], visibility="private")
    make_note(client, auth_headers, title="my note", tags=["cloud"])
    res = client.get("/api/notes/?tag=cloud", headers=auth_headers)
    titles = [n["title"] for n in res.json()]
    assert "my note" in titles
    assert "other private" not in titles


# ── GET /api/tags/ ────────────────────────────────────────────────────────────

def test_list_tags_returns_counts(client, auth_headers):
    make_note(client, auth_headers, tags=["cloud", "aws"])
    make_note(client, auth_headers, tags=["cloud", "python"])
    make_note(client, auth_headers, tags=["python"])
    res = client.get("/api/tags/", headers=auth_headers)
    assert res.status_code == 200
    by_tag = {item["tag"]: item["count"] for item in res.json()}
    assert by_tag["cloud"] == 2
    assert by_tag["python"] == 2
    assert by_tag["aws"] == 1


def test_list_tags_empty_when_no_notes(client, auth_headers):
    res = client.get("/api/tags/", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_list_tags_excludes_other_users_notes(client, auth_headers, second_user_headers):
    make_note(client, second_user_headers, tags=["secret"])
    make_note(client, auth_headers, tags=["mine"])
    res = client.get("/api/tags/", headers=auth_headers)
    tags = [item["tag"] for item in res.json()]
    assert "mine" in tags
    assert "secret" not in tags


def test_list_tags_excludes_deleted_notes(client, auth_headers):
    note = make_note(client, auth_headers, tags=["deleted-tag"])
    client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
    res = client.get("/api/tags/", headers=auth_headers)
    tags = [item["tag"] for item in res.json()]
    assert "deleted-tag" not in tags


def test_list_tags_requires_auth(client):
    res = client.get("/api/tags/")
    assert res.status_code == 401


def test_list_tags_sorted_by_count_desc(client, auth_headers):
    make_note(client, auth_headers, tags=["rare"])
    make_note(client, auth_headers, tags=["common"])
    make_note(client, auth_headers, tags=["common"])
    make_note(client, auth_headers, tags=["common"])
    res = client.get("/api/tags/", headers=auth_headers)
    items = res.json()
    counts = [item["count"] for item in items]
    assert counts == sorted(counts, reverse=True)
