# Software Requirements Specification — CloudNotes

**Version:** 2.0  
**Date:** 2026-06-14  
**Status:** Pre-Docker Feature Expansion Phase

---

## 1. Purpose

This document specifies the features and technical concepts to implement in CloudNotes **before** introducing Docker, cloud hosting, or infrastructure tooling. The goal is to build a production-grade application core — auth hardening, caching, rate limiting, search, file handling, audit trails — so that when Docker and cloud deployment arrive, they wrap a complete product rather than a skeleton.

Each feature is rated on:
- **Priority:** P0 (must-have), P1 (high-value), P2 (good-to-have)
- **Complexity:** Low / Medium / High
- **Cloud Relevance:** how this concept maps to a real cloud engineering concern

---

## 2. Current State (Baseline)

| Capability | Status |
|---|---|
| User registration + login (JWT) | Done |
| CRUD notes | Done |
| RBAC (user / admin roles) | Done |
| Structured logging | Done |
| TDD + SSDLC test suite (66 tests) | Done |
| Database migrations (Alembic) | Missing |
| Rate limiting | Missing |
| Redis cache | Missing |
| Email verification | Missing |
| Password reset | Missing |
| Note search | Missing |
| Note sharing | Missing |
| File attachments | Missing |
| Soft deletes + audit trail | Missing |
| Token refresh | Missing |
| Admin management endpoints | Missing |
| Background tasks | Missing |

---

## 3. Feature Specifications

---

### F-01 · Database Migrations (Alembic)

**Priority:** P0  
**Complexity:** Low  
**Cloud Relevance:** Every cloud DB change (RDS, Cloud SQL, Supabase) needs migrations. `create_all()` destroys data on schema changes.

**Problem:**  
The app currently calls `Base.metadata.create_all()` at startup. This works once, but if you add a column, drop a column, or rename a table, you must drop and recreate everything — losing all data.

**Requirements:**
- Replace `create_all()` at startup with Alembic's migration runner
- Create initial migration from current schema (User + Note tables)
- Each schema change produces a versioned migration file (e.g., `0001_add_tags_to_notes.py`)
- Migrations run automatically on app startup in non-prod; manually in prod via CLI command
- Migration files committed to git — schema history becomes part of code history

**Key Concepts Learned:**
- Alembic `upgrade head` / `downgrade -1`
- `env.py` — how Alembic connects to the database
- Auto-generate vs. hand-written migrations
- Why you never alter a live column without a migration

**Acceptance Criteria:**
- `alembic upgrade head` brings a blank DB to current schema
- Adding a new column works without wiping existing data
- Test suite still passes with Alembic-managed schema

---

### F-02 · Rate Limiting

**Priority:** P0  
**Complexity:** Medium  
**Cloud Relevance:** AWS WAF, Cloudflare, API Gateway — all implement rate limiting at infra level. Understanding it in-app first makes infra-level config intuitive.

**Problem:**  
Currently an attacker can call `POST /api/auth/login` thousands of times per second — brute-forcing passwords with no friction.

**Requirements:**
- Library: `slowapi` (FastAPI-native, built on `limits`)
- Rate limit login endpoint: **5 requests per minute per IP**
- Rate limit register endpoint: **3 requests per minute per IP**
- Rate limit notes write endpoints (POST/PUT/DELETE): **30 per minute per user**
- All other endpoints: **60 per minute per IP** global default
- On limit exceeded: return `429 Too Many Requests` with `Retry-After` header
- Limits stored in-memory (no Redis yet — Redis is F-03)
- Custom error handler so 429 returns JSON, not HTML

