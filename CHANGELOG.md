# Changelog

## v1 (current)

All routes available under `/api/v1/` (primary) and `/api/` (legacy alias).

### Non-breaking changes
- `/api/v1/` prefix added as the canonical versioned path.
- `/api/` retained as an alias during the transition period.
- `Accept-Version: v1` header accepted on all `/api/` requests.
- `X-Request-ID` header added to all responses (correlation ID).

### Upcoming breaking changes in v2 (not yet released)
- `/api/` alias will be removed — clients must migrate to `/api/v2/`.
- Announce at least 90 days before removal.

---

### Cloud concept: why versioning matters

Once external clients depend on an API, any change to field names, response
shapes, or status codes is a **breaking change**.  URL versioning (`/v1/`) gives
clients a stable path to pin to.  Header versioning (`Accept-Version`) lets a
single URL serve multiple versions via content negotiation — the same model as
`Accept: application/json` vs `text/html`.

In production: API Gateway routes `/v1/` traffic to one Lambda/service and
`/v2/` to another, enabling blue/green deployment of the API layer independently
of the data layer.
