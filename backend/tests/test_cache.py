"""
F-03 Redis Cache tests.

Tests verify the cache-aside pattern:
  1. First request → DB hit → key written to Redis
  2. Second request → Redis hit → DB not queried
  3. Write (create/update/delete) → relevant keys evicted

The `fake_redis` autouse fixture in conftest.py replaces the Redis client
with an in-process fakeredis instance, so no real Redis is needed to run
these tests. Each test starts with an empty cache.
"""

from tests.conftest import make_note


class TestListCache:
    def test_first_list_request_populates_cache(self, client, auth_headers, fake_redis):
        """After GET /notes/, the list key must exist in Redis."""
        make_note(client, auth_headers, title="Cached note")

        # Clear any keys set by make_note's invalidation
        fake_redis.flushall()

        client.get("/api/notes/", headers=auth_headers)
        assert fake_redis.exists("notes:list:0:100") == 1

    def test_second_list_request_is_a_cache_hit(self, client, auth_headers, fake_redis):
        """Second GET /notes/ must return the same data as the first."""
        make_note(client, auth_headers, title="Note A")
        fake_redis.flushall()

        res1 = client.get("/api/notes/", headers=auth_headers)
        res2 = client.get("/api/notes/", headers=auth_headers)

        assert res1.status_code == 200
        assert res2.status_code == 200
        assert res1.json() == res2.json()

    def test_create_invalidates_list_cache(self, client, auth_headers, fake_redis):
        """POST /notes/ must evict all notes:list:* keys."""
        make_note(client, auth_headers, title="Existing")
        fake_redis.flushall()

        # Populate cache
        client.get("/api/notes/", headers=auth_headers)
        assert fake_redis.exists("notes:list:0:100") == 1

        # Write should evict
        client.post("/api/notes/",
                    json={"title": "New note", "content": "body"},
                    headers=auth_headers)
        assert fake_redis.exists("notes:list:0:100") == 0

    def test_delete_invalidates_list_cache(self, client, auth_headers, fake_redis):
        """DELETE /notes/{id} must evict all notes:list:* keys."""
        note = make_note(client, auth_headers)
        fake_redis.flushall()

        client.get("/api/notes/", headers=auth_headers)
        assert fake_redis.exists("notes:list:0:100") == 1

        client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
        assert fake_redis.exists("notes:list:0:100") == 0

    def test_update_invalidates_list_cache(self, client, auth_headers, fake_redis):
        """PUT /notes/{id} must evict all notes:list:* keys."""
        note = make_note(client, auth_headers)
        fake_redis.flushall()

        client.get("/api/notes/", headers=auth_headers)
        assert fake_redis.exists("notes:list:0:100") == 1

        client.put(f"/api/notes/{note['id']}",
                   json={"title": "Updated"},
                   headers=auth_headers)
        assert fake_redis.exists("notes:list:0:100") == 0

    def test_cache_returns_fresh_data_after_invalidation(self, client, auth_headers, fake_redis):
        """After create + next GET, the list must include the new note."""
        make_note(client, auth_headers, title="First")
        fake_redis.flushall()

        res_before = client.get("/api/notes/", headers=auth_headers)
        titles_before = [n["title"] for n in res_before.json()]

        client.post("/api/notes/",
                    json={"title": "Second", "content": "body"},
                    headers=auth_headers)

        res_after = client.get("/api/notes/", headers=auth_headers)
        titles_after = [n["title"] for n in res_after.json()]

        assert "Second" not in titles_before
        assert "Second" in titles_after


class TestDetailCache:
    def test_first_get_populates_detail_cache(self, client, auth_headers, fake_redis):
        """After GET /notes/{id}, the detail key must exist in Redis."""
        note = make_note(client, auth_headers)
        fake_redis.flushall()

        client.get(f"/api/notes/{note['id']}", headers=auth_headers)
        assert fake_redis.exists(f"notes:detail:{note['id']}") == 1

    def test_second_get_is_a_cache_hit(self, client, auth_headers, fake_redis):
        """Second GET /notes/{id} must return identical data."""
        note = make_note(client, auth_headers)
        fake_redis.flushall()

        res1 = client.get(f"/api/notes/{note['id']}", headers=auth_headers)
        res2 = client.get(f"/api/notes/{note['id']}", headers=auth_headers)

        assert res1.json() == res2.json()

    def test_update_invalidates_detail_cache(self, client, auth_headers, fake_redis):
        """PUT must evict the specific note's detail key."""
        note = make_note(client, auth_headers, title="Original")
        fake_redis.flushall()

        client.get(f"/api/notes/{note['id']}", headers=auth_headers)
        assert fake_redis.exists(f"notes:detail:{note['id']}") == 1

        client.put(f"/api/notes/{note['id']}",
                   json={"title": "Updated"},
                   headers=auth_headers)
        assert fake_redis.exists(f"notes:detail:{note['id']}") == 0

    def test_delete_invalidates_detail_cache(self, client, auth_headers, fake_redis):
        """DELETE must evict the specific note's detail key."""
        note = make_note(client, auth_headers)
        fake_redis.flushall()

        client.get(f"/api/notes/{note['id']}", headers=auth_headers)
        assert fake_redis.exists(f"notes:detail:{note['id']}") == 1

        client.delete(f"/api/notes/{note['id']}", headers=auth_headers)
        assert fake_redis.exists(f"notes:detail:{note['id']}") == 0

    def test_cache_returns_updated_data_after_invalidation(self, client, auth_headers, fake_redis):
        """After PUT + next GET, the response must reflect the new title."""
        note = make_note(client, auth_headers, title="Before")
        fake_redis.flushall()

        client.get(f"/api/notes/{note['id']}", headers=auth_headers)  # populate cache

        client.put(f"/api/notes/{note['id']}",
                   json={"title": "After"},
                   headers=auth_headers)

        res = client.get(f"/api/notes/{note['id']}", headers=auth_headers)
        assert res.json()["title"] == "After"

    def test_different_notes_have_independent_cache_keys(self, client, auth_headers, fake_redis):
        """Invalidating note 1 must not evict note 2's detail cache."""
        note1 = make_note(client, auth_headers, title="Note 1")
        note2 = make_note(client, auth_headers, title="Note 2")
        fake_redis.flushall()

        client.get(f"/api/notes/{note1['id']}", headers=auth_headers)
        client.get(f"/api/notes/{note2['id']}", headers=auth_headers)

        # Delete note1 — only note1's key should be evicted
        client.delete(f"/api/notes/{note1['id']}", headers=auth_headers)

        assert fake_redis.exists(f"notes:detail:{note1['id']}") == 0
        assert fake_redis.exists(f"notes:detail:{note2['id']}") == 1


class TestGracefulDegradation:
    def test_cache_miss_falls_through_to_db(self, client, auth_headers, fake_redis):
        """Even with an empty cache, GET /notes/ must return correct data from DB."""
        make_note(client, auth_headers, title="Persisted")
        fake_redis.flushall()  # empty cache, force DB hit

        res = client.get("/api/notes/", headers=auth_headers)
        assert res.status_code == 200
        assert any(n["title"] == "Persisted" for n in res.json())

    def test_404_not_cached(self, client, auth_headers, fake_redis):
        """A 404 response must not write anything to the cache."""
        client.get("/api/notes/99999", headers=auth_headers)
        # No key should have been written for a nonexistent note
        assert fake_redis.exists("notes:detail:99999") == 0