**Key Concepts Learned:**
- Token bucket vs. sliding window vs. fixed window algorithms
- IP-based vs. user-based limits
- `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `Retry-After` headers
- Why limits need a distributed store (Redis) once you scale past one server

**Acceptance Criteria:**
- 6th login attempt within 1 minute from same IP returns 429
- Response body: `{ "detail": "Rate limit exceeded. Try again in 60 seconds." }`
- Tests: `test_login_rate_limit_returns_429_on_sixth_attempt`

---

### F-03 · Redis Cache

**Priority:** P1  
**Complexity:** Medium  
**Cloud Relevance:** ElastiCache (AWS), Memorystore (GCP), Upstash (serverless Redis) — caching is the most common scaling lever used before adding more DB replicas.

**Problem:**  
Every `GET /api/notes/` hits PostgreSQL, even if data hasn't changed. At scale this creates unnecessary DB load.

**Sub-features:**

#### F-03a · Cache Note List
- Cache the result of `GET /api/notes/?skip=0&limit=100` for **30 seconds**
- Cache key: `notes:list:skip={skip}:limit={limit}`
- On any note write (POST/PUT/DELETE), invalidate all `notes:list:*` keys
- Cache miss → hit DB → store in Redis → return response
- Cache hit → return from Redis directly

#### F-03b · Cache Individual Notes
- Cache `GET /api/notes/{note_id}` for **5 minutes**
- Cache key: `notes:detail:{note_id}`
- Invalidate on update or delete of that specific note

#### F-03c · Redis for Rate Limiting (upgrade F-02)
- Once Redis is running, move `slowapi` backend from in-memory to Redis
- This makes rate limits consistent across multiple app instances (critical for horizontal scaling)

**Library:** `redis-py` (async via `redis.asyncio`)  
**Local Setup:** `redis:7-alpine` added to `docker-compose.yml` (later)  
**Config:** Add `REDIS_URL` to `Settings` (default: `redis://localhost:6379`)

**Key Concepts Learned:**
- Cache invalidation strategies (TTL vs. explicit invalidation)
- Cache-aside pattern vs. write-through vs. write-behind
- Why in-memory cache breaks with multiple instances (cache coherence)
- Redis data structures: strings, sets, hashes

**Acceptance Criteria:**
- First request hits DB; subsequent requests within TTL return cached result
- After POST /notes/, next GET /notes/ hits DB again (cache invalidated)
- Tests mock Redis client using `fakeredis`
- `test_note_list_returned_from_cache_on_second_request`

---

### F-04 · User Workspace Separation

**Priority:** P0  
**Complexity:** Low  
**Cloud Relevance:** Multi-tenancy is a core SaaS pattern. Understanding row-level security before you need it prevents data leaks in production.

**Problem:**  
Currently `GET /api/notes/` returns every note from every user. User A can read User B's notes. This is wrong for any real application.

**Requirements:**

#### F-04a · Scoped Note List (My Notes)
- `GET /api/notes/` returns only notes owned by the requesting user
- Admin users still see all notes
- Add `GET /api/admin/notes/` for admin-only global list

#### F-04b · Note Visibility Model
- Add `visibility` field to Note model: `"private"` (default) or `"public"`
- `private`: only owner and admin can read, update, delete
- `public`: all authenticated users can read; only owner and admin can write
- Migration: add `visibility` column with default `"private"`

#### F-04c · User Profile Endpoint
- `GET /api/users/me` — returns current user's profile
- `PUT /api/users/me` — update email (requires password confirmation)
- `DELETE /api/users/me` — soft-delete account (sets `is_active=False`)

**Key Concepts Learned:**
- Row-level security (RLS) — PostgreSQL can enforce this at DB level too
- Multi-tenancy: separate data per tenant within shared DB
- Data isolation vs. access control (different problems)

**Acceptance Criteria:**
- User A cannot see User B's private notes
- User A can see User B's public notes
- Admin can see all notes via `/api/admin/notes/`
- Tests verify cross-user isolation

---

### F-05 · Email Verification

**Priority:** P1  
**Complexity:** Medium  
**Cloud Relevance:** SES (AWS), SendGrid, Mailgun — transactional email is a standard cloud service. Learning to integrate it here prepares you for cloud email config.

**Problem:**  
Anyone can register with `fake@nobody.com` — no proof of email ownership.

