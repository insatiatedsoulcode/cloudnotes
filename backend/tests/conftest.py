"""
Test configuration and shared fixtures.

Architecture:
- A separate `cloudnotes_test` PostgreSQL DB is used — never touches dev data.
- Tables are created once per test session, then TRUNCATED between every test
  so each test starts from a clean, empty state.
- FastAPI's dependency injection is overridden to point at the test DB.
- All fixtures are function-scoped by default so tests are fully isolated.
"""

# Set env vars BEFORE any app module is imported.
# app/database.py reads DATABASE_URL at import time, so this must come first.
import os
os.environ.setdefault("DATABASE_URL", "postgresql://deepakkumarsingh@localhost:5432/cloudnotes")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("APP_ENV", "test")
# "memory://" tells slowapi to use in-memory rate limit storage (no real Redis needed).
# The cache layer is independently mocked with fakeredis via the fake_redis fixture.
os.environ.setdefault("REDIS_URL", "memory://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

import app.models  # noqa: F401 — registers all ORM models before create_all
from app.database import Base, get_db
from app.main import app

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://deepakkumarsingh@localhost:5432/cloudnotes_test",
)

_engine = create_engine(TEST_DB_URL)
_TestSession = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


# ── DB lifecycle ──────────────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def create_tables():
    """Create all tables once for the whole test run, then install the FTS trigger."""
    Base.metadata.create_all(bind=_engine)
    with _engine.connect() as conn:
        conn.execute(text("""
            CREATE OR REPLACE FUNCTION notes_search_vector_update() RETURNS trigger AS $$
            BEGIN
                NEW.search_vector :=
                    setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                    setweight(to_tsvector('english', coalesce(NEW.content, '')), 'B');
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
        """))
        conn.execute(text("""
            DROP TRIGGER IF EXISTS notes_search_vector_trigger ON notes
        """))
        conn.execute(text("""
            CREATE TRIGGER notes_search_vector_trigger
            BEFORE INSERT OR UPDATE ON notes
            FOR EACH ROW EXECUTE FUNCTION notes_search_vector_update()
        """))
        conn.commit()
    yield
    Base.metadata.drop_all(bind=_engine)


@pytest.fixture(autouse=True)
def clean_tables(create_tables):
    """
    Truncate every table before each test.
    RESTART IDENTITY resets auto-increment sequences so IDs start at 1 each time.
    CASCADE handles FK ordering automatically.
    """
    with _engine.connect() as conn:
        conn.execute(text(
            "TRUNCATE TABLE audit_logs, attachments, share_links, note_shares, refresh_tokens, email_verifications, notes, users RESTART IDENTITY CASCADE"
        ))
        conn.commit()


@pytest.fixture(autouse=True)
def fake_redis():
    """
    Replace the Redis cache client with fakeredis for every test.

    Why fakeredis?
    - No real Redis server needed in CI or when running tests offline.
    - Each test gets a fresh, empty store (flushall after yield).
    - Deterministic: no TTL races, no cross-test key bleed.

    How it works:
    - app/cache.py exposes override_for_testing() to swap the client.
    - fakeredis.FakeRedis is a pure-Python in-process Redis clone.
    """
    import fakeredis
    from app.cache import override_for_testing
    fake = fakeredis.FakeRedis(decode_responses=True)
    override_for_testing(fake)
    yield fake
    fake.flushall()
    override_for_testing(None)


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear in-memory rate limit counters before each test.

    Without this, a test that hits the login endpoint N times would exhaust
    the limit and cause unrelated tests to receive 429 responses.
    """
    from app.limiter import reset_limits
    reset_limits()
    yield
    reset_limits()


@pytest.fixture(autouse=True)
def mock_email():
    """
    Suppress real verification SMTP calls in every test.

    Patches send_verification_email at the call site (app.routers.auth).
    Tests that need to capture the token read:
        mock_email.call_args.kwargs["token"]
    """
    with patch("app.routers.auth.send_verification_email") as mock_fn:
        yield mock_fn


@pytest.fixture(autouse=True)
def mock_password_reset_email():
    """
    Suppress real password-reset SMTP calls in every test.

    Tests that need to capture the reset token read:
        mock_password_reset_email.call_args.kwargs["token"]
    """
    with patch("app.routers.auth.send_password_reset_email") as mock_fn:
        yield mock_fn


# ── Dependency override ───────────────────────────────────────────────────────

def _override_get_db():
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


# ── Helpers ───────────────────────────────────────────────────────────────────

def _auto_verify(user_id: int) -> None:
    """Directly set is_verified=True in the test DB — bypasses the email flow."""
    from app.models.user import User as UserModel
    db = _TestSession()
    user = db.query(UserModel).filter(UserModel.id == user_id).first()
    user.is_verified = True
    db.commit()
    db.close()


# ── Core fixtures ─────────────────────────────────────────────────────────────

@pytest.fixture
def client():
    """FastAPI TestClient — fires real HTTP through the full middleware stack."""
    return TestClient(app)


@pytest.fixture
def registered_user(client):
    """A freshly registered and auto-verified normal user.

    Auto-verification lets existing CRUD/cache/workspace tests work without
    each test going through the email flow.  Tests for the verification flow
    itself live in test_email_verification.py and work with the unverified state.
    """
    res = client.post("/api/auth/register", json={
        "email": "user@test.com",
        "password": "Password123",
    })
    assert res.status_code == 201, res.json()
    _auto_verify(res.json()["id"])
    return res.json()


@pytest.fixture
def auth_headers(client, registered_user):
    """Authorization header for the normal test user."""
    res = client.post("/api/auth/login",
                      data={"username": "user@test.com", "password": "Password123"})
    assert res.status_code == 200, res.json()
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_user_headers(client):
    """Authorization header for a second, different user (for ownership tests)."""
    res_reg = client.post("/api/auth/register", json={
        "email": "other@test.com",
        "password": "Password123",
    })
    _auto_verify(res_reg.json()["id"])
    res = client.post("/api/auth/login",
                      data={"username": "other@test.com", "password": "Password123"})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    """Authorization header for an admin user (created directly in the DB)."""
    from app.models.user import User
    from app.routers.auth import _hash

    db = _TestSession()
    admin = User(
        email="admin@test.com",
        password_hash=_hash("AdminPass123"),
        role="admin",
        is_verified=True,
    )
    db.add(admin)
    db.commit()
    db.close()

    res = client.post("/api/auth/login",
                      data={"username": "admin@test.com", "password": "AdminPass123"})
    assert res.status_code == 200, res.json()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
def db_session():
    """Direct DB session — for tests that need to insert rows with specific field values."""
    db = _TestSession()
    try:
        yield db
    finally:
        db.close()


def make_note(client, headers, title="Test note", content="Test content", visibility="private", tags=None):
    """Create a note via the API and return the response JSON."""
    body = {"title": title, "content": content, "visibility": visibility}
    if tags is not None:
        body["tags"] = tags
    res = client.post("/api/notes/", json=body, headers=headers)
    assert res.status_code == 201, res.json()
    return res.json()
