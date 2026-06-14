"""F-08: Full-Text Search, filtering, and sorting."""

from datetime import datetime, timedelta

from tests.conftest import make_note


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_note_with_date(db_session, user_id: int, title: str, content: str, created_at: datetime):
    """Insert a note directly with a specific created_at timestamp.

    The BEFORE INSERT trigger still fires, so search_vector is populated.
    """
    from app.models.note import Note as NoteModel
    note = NoteModel(
        title=title,
        content=content,
        author="user@test.com",
        owner_id=user_id,
        created_at=created_at,
        updated_at=created_at,
    )
    db_session.add(note)
    db_session.commit()
    db_session.refresh(note)
    return note


# ── Full-Text Search ──────────────────────────────────────────────────────────

class TestFullTextSearch:
    def test_search_by_title_keyword(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="Kubernetes Deployment Guide", content="Some generic content")
        make_note(client, auth_headers, title="Docker Basics", content="Container fundamentals")

        res = client.get("/api/notes/?q=kubernetes", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert "Kubernetes" in data[0]["title"]

    def test_search_by_content_keyword(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="Cloud Notes", content="This note covers prometheus monitoring setup")
        make_note(client, auth_headers, title="Random Note", content="Nothing special here")

        res = client.get("/api/notes/?q=prometheus", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert "prometheus" in data[0]["content"]

    def test_search_no_results(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="Note One", content="Content one")

        res = client.get("/api/notes/?q=xyznonexistent123", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_search_multiple_results(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="Terraform basics", content="Infrastructure as code with terraform")
        make_note(client, auth_headers, title="Terraform advanced", content="State management guide")
        make_note(client, auth_headers, title="Ansible guide", content="Configuration management")

        res = client.get("/api/notes/?q=terraform", headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()) == 2

    def test_empty_query_string_returns_all(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="Note A", content="content a")
        make_note(client, auth_headers, title="Note B", content="content b")

        res = client.get("/api/notes/?q=", headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()) == 2

    def test_search_rank_sort_title_beats_content(self, client, auth_headers, registered_user):
        # Title match (weight A) must outrank a content-only match (weight B)
        make_note(client, auth_headers, title="grafana dashboard setup", content="monitoring")
        make_note(client, auth_headers, title="metrics overview", content="using grafana for visualization")

        res = client.get("/api/notes/?q=grafana&sort=rank", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 2
        assert "grafana" in data[0]["title"].lower()

    def test_rank_sort_without_query_falls_back_to_created_at(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="First Note", content="first")
        make_note(client, auth_headers, title="Second Note", content="second")

        # sort=rank without q should not error — falls back to created_at desc
        res = client.get("/api/notes/?sort=rank&order=desc", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data[0]["title"] == "Second Note"


# ── Filters ───────────────────────────────────────────────────────────────────

class TestFilters:
    def test_filter_visibility_public(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="Private Note", content="secret", visibility="private")
        make_note(client, auth_headers, title="Public Note", content="open", visibility="public")

        res = client.get("/api/notes/?visibility=public", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["visibility"] == "public"

    def test_filter_visibility_private(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="Private Note", content="secret", visibility="private")
        make_note(client, auth_headers, title="Public Note", content="open", visibility="public")

        res = client.get("/api/notes/?visibility=private", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["visibility"] == "private"

    def test_filter_date_from_excludes_old_notes(self, client, auth_headers, registered_user, db_session):
        user_id = registered_user["id"]
        _create_note_with_date(db_session, user_id, "Old Note", "from last month",
                               datetime.utcnow() - timedelta(days=30))
        _create_note_with_date(db_session, user_id, "Recent Note", "from today",
                               datetime.utcnow())

        from_date = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")
        res = client.get(f"/api/notes/?from={from_date}", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["title"] == "Recent Note"

    def test_filter_date_to_excludes_future_notes(self, client, auth_headers, registered_user, db_session):
        user_id = registered_user["id"]
        _create_note_with_date(db_session, user_id, "Old Note", "from last month",
                               datetime.utcnow() - timedelta(days=30))
        _create_note_with_date(db_session, user_id, "Recent Note", "from today",
                               datetime.utcnow())

        to_date = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
        res = client.get(f"/api/notes/?to={to_date}", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["title"] == "Old Note"

    def test_filter_date_range(self, client, auth_headers, registered_user, db_session):
        user_id = registered_user["id"]
        _create_note_with_date(db_session, user_id, "Very Old", "ancient",
                               datetime.utcnow() - timedelta(days=60))
        _create_note_with_date(db_session, user_id, "Middle", "medium",
                               datetime.utcnow() - timedelta(days=15))
        _create_note_with_date(db_session, user_id, "Recent", "new",
                               datetime.utcnow())

        from_date = (datetime.utcnow() - timedelta(days=20)).strftime("%Y-%m-%d")
        to_date = (datetime.utcnow() - timedelta(days=5)).strftime("%Y-%m-%d")
        res = client.get(f"/api/notes/?from={from_date}&to={to_date}", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["title"] == "Middle"

    def test_search_combined_with_visibility(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="Private ansible note", content="private config", visibility="private")
        make_note(client, auth_headers, title="Public ansible guide", content="open config", visibility="public")

        res = client.get("/api/notes/?q=ansible&visibility=public", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert len(data) == 1
        assert data[0]["visibility"] == "public"


# ── Sorting ───────────────────────────────────────────────────────────────────

class TestSorting:
    def test_sort_created_at_desc_default(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="First Note", content="first")
        make_note(client, auth_headers, title="Second Note", content="second")

        res = client.get("/api/notes/", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data[0]["title"] == "Second Note"

    def test_sort_created_at_asc(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="First Note", content="first")
        make_note(client, auth_headers, title="Second Note", content="second")

        res = client.get("/api/notes/?sort=created_at&order=asc", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data[0]["title"] == "First Note"
        assert data[1]["title"] == "Second Note"

    def test_sort_updated_at(self, client, auth_headers, registered_user):
        n1 = make_note(client, auth_headers, title="First Note", content="first")
        make_note(client, auth_headers, title="Second Note", content="second")
        # Update the first note so it has a newer updated_at
        client.put(f"/api/notes/{n1['id']}", json={"content": "updated content"}, headers=auth_headers)

        res = client.get("/api/notes/?sort=updated_at&order=desc", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data[0]["title"] == "First Note"

    def test_unknown_sort_param_falls_back(self, client, auth_headers, registered_user):
        make_note(client, auth_headers, title="Note A", content="a")
        res = client.get("/api/notes/?sort=invalid_column", headers=auth_headers)
        assert res.status_code == 200


# ── Access control in search ──────────────────────────────────────────────────

class TestSearchAccessControl:
    def test_user_cannot_find_other_users_private_note(self, client, auth_headers, second_user_headers, registered_user):
        make_note(client, second_user_headers, title="Secret kubernetes note", content="confidential")

        res = client.get("/api/notes/?q=kubernetes", headers=auth_headers)
        assert res.status_code == 200
        assert res.json() == []

    def test_user_can_find_other_users_public_note(self, client, auth_headers, second_user_headers, registered_user):
        make_note(client, second_user_headers, title="Public kubernetes guide", content="open content", visibility="public")

        res = client.get("/api/notes/?q=kubernetes", headers=auth_headers)
        assert res.status_code == 200
        assert len(res.json()) == 1

    def test_admin_finds_all_notes_including_private(self, client, admin_headers, second_user_headers):
        make_note(client, second_user_headers, title="Private terraform note", content="confidential")

        res = client.get("/api/notes/?q=terraform", headers=admin_headers)
        assert res.status_code == 200
        assert len(res.json()) == 1

    def test_search_requires_auth(self, client):
        res = client.get("/api/notes/?q=anything")
        assert res.status_code == 401