**Requirements:**
- On register: generate a 32-byte random token, store it in DB (or Redis with TTL), send verification email
- Add `is_verified` (Boolean, default=False) field to User model
- `GET /api/auth/verify?token=<token>` — marks user as verified
- Unverified users: can login but see a warning; cannot create notes until verified
- Token expires in 24 hours
- `POST /api/auth/resend-verification` — resend the email (rate limited: 1 per 5 minutes)

**Email Backend:**
- Local dev: `MailHog` (SMTP mock, web UI at :8025) — runs in Docker
- Production: Pluggable via `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS` env vars
- Library: Python `smtplib` + `email.mime` or `fastapi-mail`

**Key Concepts Learned:**
- Transactional email vs. marketing email
- SMTP vs. API-based email services
- Token-based verification (same pattern as password reset, OAuth callback)
- Why you never store verification tokens in plain text

**Acceptance Criteria:**
- Register → email sent to MailHog
- Click link → `is_verified` set to True
- Unverified user gets `403: Please verify your email before creating notes`

---

### F-06 · Password Reset Flow

**Priority:** P1  
**Complexity:** Medium  
**Cloud Relevance:** Same infrastructure as F-05 (email service). Common pattern in every production app.

**Requirements:**
- `POST /api/auth/forgot-password` — accepts `{ email }`, sends reset email if user exists (always returns 200 for user enumeration resistance)
- Reset link: `https://app.example.com/reset-password?token=<token>`
- `POST /api/auth/reset-password` — accepts `{ token, new_password }`, validates token, updates password hash
- Token: 32-byte random, stored in Redis with 1-hour TTL
- Token is single-use: delete from Redis after successful reset
- Rate limit: 3 reset requests per email per hour

**Key Concepts Learned:**
- Stateful tokens vs. JWT (reset tokens must be revocable — use Redis/DB, not JWT)
- Why reset tokens must be single-use
- Secure token generation (`secrets.token_urlsafe(32)`)
- User enumeration resistance in account recovery

**Acceptance Criteria:**
- `POST /forgot-password` always returns `{ "message": "If that email exists, a reset link was sent" }`
- Token expires after 1 hour
- Token cannot be used twice

---

### F-07 · Refresh Token (Token Rotation)

**Priority:** P1  
**Complexity:** Medium  
**Cloud Relevance:** Cognito, Auth0, Keycloak all implement access + refresh token pairs. Understanding the pattern helps when integrating managed auth services.

**Problem:**  
Current JWT expires in 60 minutes. User gets logged out mid-work. Extending expiry increases risk if token is stolen.

**Requirements:**
- On login: issue two tokens:
  - **Access token:** short-lived (15 minutes), JWT, used for API calls
  - **Refresh token:** long-lived (30 days), opaque random string, stored in DB
- `POST /api/auth/refresh` — accepts refresh token in HTTP-only cookie, returns new access + refresh tokens (rotation)
- `POST /api/auth/logout` — deletes refresh token from DB (true logout)
- Refresh tokens stored in `refresh_tokens` table: `(id, user_id, token_hash, created_at, expires_at, revoked)`
- On suspicious activity (token reuse after rotation), revoke all refresh tokens for that user

**Key Concepts Learned:**
- Why access tokens should be short-lived
- Refresh token rotation and reuse detection
- HTTP-only cookies vs. localStorage (HttpOnly prevents XSS token theft)
- True server-side logout (stateless JWT cannot be revoked — only refresh tokens can)

**Acceptance Criteria:**
- Access token expires in 15 min; refresh token in 30 days
- `/refresh` with valid refresh token → new token pair, old refresh token invalidated
- `/logout` → refresh token deleted, subsequent `/refresh` returns 401

---

### F-08 · Full-Text Search

**Priority:** P1  
**Complexity:** Medium  
**Cloud Relevance:** OpenSearch (AWS), Elasticsearch, Typesense — search is a standalone service at cloud scale. Building it in PostgreSQL first teaches you what to offload later.

**Requirements:**

#### F-08a · PostgreSQL Full-Text Search
- `GET /api/notes/?q=kubernetes` — filters notes by search term
- Use PostgreSQL `tsvector` + `tsquery` for indexed full-text search
- Search across `title` and `content` fields (weighted: title matches rank higher)
- Migration: add `search_vector` computed column of type `tsvector`
- Index: `GIN` index on `search_vector`
- Trigger: update `search_vector` on INSERT/UPDATE

