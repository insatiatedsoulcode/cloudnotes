# CloudNotes — Software Requirements Specification v2
### Comprehensive Architecture & Feature Reference

**Date:** 2026-06-14  
**Status:** Current (all 17 features implemented, 401 tests passing)  
**Stack:** React + FastAPI + PostgreSQL + Redis

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Technology Stack](#3-technology-stack)
4. [Database Schema](#4-database-schema)
5. [Authentication & Security Model](#5-authentication--security-model)
6. [API Reference](#6-api-reference)
7. [Feature Inventory (F-01 – F-17)](#7-feature-inventory)
8. [Request Lifecycle](#8-request-lifecycle)
9. [Background Tasks & Scheduler](#9-background-tasks--scheduler)
10. [Caching Architecture](#10-caching-architecture)
11. [Storage Architecture](#11-storage-architecture)
12. [Logging & Observability](#12-logging--observability)
13. [Test Coverage](#13-test-coverage)
14. [Cloud Engineering Concepts Map](#14-cloud-engineering-concepts-map)
15. [Deployment Architecture](#15-deployment-architecture)

---

## 1. Executive Summary

CloudNotes is a production-grade notes application built as a **cloud engineering learning project**. Every feature is chosen to teach a real cloud pattern: caching, background tasks, soft deletes, audit trails, structured logging, API versioning, and more. The backend is a FastAPI service backed by PostgreSQL and Redis; the frontend is a React SPA served by Nginx.

**Current state:** 17 features implemented across 22 test files with 401 tests, all passing.

---

## 2. System Architecture

### 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         CLIENT LAYER                            │
│                                                                 │
│   Browser ──── React SPA (Vite build, served by Nginx)         │
│                     │                                           │
│                      ── Vite proxy → :8000 (dev)               │
│                      ── Nginx reverse proxy (prod)              │
└─────────────────────────────────┬───────────────────────────────┘
                                  │ HTTP / JSON
┌─────────────────────────────────▼───────────────────────────────┐
│                       API LAYER (FastAPI)                        │
│                                                                  │
│  ┌──────────────┐  ┌─────────────┐  ┌──────────────────────┐   │
│  │  Middleware   │  │   Routers   │  │    Background Tasks  │   │
│  │              │  │             │  │                      │   │
│  │ • CORS        │  │ /auth       │  │  FastAPI BG tasks:  │   │
│  │ • Rate limit  │  │ /notes      │  │  • send_email()     │   │
│  │ • Version hdr │  │ /tags       │  │                      │   │
│  │ • Content-Type│  │ /sharing    │  │  APScheduler jobs:  │   │
│  │ • Request ID  │  │ /attachments│  │  • hard delete 2AM  │   │
│  │ • Logging     │  │ /admin      │  │  • purge tokens 3AM │   │
│  │ • SlowAPI RL  │  │ /users      │  │  • revoke links 1hr │   │
│  └──────────────┘  └─────────────┘  └──────────────────────┘   │
│                           │                                      │
│  ┌───────────────────────┐│┌──────────────────────────────┐     │
│  │   Dependencies        │││   Audit Layer                │     │
│  │                       │││                              │     │
│  │ • get_current_user()  │││ log_action() — same-tx audit │     │
│  │ • require_verified()  │││ entries for every mutation   │     │
│  │ • require_admin()     │││                              │     │
│  │ • get_db()            │││                              │     │
│  │ • get_storage()       │││                              │     │
│  └───────────────────────┘│└──────────────────────────────┘     │
└─────────────────────────────────┬───────────────────────────────┘
                                  │
        ┌─────────────────────────┼────────────────────┐
        │                         │                    │
┌───────▼──────┐         ┌────────▼──────┐    ┌───────▼──────┐
│  PostgreSQL  │         │     Redis     │    │  Local Disk  │
│              │         │               │    │  (uploads/)  │
│  8 tables    │         │  Cache aside  │    │              │
│  10 Alembic  │         │  Rate limit   │    │  S3-ready    │
│  migrations  │         │  counters     │    │  StorageBack-│
│              │         │  Pwd reset    │    │  end proto   │
│  GIN indexes │         │  tokens       │    │              │
│  FTS trigger │         │               │    │              │
└──────────────┘         └───────────────┘    └──────────────┘
```

### 2.2 Layered Architecture (Per-Request)

```
HTTP Request
    │
    ▼
┌─────────────────────────────────────────────────────┐
│  MIDDLEWARE STACK  (executed in registration order)  │
│                                                      │
│  1. SlowAPIMiddleware     — rate limiting            │
│  2. CORSMiddleware        — cross-origin headers     │
│  3. api_middleware (ours) — in order:                │
│       a. Accept-Version validation                   │
│       b. request_id_var.set(uuid4())                 │
│       c. Content-Type check (POST/PUT/PATCH)         │
│       d. body logging (non-multipart)                │
│       e. call_next(request)  ◄── actual handler here │
│       f. X-Request-ID response header                │
│       g. response timing log                         │
└────────────────────────┬────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────┐
│  FASTAPI DEPENDENCY INJECTION                        │
│                                                      │
│  get_db()            — yields SQLAlchemy Session     │
│  get_current_user()  — decodes JWT → User ORM obj   │
│  require_verified()  — get_current_user + is_verified│
│  require_admin()     — get_current_user + role=admin │
│  get_storage()       — LocalStorage | S3Storage      │
└────────────────────┬────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────┐
│  ROUTER HANDLER                                      │
│                                                      │
│  1. Cache check (GET only)                           │
│  2. DB query (SQLAlchemy ORM)                        │
│  3. Business logic                                   │
│  4. log_action() — adds AuditLog to session          │
│  5. db.commit() — saves both action + audit entry    │
│  6. Cache invalidation                               │
│  7. Background task enqueue (email sends)            │
│  8. Return Pydantic response model                   │
└─────────────────────────────────────────────────────┘
```

---

## 3. Technology Stack

| Layer | Technology | Version | Notes |
|-------|-----------|---------|-------|
| Frontend | React | 18.x | Vite build, Nginx serving |
| API Framework | FastAPI | 0.111.0 | Async, OpenAPI auto-docs |
| ASGI Server | Uvicorn | 0.29.0 | Standard extras (websockets) |
| ORM | SQLAlchemy | 2.0.30 | Declarative models |
| Migrations | Alembic | 1.13.1 | 10 versioned migrations |
| Database | PostgreSQL | 16 | ARRAY, TSVECTOR, JSONB, GIN |
| Cache / RL | Redis | 5.0.4 | Cache-aside + SlowAPI RL |
| Auth | python-jose | 3.3.0 | HS256 JWT |
| Password | passlib + bcrypt | 1.7.4 / 4.0.1 | 128-char max |
| Validation | Pydantic | 2.7.1 | Field validators, EmailStr |
| Rate Limiting | slowapi | 0.1.9 | Per-user + per-IP |
| Scheduler | APScheduler | 3.11.2 | AsyncIOScheduler |
| Logging | python-json-logger | 2.x | JSON or text mode |
| File Storage | LocalStorage / S3 | — | Protocol-based abstraction |
| Container | Docker + Compose | 3.9 | maps to ECS task definitions |

---

## 4. Database Schema

### 4.1 Entity-Relationship Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ENTITY RELATIONSHIPS                          │
└─────────────────────────────────────────────────────────────────────┘

┌───────────────────────────┐
│           users           │
├───────────────────────────┤
│ PK  id          INTEGER   │◄──────────────────────────────────┐
│     email       VARCHAR   │◄────────────────────────────┐     │
│     password_hash VARCHAR │                             │     │
│     role        VARCHAR   │  "user" | "admin"           │     │
│     is_active   BOOLEAN   │  False = suspended          │     │
│     is_verified BOOLEAN   │  False = cannot create      │     │
│     created_at  DATETIME  │                             │     │
└───────────────────────────┘                             │     │
          │ 1                                             │     │
          │                                               │     │
          │ N    ┌────────────────────────────────────┐   │     │
          └─────►│         notes                      │   │     │
                 ├────────────────────────────────────┤   │     │
                 │ PK  id            INTEGER           │   │     │
                 │ FK  owner_id  ───►users.id          │   │     │
                 │     title         VARCHAR(255)      │   │     │
                 │     content       TEXT              │   │     │
                 │     author        VARCHAR(100)      │   │     │
                 │     visibility    VARCHAR(10)       │   │     │
                 │     tags          TEXT[]  ← GIN idx │   │     │
                 │     deleted_at    DATETIME nullable  │   │     │
                 │     search_vector TSVECTOR ← GIN idx│   │     │
                 │     created_at    DATETIME           │   │     │
                 │     updated_at    DATETIME           │   │     │
                 └──────────────┬─────────────────────┘   │     │
                                │ 1                        │     │
                    ┌───────────┼───────────┐              │     │
                    │           │           │              │     │
                    │N          │N          │N             │     │
          ┌─────────▼──┐  ┌────▼───────┐  ┌▼───────────┐ │     │
          │  note_shares│  │share_links │  │attachments │ │     │
          ├─────────────┤  ├────────────┤  ├────────────┤ │     │
          │ PK id       │  │ PK id      │  │ PK id      │ │     │
          │ FK note_id  │  │ FK note_id │  │ FK note_id │ │     │
          │ FK shared_  │  │ token_hash │  │ filename   │ │     │
          │   with_uid ─┼─►│ expires_at │  │ content_   │ │     │
          │ permission  │  │ revoked    │  │   type     │ │     │
          │ created_at  │  │ created_at │  │ size_bytes │ │     │
          │             │  │            │  │ storage_   │ │     │
          │ UNIQUE(note_│  │            │  │   path     │ │     │
          │   id,user_id│  │            │  │ created_at │ │     │
          └─────────────┘  └────────────┘  └────────────┘ │     │
                │                                          │     │
                └──────────────────────────────────────────┘     │
                                                                  │
          ┌─────────────────────────────────────────────────┐    │
          │              email_verifications                 │    │
          ├─────────────────────────────────────────────────┤    │
          │ PK id        INTEGER                             │    │
          │ FK user_id ──────────────────────────────────────────►│
          │    token_hash  VARCHAR(64)  ← indexed            │    │
          │    expires_at  DATETIME                          │    │
          │    used        BOOLEAN                           │    │
          │    created_at  DATETIME                          │    │
          └─────────────────────────────────────────────────┘    │
                                                                  │
          ┌─────────────────────────────────────────────────┐    │
          │              refresh_tokens                      │    │
          ├─────────────────────────────────────────────────┤    │
          │ PK id        INTEGER                             │    │
          │ FK user_id ──────────────────────────────────────────►│
          │    token_hash  VARCHAR(64)  unique + indexed     │    │
          │    expires_at  DATETIME                          │    │
          │    revoked     BOOLEAN                           │    │
          │    ip_address  VARCHAR(45)                       │    │
          │    user_agent  VARCHAR(500)                      │    │
          │    created_at  DATETIME                          │    │
          └─────────────────────────────────────────────────┘    │
                                                                  │
          ┌─────────────────────────────────────────────────┐    │
          │              audit_logs                          │    │
          ├─────────────────────────────────────────────────┤    │
          │ PK id            INTEGER                         │    │
          │ FK user_id ──────────────────────────────────────────►│
          │    action        VARCHAR(50)  ← indexed          │    │
          │    resource_type VARCHAR(50)                     │    │
          │    resource_id   INTEGER                         │    │
          │    details       JSONB  (before/after snapshots) │    │
          │    ip_address    VARCHAR(45)                     │    │
          │    created_at    DATETIME  ← indexed             │    │
          └─────────────────────────────────────────────────┘    │
                                                                  │
          (append-only — never UPDATE'd or DELETE'd)              │
```

### 4.2 PostgreSQL-Specific Features

```
┌─────────────────────────────────────────────────────────────┐
│              POSTGRESQL ADVANCED FEATURES USED               │
├──────────────┬──────────────────────────────────────────────┤
│ Feature      │ Usage                                        │
├──────────────┼──────────────────────────────────────────────┤
│ TSVECTOR     │ notes.search_vector — FTS weighted index     │
│              │ title=weight A, content=weight B             │
│              │ Updated by DB trigger on INSERT/UPDATE       │
├──────────────┼──────────────────────────────────────────────┤
│ GIN index    │ notes.search_vector — FTS @@ operator        │
│ (2 of them)  │ notes.tags — array @> (contains) operator    │
├──────────────┼──────────────────────────────────────────────┤
│ ARRAY(TEXT)  │ notes.tags — free-form tags, no join table   │
│              │ unnest() for GROUP BY count query            │
├──────────────┼──────────────────────────────────────────────┤
│ JSONB        │ audit_logs.details — before/after snapshots  │
│              │ Schema-flexible; queryable with ->> / @>     │
├──────────────┼──────────────────────────────────────────────┤
│ DB Trigger   │ notes_search_vector_trigger                  │
│              │ BEFORE INSERT OR UPDATE ON notes             │
│              │ calls notes_search_vector_update() plpgsql   │
└──────────────┴──────────────────────────────────────────────┘
```

### 4.3 Alembic Migration Chain

```
  e6361fdb29d1  ← initial schema (users, notes)
        │
  959a20e0dea4  ← visibility + is_active on users
        │
  a1b2c3d4e5f6  ← email_verifications table + is_verified
        │
  b2c3d4e5f6a7  ← refresh_tokens table
        │
  c3d4e5f6a7b8  ← session metadata (ip_address, user_agent)
        │
  d4e5f6a7b8c9  ← FTS (search_vector TSVECTOR, GIN index, trigger)
        │
  e5f6a7b8c9d0  ← note_shares + share_links tables
        │
  f6a7b8c9d0e1  ← attachments table
        │
  07a8b9c0d1e2  ← soft delete (deleted_at) + audit_logs table
        │
  a8b9c0d1e2f3  ← tags TEXT[] column + GIN index on notes
        │
       HEAD
```

---

## 5. Authentication & Security Model

### 5.1 Token Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    DUAL-TOKEN AUTH FLOW                           │
└──────────────────────────────────────────────────────────────────┘

  POST /api/v1/auth/login
       │
       ├─ Verify email + bcrypt hash
       ├─ Check is_active (suspended → 403)
       │
       ├──► ACCESS TOKEN (JWT, HS256)
       │    • Payload: {sub: user_id, exp: now+15min}
       │    • Returned in response body
       │    • Stateless — verified by signature, not DB lookup
       │    • Short-lived: compromise window is ≤15 minutes
       │
       └──► REFRESH TOKEN (opaque, 256-bit random)
            • SHA-256 hash stored in refresh_tokens table
            • Raw value in HTTP-only SameSite=Lax cookie
            • Long-lived: 30 days
            • Server-side revocable (DB row)
            • Carries ip_address + user_agent for session list

  ┌─────────────────────────────────────────────────────────────┐
  │  TOKEN ROTATION (POST /api/v1/auth/refresh)                  │
  │                                                              │
  │  Client sends cookie ──► verify hash in DB                  │
  │  Old token revoked ──► new access + refresh issued          │
  │                                                              │
  │  REUSE DETECTION:                                            │
  │  If revoked token is presented again → attacker has it      │
  │  Response: revoke ALL sessions for user (nuclear option)    │
  └─────────────────────────────────────────────────────────────┘

  HTTP-only cookie properties:
    Name:     refresh_token
    Path:     /api/auth      ← only sent to auth endpoints
    HttpOnly: true           ← JS cannot read (XSS protection)
    SameSite: Lax            ← CSRF mitigation
    Secure:   true in prod   ← HTTPS only in production
```

### 5.2 Authorization Layers

```
REQUEST ──► [1] JWT decode + user load
                    │
                    ▼
            [2] Role check
                    │
              ┌─────┴─────┐
           user          admin
              │               │
              ▼               ▼
     [3] Resource scope   All resources
         Own notes
         + public notes
         + explicitly
           shared notes
              │
              ▼
     [4] Visibility check
         private: owner + admin + shared
         public:  all authenticated
              │
              ▼
     [5] Permission check (for writes)
         owner + admin: full
         edit-share:    update only
         view-share:    read only

  ┌────────────────────────────────────────────────┐
  │  DELETED RESOURCE GATE (F-11)                  │
  │  All queries filter: WHERE deleted_at IS NULL  │
  │  Deleted resources return 404 to all callers   │
  └────────────────────────────────────────────────┘
```

### 5.3 Email Verification Gate

```
  Register ──► User created (is_verified=False)
                     │
                     ▼
              Verification email sent
              (BackgroundTask, token hash in DB)
                     │
              User clicks link
                     │
                     ▼
              GET /auth/verify?token=...
              is_verified = True
                     │
                     ▼
              POST /notes/ → require_verified() → allowed
              (Before verify: 403 "Email not verified")
```

### 5.4 Security Controls Summary

| Control | Implementation |
|---------|---------------|
| Password hashing | bcrypt, cost factor default |
| Password limits | min 8, max 128 chars (bcrypt 72-byte truncation protection) |
| JWT signing | HS256, 15-minute expiry |
| Refresh token | SHA-256 hashed at rest, HTTP-only cookie |
| Token reuse | Detects replayed revoked tokens → revoke all sessions |
| Rate limiting | Login 5/min, Register 3/min, Writes 30/min (per user or IP) |
| Input validation | Pydantic: max lengths, control char rejection, null byte rejection |
| Content-Type | 415 for non-JSON/form/multipart on mutation endpoints |
| SQL injection | SQLAlchemy ORM parameterized queries throughout |
| XSS | JSON API only; no HTML rendering |
| MIME type | Magic bytes validation for uploads (not client header) |
| File size | 10 MB max for attachments |
| Account suspension | is_active=False blocks login with 403 |
| Admin self-protect | Admin cannot suspend their own account |

---

## 6. API Reference

### Base URLs
- Primary (versioned): `/api/v1/`
- Legacy alias: `/api/` (backwards compat, hidden from docs)
- Header alternative: `Accept-Version: v1` on any `/api/` route

### 6.1 Authentication Endpoints (`/api/v1/auth/`)

```
POST   /register           Register new user (email + password)
POST   /login              OAuth2 password flow → access token + refresh cookie
POST   /refresh            Rotate refresh token → new access token
POST   /logout             Revoke refresh token, clear cookie
GET    /verify?token=...   Consume email verification token
POST   /resend-verification Resend verification email
POST   /forgot-password    Send password reset email
POST   /reset-password     Consume reset token, update password
GET    /sessions           List active sessions for current user
DELETE /sessions/{id}      Revoke a specific session
DELETE /sessions           Revoke all sessions (logout everywhere)
```

### 6.2 Notes Endpoints (`/api/v1/notes/`)

```
GET    /                   List notes (own + public + shared)
         ?q=               Full-text search (FTS)
         ?tag=             Filter by tag
         ?sort=            created_at | updated_at | rank
         ?order=           asc | desc
         ?from=            Date filter start (YYYY-MM-DD)
         ?to=              Date filter end (YYYY-MM-DD)
         ?visibility=      public | private
         ?skip=&limit=     Pagination

POST   /                   Create note (requires is_verified)
         body: {title, content, visibility, tags[]}

GET    /{note_id}          Get single note (visibility-scoped)
PUT    /{note_id}          Update note (owner/admin/edit-share)
DELETE /{note_id}          Soft-delete note (owner/admin only)
```

### 6.3 Sharing Endpoints (`/api/v1/notes/`)

```
POST   /{note_id}/share              Share with registered user
         body: {email, permission: "view"|"edit"}
         (idempotent: updates permission if already shared)

GET    /{note_id}/shares             List shares for a note
DELETE /{note_id}/share/{share_id}   Revoke a specific share

POST   /{note_id}/share-link         Generate public share link (7-day TTL)
DELETE /{note_id}/share-link         Revoke active share link

GET    /shared/{token}               Access note via share link (no auth)
```

### 6.4 Attachment Endpoints (`/api/v1/notes/`)

```
POST   /{note_id}/attachments        Upload file (owner/admin only)
         Allowed: JPEG, PNG, GIF, PDF, plain text
         Max size: 10 MB
         MIME validated from magic bytes, not client header

GET    /{note_id}/attachments        List attachments (read-access scope)
DELETE /{note_id}/attachments/{id}   Delete attachment (owner/admin only)
```

### 6.5 Tags Endpoint (`/api/v1/tags/`)

```
GET    /     Return [{tag, count}] for current user's live notes
             Sorted by count DESC
             Uses PostgreSQL unnest() + GROUP BY
```

### 6.6 User Endpoints (`/api/v1/users/`)

```
GET    /me           Get current user profile
PUT    /me           Change password (current + new)
DELETE /me           Delete own account (soft: is_active=False)
```

### 6.7 Admin Endpoints (`/api/v1/admin/`) — role=admin required

```
GET    /notes              List all live notes (system-wide)
GET    /notes/trash        List soft-deleted notes
POST   /notes/{id}/restore Restore a soft-deleted note

GET    /users              List all users with note_count
PUT    /users/{id}/role    Change role: {"role": "user"|"admin"}
PUT    /users/{id}/suspend    Set is_active=False
PUT    /users/{id}/unsuspend  Set is_active=True (not self)

GET    /stats              System stats:
                            {total_users, total_notes,
                             notes_today, active_sessions}

GET    /audit-logs         Paginated audit trail
         ?user_id=         Filter by user
         ?action=          Filter by action type
         ?from=&to=        DateTime range filter
         ?skip=&limit=     Pagination
```

### 6.8 Special Endpoints

```
GET  /health      Health check → {"status": "ok"}
GET  /            Root → {"message": "CloudNotes API", "docs": "/docs"}
GET  /docs        OpenAPI interactive documentation (Swagger UI)
```

---

## 7. Feature Inventory

```
┌────┬───────────────────────────────────────┬─────────┬──────────────────────────────────────┐
│ ID │ Feature                               │ Status  │ Cloud Concept                        │
├────┼───────────────────────────────────────┼─────────┼──────────────────────────────────────┤
│F-01│ Alembic migrations                    │ ✅ Done │ Schema versioning, zero-downtime DDL │
│F-02│ Rate limiting (SlowAPI + Redis)       │ ✅ Done │ API Gateway throttling               │
│F-03│ Redis cache (cache-aside)             │ ✅ Done │ ElastiCache, TTL eviction            │
│F-04│ User workspace + visibility           │ ✅ Done │ Resource ownership, IAM-style scope  │
│F-05│ Email verification                    │ ✅ Done │ Confirmation tokens, one-time links  │
│F-06│ Password reset                        │ ✅ Done │ Secure token flow, Redis TTL         │
│F-07│ Refresh token + session mgmt          │ ✅ Done │ Token rotation, reuse detection      │
│F-08│ Full-text search + filters            │ ✅ Done │ OpenSearch/Elasticsearch concepts    │
│F-09│ Note sharing (ACL + share links)      │ ✅ Done │ S3 bucket policies, presigned URLs   │
│F-10│ File attachments (storage abstraction)│ ✅ Done │ S3 interface, magic bytes, CDN       │
│F-11│ Soft deletes + audit trail            │ ✅ Done │ Tombstoning, compliance logging      │
│F-12│ Background tasks + scheduler          │ ✅ Done │ SQS, Lambda, EventBridge             │
│F-13│ Note tags (PostgreSQL arrays + GIN)   │ ✅ Done │ Array vs normalized, GIN index       │
│F-14│ Admin management endpoints            │ ✅ Done │ Control plane vs data plane          │
│F-15│ Structured JSON logging + request ID  │ ✅ Done │ CloudWatch, Datadog, correlation IDs │
│F-16│ API versioning (/v1/ + alias)         │ ✅ Done │ API Gateway, blue/green deployment   │
│F-17│ Input sanitization + Content-Type     │ ✅ Done │ WAF rules, bcrypt DoS prevention     │
└────┴───────────────────────────────────────┴─────────┴──────────────────────────────────────┘
```

---

## 8. Request Lifecycle

### 8.1 Authenticated Note Create (Complete Flow)

```
  Browser                  FastAPI              Redis           PostgreSQL
     │                        │                   │                 │
     │  POST /api/v1/notes/   │                   │                 │
     │  Authorization: Bearer │                   │                 │
     │  {title,content,tags}  │                   │                 │
     │───────────────────────►│                   │                 │
     │                        │                   │                 │
     │                        │ [Middleware]       │                 │
     │                        │ Accept-Version?    │                 │
     │                        │ Set request_id_var │                 │
     │                        │ Check Content-Type │                 │
     │                        │ Rate limit check──►│                 │
     │                        │◄──────────────────│                 │
     │                        │                   │                 │
     │                        │ [Dependency: get_current_user]      │
     │                        │ Decode JWT → user_id               │
     │                        │ SELECT * FROM users WHERE id=?─────►│
     │                        │◄────────────────────────────────────│
     │                        │                   │                 │
     │                        │ [Dependency: require_verified]      │
     │                        │ Check is_verified=True              │
     │                        │                   │                 │
     │                        │ [Pydantic validation]               │
     │                        │ title ≤255, no ctrl chars           │
     │                        │ content ≤50k, no null bytes         │
     │                        │ tags: lowercase, deduplicate        │
     │                        │                   │                 │
     │                        │ INSERT INTO notes ─────────────────►│
     │                        │ db.flush() → get id                │
     │                        │                   │                 │
     │                        │ INSERT INTO audit_logs ────────────►│
     │                        │ (note_create, details={...})        │
     │                        │                   │                 │
     │                        │ db.commit() ───────────────────────►│
     │                        │◄────────────────────────────────────│
     │                        │                   │                 │
     │                        │ cache_delete_pattern("notes:list:*")│
     │                        │───────────────────►│                 │
     │                        │                   │                 │
     │                        │ [BackgroundTask: send_verify not    │
     │                        │  applicable here — no email needed] │
     │                        │                   │                 │
     │  201 {id,title,...}    │                   │                 │
     │  X-Request-ID: uuid    │                   │                 │
     │◄───────────────────────│                   │                 │
```

### 8.2 Cache-Aside Pattern (Note List)

```
  GET /api/v1/notes/
         │
         ▼
  cache_get("notes:list:{user_id}:{skip}:{limit}:{sort}:{order}")
         │
    ┌────┴────┐
    │  HIT?   │
    └────┬────┘
    Yes  │  No
    │    │    │
    │    │    ▼
    │    │  DB query (with scope, filters, sort)
    │    │    │
    │    │    ▼
    │    │  cache_set(key, data, TTL=30s)
    │    │    │
    ▼    └────┘
  Return cached / fresh data

  Cache invalidation triggers:
    • Note created   → cache_delete_pattern("notes:list:*")
    • Note updated   → cache_delete_pattern("notes:list:*")
                     + cache_delete("notes:detail:{id}")
    • Note deleted   → cache_delete_pattern("notes:list:*")
                     + cache_delete("notes:detail:{id}")
    • Share added    → cache_delete_pattern("notes:list:*")

  TTLs:
    notes:list:*    30 seconds
    notes:detail:*   5 minutes
```

---

## 9. Background Tasks & Scheduler

### 9.1 FastAPI BackgroundTasks (Fire-and-Forget)

```
  POST /auth/register
         │
         ├─ DB: INSERT user + flush
         ├─ DB: INSERT audit_log
         ├─ DB: commit
         │
         ├─ _issue_verification() → DB token
         │
         ├─ background_tasks.add_task(
         │      send_verification_email,
         │      to=user.email,
         │      token=raw_token
         │  )
         │
         └─ RETURN 201 immediately
                │
                │ (after response is sent)
                ▼
           send_verification_email()
           → SMTP to MailHog / SES

  Same pattern: forgot-password, resend-verification
  Why: response latency independent of SMTP server latency
  Limitation: task lost if process crashes before execution
  Production upgrade: Celery + SQS for durability
```

### 9.2 APScheduler Jobs

```
  ┌──────────────────────────────────────────────────────────────┐
  │                  APSCHEDULER (AsyncIOScheduler)               │
  │                  Started in lifespan (not in test mode)       │
  └──────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │  Job 1: hard_delete_old_notes()           Cron: 02:00 daily │
  │                                                             │
  │  DELETE FROM notes                                          │
  │  WHERE deleted_at IS NOT NULL                               │
  │    AND deleted_at < now() - INTERVAL '30 days'              │
  │                                                             │
  │  Effect: permanent removal after 30-day grace period        │
  │  Cascade: FK ON DELETE CASCADE removes shares/links/atts    │
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │  Job 2: purge_expired_refresh_tokens()    Cron: 03:00 daily │
  │                                                             │
  │  DELETE FROM refresh_tokens                                 │
  │  WHERE expires_at < now()                                   │
  │                                                             │
  │  Effect: prevents unbounded table growth                    │
  └─────────────────────────────────────────────────────────────┘

  ┌─────────────────────────────────────────────────────────────┐
  │  Job 3: revoke_expired_share_links()      Interval: 1 hour  │
  │                                                             │
  │  UPDATE share_links SET revoked=True                        │
  │  WHERE expires_at < now() AND revoked=False                 │
  │                                                             │
  │  Effect: marks links as revoked even if not yet accessed    │
  │  (Access endpoint already checks expires_at; this is       │
  │   a cleanup to make the revoked flag accurate for audits)   │
  └─────────────────────────────────────────────────────────────┘

  Cloud analogy:
    APScheduler (in-process) ≈ cron
    Production upgrade → AWS EventBridge Scheduler + Lambda
    Key difference: EventBridge survives process crashes;
    APScheduler jobs are lost if the server restarts between
    scheduled times (the "at-least-once" problem)
```

---

## 10. Caching Architecture

```
  ┌─────────────────────────────────────────────────────────┐
  │                   REDIS USAGE MAP                        │
  ├─────────────────────┬───────────────────────────────────┤
  │  Key Pattern        │  Purpose           TTL            │
  ├─────────────────────┼───────────────────────────────────┤
  │ notes:list:{uid}:*  │ Note list cache    30s            │
  │ notes:detail:{id}   │ Single note cache  5 min          │
  │ pwd_reset:{hash}    │ Reset token        1 hour         │
  │ slowapi:*           │ Rate limit counters  window-based │
  └─────────────────────┴───────────────────────────────────┘

  Cache-Aside Pattern:
    READ:  try cache → miss → DB → write to cache → return
    WRITE: update DB → delete/invalidate cache keys

  Why delete (not update) on write:
    Updating cache on write risks stale data if DB commit fails.
    Deletion forces the next read to re-fetch from DB.

  Test strategy:
    fakeredis.FakeRedis — in-memory Redis clone
    Injected via override_for_testing() in conftest.py
    Flushed after every test — no cross-test contamination
```

---

## 11. Storage Architecture

```
  ┌─────────────────────────────────────────────────────────┐
  │             FILE STORAGE ABSTRACTION (F-10)              │
  └─────────────────────────────────────────────────────────┘

  Protocol (structural subtyping — no ABC needed):

    class StorageBackend(Protocol):
        def save(key: str, data: bytes, content_type: str) -> None
        def get_url(key: str) -> str
        def delete(key: str) -> None

  Implementations:
    LocalStorage — writes to UPLOADS_DIR/{key}
                  serves via FastAPI StaticFiles at /uploads/
    S3Storage   — not yet implemented (raises NotImplementedError)

  Upload pipeline:
    1. Read file bytes (async)
    2. Size check: > 10 MB → 413
    3. Magic bytes detection → MIME type
       PNG:  \x89PNG\r\n\x1a\n
       JPEG: \xff\xd8\xff
       GIF:  GIF87a / GIF89a
       PDF:  %PDF-
       text: no null in first 512 bytes
    4. Sanitize filename (strip path traversal, special chars)
    5. Key = {note_id}/{uuid}_{filename}
    6. storage.save(key, data, content_type)
    7. INSERT INTO attachments (note_id, key, ...)
    8. Return URL = storage.get_url(key)

  Key design: UUID prefix prevents filename collisions.
  In production: swap LocalStorage for S3Storage with
  pre-signed GET URLs; no binary traffic through the app server.
```

---

## 12. Logging & Observability

### 12.1 Structured Logging (F-15)

```
  LOG_FORMAT=text (default / dev):
    09:42:15  INFO      [cloudnotes.request]  GET /api/v1/notes/  body=<empty>  rid=abc-123
    09:42:15  INFO      [cloudnotes.notes]    LIST  user_id=1  skip=0  limit=100  ...  rid=abc-123
    09:42:15  INFO      [cloudnotes.response] GET /api/v1/notes/  status=200  duration_ms=12.4  rid=abc-123

  LOG_FORMAT=json (production / CloudWatch):
    {"timestamp":"2026-06-14T09:42:15Z","level":"INFO","logger":"cloudnotes.request",
     "message":"GET /api/v1/notes/ body=<empty>","request_id":"abc-123"}

  Log levels per APP_ENV:
    production → INFO   (no debug noise)
    test       → WARNING (suppressed by pytest)
    dev/other  → DEBUG
```

### 12.2 Request Correlation

```
  ┌─────────────────────────────────────────────────────────┐
  │              REQUEST ID FLOW (ContextVar)                │
  └─────────────────────────────────────────────────────────┘

  Middleware:
    rid = uuid4()
    request_id_var.set(rid)       ← ContextVar (task-local)
    response.headers["X-Request-ID"] = rid

  _RequestContextFilter.filter():
    record.request_id = request_id_var.get("")
    (called for every log record in this coroutine's context)

  Result:
    Every log line for a request carries the same rid.
    X-Request-ID in response lets client correlate with server logs.

  Cloud analogy:
    Simplest form of distributed tracing.
    Production: propagate rid as X-Amzn-Trace-Id (X-Ray)
    or W3C traceparent header across service boundaries.
```

### 12.3 Audit Trail

```
  ┌──────────────────────────────────────────────────────────┐
  │                AUDIT LOG ENTRIES                          │
  ├──────────────────┬───────────────────────────────────────┤
  │ action           │ When emitted                          │
  ├──────────────────┼───────────────────────────────────────┤
  │ user_register    │ POST /auth/register (success)         │
  │ user_login       │ POST /auth/login (success)            │
  │ password_reset   │ POST /auth/reset-password (success)   │
  │ note_create      │ POST /notes/ (success)                │
  │ note_update      │ PUT /notes/{id} (includes before/after│
  │                  │ snapshot of changed fields)           │
  │ note_delete      │ DELETE /notes/{id} (soft delete)      │
  │ note_restore     │ POST /admin/notes/{id}/restore        │
  │ share_create     │ POST /notes/{id}/share (new share)    │
  │ share_update     │ POST /notes/{id}/share (update perm)  │
  │ user_role_change │ PUT /admin/users/{id}/role            │
  │ user_suspend     │ PUT /admin/users/{id}/suspend         │
  │ user_unsuspend   │ PUT /admin/users/{id}/unsuspend       │
  └──────────────────┴───────────────────────────────────────┘

  Transactional guarantee:
    log_action() adds AuditLog to the DB session WITHOUT committing.
    The caller commits both the business row and the audit row together.
    If the business write fails → rollback → no orphan audit entry.
    If the commit succeeds → both are durable.

  Append-only principle:
    Audit rows are never UPDATE'd or DELETE'd.
    Violation of this would be a security incident.
```

---

## 13. Test Coverage

### 13.1 Test Suite Overview

```
  ┌────────────────────────────────────┬────────┐
  │ Test File                          │ Tests  │
  ├────────────────────────────────────┼────────┤
  │ test_admin.py                      │  25    │
  │ test_attachments.py                │  22    │
  │ test_audit_log.py                  │  14    │
  │ test_auth.py                       │  14    │
  │ test_background_tasks.py           │  12    │
  │ test_cache.py                      │  14    │
  │ test_email_verification.py         │  21    │
  │ test_input_sanitization.py         │  19    │
  │ test_logging.py                    │  15    │
  │ test_notes.py                      │  25    │
  │ test_password_reset.py             │  17    │
  │ test_rate_limit.py                 │  10    │
  │ test_refresh_token.py              │  31    │
  │ test_search.py                     │  21    │
  │ test_security.py                   │  21    │
  │ test_sharing.py                    │  24    │
  │ test_soft_delete.py                │  16    │
  │ test_tags.py                       │  22    │
  │ test_user_profile.py               │  11    │
  │ test_versioning.py                 │  12    │
  │ test_workspace.py                  │  19    │
  ├────────────────────────────────────┼────────┤
  │ TOTAL                              │  401   │
  └────────────────────────────────────┴────────┘
  Pass rate: 100% (401/401)
```

### 13.2 Test Infrastructure

```
  ┌─────────────────────────────────────────────────────────┐
  │                  TEST ARCHITECTURE                       │
  └─────────────────────────────────────────────────────────┘

  Database isolation:
    • Separate DB: cloudnotes_test (never touches dev data)
    • create_tables (session-scoped): Base.metadata.create_all()
      + manually install FTS trigger (triggers not in create_all)
    • clean_tables (function-scoped autouse):
      TRUNCATE audit_logs, attachments, share_links, note_shares,
      refresh_tokens, email_verifications, notes, users
      RESTART IDENTITY CASCADE
      → each test gets a fully clean state

  Dependency overrides:
    app.dependency_overrides[get_db] = lambda: test_session
    app.dependency_overrides[get_storage] = lambda: LocalStorage(tmp_path)

  External service mocks:
    fakeredis.FakeRedis → replaces Redis (no real server needed)
    mock_email          → patches send_verification_email
    mock_password_reset → patches send_password_reset_email

  Scheduler isolation:
    Scheduler skipped when APP_ENV == "test"
    Job functions accept optional db= for direct invocation

  Rate limiter isolation:
    reset_limits() called before/after every test
    (prevents limit exhaustion from polluting other tests)
```

---

## 14. Cloud Engineering Concepts Map

```
  ┌──────────────────────────────────────────────────────────────────┐
  │          WHAT THIS PROJECT TEACHES → AWS EQUIVALENT               │
  ├──────────────┬──────────────────────┬────────────────────────────┤
  │ Feature      │ Local Implementation  │ AWS / Production           │
  ├──────────────┼──────────────────────┼────────────────────────────┤
  │ Auth tokens  │ JWT + refresh cookie  │ Cognito / custom auth      │
  │ Rate limiting│ SlowAPI + Redis       │ API Gateway throttling     │
  │ Caching      │ Redis cache-aside     │ ElastiCache (Redis/Memcached│
  │ File storage │ LocalStorage          │ S3 + presigned URLs        │
  │ Email        │ SMTP → MailHog        │ SES                        │
  │ Background   │ FastAPI BG tasks      │ SQS + Lambda               │
  │ Scheduler    │ APScheduler           │ EventBridge Scheduler      │
  │ Full-text    │ PostgreSQL FTS        │ OpenSearch                 │
  │ Database     │ PostgreSQL (RDS-compat│ RDS PostgreSQL / Aurora    │
  │ Migrations   │ Alembic               │ Same (pre-deploy step)     │
  │ Container    │ Docker Compose        │ ECS task definitions       │
  │ Reverse proxy│ Nginx                 │ ALB / CloudFront           │
  │ Logging      │ JSON → stdout         │ CloudWatch Logs Insights   │
  │ API versioning│ /v1/ + alias         │ API Gateway stage variables│
  │ Audit log    │ audit_logs table      │ CloudTrail                 │
  │ Soft delete  │ deleted_at column     │ S3 versioning / DynamoDB TTL│
  │ Tags (array) │ PostgreSQL ARRAY      │ DynamoDB sets / Elasticsearch│
  │ WAF          │ Pydantic validators   │ AWS WAF rules              │
  │ ACL sharing  │ note_shares table     │ S3 bucket policies / IAM   │
  │ Presigned URL│ share_links table     │ S3 presigned GET URLs      │
  └──────────────┴──────────────────────┴────────────────────────────┘
```

---

## 15. Deployment Architecture

### 15.1 Local Development (Docker Compose)

```
  ┌─────────────────────────────────────────────────────────┐
  │                  docker-compose.yml                      │
  └─────────────────────────────────────────────────────────┘

  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
  │  frontend    │     │  backend     │     │  db          │
  │  (Nginx)     │     │  (Uvicorn)   │     │  (PostgreSQL)│
  │              │     │              │     │              │
  │  :80         │────►│  :8000       │────►│  :5432       │
  │              │     │              │     │              │
  │  React SPA   │     │  FastAPI     │     │  cloudnotes  │
  │  + Nginx     │     │  + hot reload│     │  database    │
  │    reverse   │     │  (develop:   │     │              │
  │    proxy     │     │   watch)     │     │  postgres_   │
  └──────────────┘     └──────────────┘     │  data volume │
                              │             └──────────────┘
                              │
                        ┌─────▼─────┐
                        │   Redis   │
                        │  :6379    │
                        │  cache +  │
                        │  rate lim │
                        └───────────┘

  Development extras:
    • MailHog at :8025 (web UI) / :1025 (SMTP) for email preview
    • Alembic auto-runs on backend startup
    • develop.watch syncs ./backend/app → /app/app (hot reload)
```

### 15.2 Production Architecture (AWS Target)

```
  Users
    │
    ▼
  ┌──────────────────────────────────────────────────────────┐
  │                   CloudFront CDN                          │
  │  Static assets (React build) cached at edge              │
  └────────────────────┬─────────────────────────────────────┘
                       │ API requests (/api/*)
                       ▼
  ┌──────────────────────────────────────────────────────────┐
  │               Application Load Balancer                   │
  │  SSL termination, health checks, /v1 routing rules        │
  └────────────────────┬─────────────────────────────────────┘
                       │
                       ▼
  ┌──────────────────────────────────────────────────────────┐
  │                ECS Fargate (Backend)                      │
  │                                                          │
  │  Task: cloudnotes-api                                    │
  │    Container: fastapi (uvicorn)                          │
  │    Env: DATABASE_URL (from Secrets Manager)              │
  │         REDIS_URL    (from Secrets Manager)              │
  │         LOG_FORMAT=json → CloudWatch                     │
  │    Health: GET /health → 200                             │
  └──────────┬───────────────────┬───────────────────────────┘
             │                   │
             ▼                   ▼
  ┌──────────────┐    ┌─────────────────┐
  │  RDS          │    │  ElastiCache    │
  │  PostgreSQL   │    │  (Redis)        │
  │               │    │                 │
  │  Multi-AZ     │    │  Cache + RL     │
  │  automated    │    │  counters       │
  │  backups      │    │                 │
  └──────────────┘    └─────────────────┘

  S3 Bucket (uploads):
    • Attachments stored as s3://{bucket}/{note_id}/{uuid}_{name}
    • Presigned GET URLs for access (15-min TTL)
    • Bucket policy: private (no public access)

  SES (email):
    • Verification + password reset emails
    • DKIM signing, bounce/complaint handling

  EventBridge Scheduler (replaces APScheduler):
    • hard_delete_old_notes → Lambda → RDS nightly
    • purge_refresh_tokens  → Lambda → RDS daily
    • revoke_share_links    → Lambda → RDS hourly

  CloudWatch:
    • Log group: /ecs/cloudnotes-api
    • LOG_FORMAT=json → Logs Insights queries
    • Filter: fields request_id | filter action = "user_login"
    • Alarms: 5xx rate, latency p99, DB connection pool

  Secrets Manager:
    DATABASE_URL, SECRET_KEY, REDIS_URL, SMTP_PASS
    (never in environment variables directly)
```

### 15.3 Migration Deployment Pattern

```
  Pre-deploy step (separate from app start):
    alembic upgrade head

  Why separate?
    • ECS tasks can't run migrations in parallel safely
    • Blue/green: migration runs before new tasks replace old ones
    • If migration fails: rollback task definition, DB unchanged

  Current (dev only):
    command.upgrade(_alembic_cfg, "head") in main.py at import time
    Safe for single-instance local dev; not for multi-instance prod
```

---

## Appendix: Source File Map

```
cloudnotes/
├── CHANGELOG.md                  API versioning changelog
├── SRS_v2.md                     This document
├── docker-compose.yml            Local dev orchestration
├── backend/
│   ├── requirements.txt          Python dependencies (16 packages)
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/             10 migrations (e6361 → a8b9c)
│   ├── app/
│   │   ├── main.py               FastAPI app, middleware, lifespan
│   │   ├── config.py             Pydantic settings (env vars)
│   │   ├── database.py           Engine, SessionLocal, Base
│   │   ├── dependencies.py       get_current_user, require_*
│   │   ├── audit.py              log_action() helper
│   │   ├── cache.py              Redis cache-aside helpers
│   │   ├── email.py              SMTP + token generation
│   │   ├── limiter.py            SlowAPI setup
│   │   ├── logger.py             setup_logging, ContextVar, filter
│   │   ├── scheduler.py          APScheduler + 3 job functions
│   │   ├── storage.py            StorageBackend protocol, LocalStorage
│   │   ├── models/
│   │   │   ├── user.py           users table
│   │   │   ├── note.py           notes table (ARRAY, TSVECTOR)
│   │   │   ├── note_share.py     note_shares table (ACL)
│   │   │   ├── share_link.py     share_links table (presigned)
│   │   │   ├── attachment.py     attachments table
│   │   │   ├── audit_log.py      audit_logs table (JSONB)
│   │   │   ├── email_verification.py
│   │   │   └── refresh_token.py
│   │   ├── routers/
│   │   │   ├── auth.py           auth + session endpoints (446 lines)
│   │   │   ├── notes.py          note CRUD + list (301 lines)
│   │   │   ├── sharing.py        ACL + share links
│   │   │   ├── attachments.py    file upload/download
│   │   │   ├── tags.py           tag list + count
│   │   │   ├── admin.py          admin control plane (288 lines)
│   │   │   └── users.py          user profile
│   │   └── schemas/
│   │       ├── note.py           NoteCreate/Update/Response
│   │       ├── user.py           UserCreate/Profile/AdminView/Stats
│   │       ├── note_share.py     ShareRequest/Response/LinkResponse
│   │       ├── attachment.py     AttachmentResponse
│   │       └── audit_log.py      AuditLogResponse
│   └── tests/                    401 tests across 22 files
└── frontend/
    ├── src/
    │   ├── api/         auth.js, notes.js
    │   ├── components/  LoginForm, NoteCard, NoteForm
    │   └── pages/
    └── Dockerfile
```