#### F-08b · Filter & Sort
- `GET /api/notes/?sort=updated_at&order=desc` — sort by field
- `GET /api/notes/?from=2026-01-01&to=2026-06-01` — date range filter
- `GET /api/notes/?visibility=public` — filter by visibility

**Key Concepts Learned:**
- `tsvector` / `tsquery` — PostgreSQL's native FTS
- GIN index vs. GiST index trade-offs
- Why FTS moves to a dedicated service (Elasticsearch) at scale: relevance tuning, fuzzy matching, multi-language stemming
- Pagination with cursor vs. offset (cursor is needed for real-time data)

**Acceptance Criteria:**
- `?q=docker` returns notes with "docker" in title or content
- Results ranked by relevance (title match > content match)
- `test_search_returns_relevant_notes`
- `test_search_with_no_results_returns_empty_list`

---

### F-09 · Note Sharing (Collaboration)

**Priority:** P2  
**Complexity:** High  
**Cloud Relevance:** IAM policies, resource-level permissions, share links (presigned URLs concept).

**Requirements:**

#### F-09a · Share with Specific Users
- `POST /api/notes/{note_id}/share` — accepts `{ email, permission: "view" | "edit" }`
- Creates a `note_shares` table: `(note_id, shared_with_user_id, permission, created_at)`
- Shared notes appear in the recipient's note list with a "Shared with me" label

#### F-09b · Public Share Links
- `POST /api/notes/{note_id}/share-link` — generates a public URL with a random token
- `GET /api/notes/shared/{token}` — returns note without authentication required
- Link expires after 7 days or can be revoked
- Concept mirror: AWS S3 presigned URLs

**Key Concepts Learned:**
- Resource-level permissions vs. role-level permissions
- Access control lists (ACL) — the pattern behind S3 bucket policies
- Presigned URL concept (time-limited access without credentials)

---

### F-10 · File Attachments (Local Storage First)

**Priority:** P1  
**Complexity:** Medium  
**Cloud Relevance:** Direct preparation for S3. Local filesystem first, then swap the storage backend.

**Requirements:**
- `POST /api/notes/{note_id}/attachments` — upload a file (multipart/form-data)
- Supported types: images (jpg, png, gif), PDFs, text files
- Max size: 10 MB
- Files stored at `./uploads/{note_id}/{filename}` (local dev)
- `GET /api/notes/{note_id}/attachments` — list attachments
- `DELETE /api/notes/{note_id}/attachments/{file_id}` — delete
- `attachments` table: `(id, note_id, filename, content_type, size_bytes, storage_path, created_at)`
- Storage backend abstracted behind a `StorageService` interface so swapping to S3 later changes only the implementation

**Storage Interface:**
```python
class StorageBackend(Protocol):
    def save(self, key: str, data: bytes, content_type: str) -> str: ...
    def get_url(self, key: str) -> str: ...
    def delete(self, key: str) -> None: ...

class LocalStorage(StorageBackend): ...   # current
class S3Storage(StorageBackend): ...      # future (F-10b)
```

**Key Concepts Learned:**
- Multipart form uploads vs. JSON
- Storage abstraction pattern (swap backend without changing business logic)
- MIME type validation (server-side, not just extension check)
- Why you never store binary data in PostgreSQL at scale

**Acceptance Criteria:**
- Upload PNG → stored in `./uploads/`, URL returned
- Upload file > 10 MB → 413 Payload Too Large
- Upload `.exe` → 422 Unsupported file type
- Swapping to S3 requires only changing `STORAGE_BACKEND=s3` env var

---

### F-11 · Soft Deletes + Audit Trail

**Priority:** P1  
**Complexity:** Low  
**Cloud Relevance:** Compliance, GDPR, SOC2 — audit logs are required in regulated environments. CloudTrail (AWS) does this at infra level; your app needs its own app-level audit trail.

**Requirements:**

#### F-11a · Soft Deletes
- Add `deleted_at` (nullable DateTime) to Note model
- `DELETE /api/notes/{note_id}` sets `deleted_at = now()` instead of removing the row
- All queries filter `WHERE deleted_at IS NULL` by default
- `GET /api/admin/notes/trash` — admin can view deleted notes
- `POST /api/admin/notes/{note_id}/restore` — admin can restore a deleted note
- Hard delete after 30 days (background job — see F-12)

#### F-11b · Audit Log
- New table: `audit_logs(id, user_id, action, resource_type, resource_id, metadata JSONB, ip_address, created_at)`
- Log every write action: register, login, note_create, note_update, note_delete, share_create, password_reset
- `metadata` stores before/after snapshot for updates
- `GET /api/admin/audit-logs` — admin-only, paginated, filterable by user/action/date

**Key Concepts Learned:**
- Soft vs. hard delete trade-offs (recoverability vs. storage growth)
- Append-only audit tables (never update or delete audit rows)
- JSONB in PostgreSQL for semi-structured data
- Why audit tables need their own retention policy

**Acceptance Criteria:**
- DELETE note → row still in DB with `deleted_at` set
- GET /notes/ excludes deleted notes
- Every write action creates an audit_log row
- `test_deleted_note_not_in_list`
- `test_audit_log_created_on_note_delete`

---

### F-12 · Background Tasks

**Priority:** P1  
**Complexity:** Medium  
**Cloud Relevance:** SQS + Lambda, Celery + Redis, AWS Batch — background work is a fundamental cloud pattern. Start simple, understand why you need a queue.

**Requirements:**

#### F-12a · In-Process Background Tasks (FastAPI BackgroundTasks)
Use FastAPI's built-in `BackgroundTasks` for:
- Sending verification emails (fire-and-forget after register response)
- Sending password reset emails (fire-and-forget)
- Logging audit events asynchronously (don't block the response)

#### F-12b · Scheduled Jobs (APScheduler)
- Hard delete notes where `deleted_at < now() - 30 days` — runs nightly at 2 AM
- Expire unused share links — runs hourly
- Purge expired refresh tokens — runs daily

**Library:** `apscheduler` with `AsyncIOScheduler`

**Key Concepts Learned:**
- Why in-process background tasks don't survive crashes (need a queue)
- APScheduler vs. cron vs. AWS EventBridge Scheduler
- The "at-least-once" delivery problem (why queues use acknowledgements)
- When to move from in-process tasks to a message queue (Celery + Redis / SQS)

**Acceptance Criteria:**
- Register → response returns immediately; email sent 0-2 seconds later
- Scheduler logs `"Cleaned 3 expired notes"` each night
- `test_email_sent_in_background_after_register`

---

### F-13 · Note Tags and Categories

**Priority:** P2  
**Complexity:** Low  
**Cloud Relevance:** Data modeling concept; tags stored as PostgreSQL arrays demonstrate non-relational patterns within relational DB.

**Requirements:**
- Add `tags` column to Note model: `ARRAY(String)` in PostgreSQL
- `POST /api/notes/` accepts `{ title, content, tags: ["cloud", "aws"] }`
- `GET /api/notes/?tag=cloud` — filter notes by tag
- `GET /api/tags/` — return all tags used by the current user with counts
- Tags are free-form strings (no separate Tags table for now)
- Tags indexed with GIN index for fast `@>` (array contains) queries

**Key Concepts Learned:**
- PostgreSQL array type vs. normalised many-to-many table
- GIN index for array/JSONB columns
- When arrays are acceptable (small, simple) vs. when to normalise

---

### F-14 · Admin Management Endpoints

**Priority:** P1  
**Complexity:** Low  
**Cloud Relevance:** Operational tooling. Every cloud system needs an admin plane separate from the data plane.

**Requirements:**
- All endpoints under `/api/admin/` require `role == "admin"` (via `require_admin` dependency)
- `GET /api/admin/users/` — list all users (id, email, role, is_verified, is_active, note_count, created_at)
- `PUT /api/admin/users/{user_id}/role` — change user role (user ↔ admin)
- `PUT /api/admin/users/{user_id}/suspend` — set `is_active=False` (user cannot login)
- `PUT /api/admin/users/{user_id}/unsuspend` — re-enable
- `GET /api/admin/stats` — system stats: total users, total notes, notes today, active sessions
- `GET /api/admin/audit-logs/` — paginated audit log (from F-11b)
- Admin cannot suspend themselves

**Key Concepts Learned:**
- Control plane vs. data plane separation
- Why admin endpoints need a separate auth check, not just role-in-JWT (JWT could be stale)
- Operational dashboards (precursor to CloudWatch Dashboards / Grafana)

**Acceptance Criteria:**
- Admin can suspend user → suspended user gets 403 on login
- Non-admin hitting `/api/admin/` routes gets 403
- Admin cannot suspend their own account

---

### F-15 · Structured JSON Logging (Log Levels per Environment)

**Priority:** P0  
**Complexity:** Low  
**Cloud Relevance:** CloudWatch Logs Insights, Datadog, Loki — all ingest JSON logs. Human-readable logs at `DEBUG` level, JSON logs in production.

**Problem:**  
Current logging uses text format (`%(asctime)s %(levelname)s [%(name)s] %(message)s`). CloudWatch works much better with JSON.

**Requirements:**
- Add `LOG_FORMAT` env var: `"text"` (default, current) or `"json"`
- JSON log fields: `timestamp`, `level`, `logger`, `message`, `request_id`, `user_id`, `duration_ms`, `status_code`
- Add request ID: generate UUID per request in middleware, attach to all log lines during that request (using `contextvars.ContextVar`)
- Library: `python-json-logger`
- Log levels:
  - `local/dev`: DEBUG
  - `test`: WARNING (suppressed by pytest)
  - `production`: INFO

**Key Concepts Learned:**
- Structured logging vs. text logs for machine parsing
- Correlation IDs / request IDs — essential for tracing across microservices
- `contextvars.ContextVar` — thread-safe per-request state in async Python
- Log levels as an operational dial (DEBUG → INFO → WARNING → ERROR)

**Acceptance Criteria:**
- With `LOG_FORMAT=json`: each line is valid JSON
- Request ID present in all log lines for that request
- `test_health_log_contains_request_id`

---

### F-16 · API Versioning

**Priority:** P1  
**Complexity:** Low  
**Cloud Relevance:** API Gateway versioning, blue/green deployments — you cannot change APIs without versioning once external clients exist.

**Requirements:**
- Move all routes under `/api/v1/` prefix
- Add `Accept-Version` header support as alternative
- Keep `/api/` as alias for `/api/v1/` for backwards compatibility during transition
- Document breaking vs. non-breaking changes in `CHANGELOG.md`

**Key Concepts Learned:**
- URL versioning vs. header versioning vs. media type versioning
- Deprecation periods (announce at v1, remove at v2)
- Why breaking changes break integrations in production

---

### F-17 · Input Sanitization and Content Security

**Priority:** P0  
**Complexity:** Low  
**Cloud Relevance:** WAF rules, Shield — input validation at app layer is the first line of defence. WAF is the second.

**Requirements:**
- Max field lengths enforced in schema (not just at DB level):
  - `title`: max 255 characters
  - `content`: max 50,000 characters
  - `email`: max 255 characters
  - `password`: max 128 characters (prevents bcrypt DoS — bcrypt only uses first 72 bytes)
- Reject control characters in title/content (null bytes, etc.)
- Add `Content-Type: application/json` enforcement on POST/PUT endpoints
- Strip leading/trailing whitespace on title (already done), extend to all string fields

**Key Concepts Learned:**
- Input validation at application boundary (never trust client)
- bcrypt 72-byte limit — long passwords are silently truncated, creating a security false sense
- Why max length matters: DoS via large payloads, memory exhaustion

**Acceptance Criteria:**
- Title > 255 chars → 422
- Password > 128 chars → 422 with explanation
- Null byte in title → 422

---

## 4. Implementation Sequence

Build in this order. Each step leaves the app fully functional and tested before the next begins.

```
Week 1 — Foundation
  ├── F-01  Alembic migrations          (enables all schema changes safely)
  ├── F-17  Input sanitization          (closes open security gaps)
  └── F-15  JSON logging                (makes later debugging much easier)

Week 2 — Auth Hardening
  ├── F-07  Refresh tokens              (proper session management)
  ├── F-05  Email verification          (requires F-07 infra in place)
  └── F-06  Password reset              (reuses email infra from F-05)

Week 3 — Data Isolation
  ├── F-04  User workspace separation   (scoped notes, visibility model)
  ├── F-11  Soft deletes + audit trail  (data safety)
  └── F-14  Admin management endpoints  (operational tooling)

Week 4 — Performance
  ├── F-02  Rate limiting               (in-memory first)
  ├── F-03  Redis cache                 (cache + move rate limits to Redis)
  └── F-08  Full-text search            (PostgreSQL FTS with GIN index)

Week 5 — Features
  ├── F-12  Background tasks            (email + scheduled cleanup)
  ├── F-10  File attachments            (local storage, S3-ready interface)
  ├── F-13  Tags and categories         (PostgreSQL arrays)
  └── F-09  Note sharing               (ACLs + share links)

Week 6 — Polish
  └── F-16  API versioning             (ready for external clients / mobile)
```

---

## 5. New Tables Summary (all require Alembic migrations)

| Table | Purpose | Key Columns |
|---|---|---|
| `refresh_tokens` | Refresh token storage | user_id, token_hash, expires_at, revoked |
| `email_verifications` | Email verification tokens | user_id, token_hash, expires_at |
| `password_resets` | Password reset tokens | user_id, token_hash, expires_at, used |
| `note_shares` | Per-note ACL entries | note_id, shared_with_user_id, permission |
| `share_links` | Public share link tokens | note_id, token, expires_at |
| `attachments` | File attachment metadata | note_id, filename, content_type, storage_path |
| `audit_logs` | Append-only audit trail | user_id, action, resource_type, metadata JSONB |

**Existing table changes:**
- `users`: add `is_verified`, `is_active`, `last_login_at`
- `notes`: add `visibility`, `deleted_at`, `tags` (ARRAY), `search_vector` (tsvector)

---

## 6. Environment Variables (after all features)

```env
# Core
DATABASE_URL=postgresql://...
SECRET_KEY=...
APP_ENV=development|test|production

# JWT
JWT_EXPIRE_MINUTES=15
JWT_REFRESH_EXPIRE_DAYS=30

# Redis
REDIS_URL=redis://localhost:6379

# Email
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_USER=
SMTP_PASS=
EMAIL_FROM=noreply@cloudnotes.local

# Storage
STORAGE_BACKEND=local|s3
UPLOADS_DIR=./uploads
AWS_BUCKET_NAME=
AWS_REGION=

# Logging
LOG_FORMAT=text|json
LOG_LEVEL=DEBUG|INFO|WARNING
```

---

## 7. What Comes After This Document

Once all features above are implemented and tested, the project is ready for:

1. **Docker Compose** — containerise app + PostgreSQL + Redis + MailHog
2. **Alembic in Docker entrypoint** — run `alembic upgrade head` before starting uvicorn
3. **EC2 deploy** — single machine, manual SSH deploy
4. **ECS Fargate** — container orchestration, no servers to manage
5. **RDS PostgreSQL** — managed DB, automated backups, multi-AZ
6. **ElastiCache Redis** — managed Redis cluster
7. **S3** — swap `LocalStorage` for `S3Storage` (one env var change)
8. **SES** — swap SMTP config for AWS SES endpoint
9. **GitHub Actions CI/CD** — test → build → push to ECR → deploy to ECS
10. **CloudWatch** — JSON logs from F-15 flow directly into CloudWatch Logs Insights

---

*Each cloud service maps directly to a concept already implemented in the application layer. The cloud migration becomes config changes, not rewrites.*
