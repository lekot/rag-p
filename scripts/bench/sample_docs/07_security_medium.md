# Security model

This document describes the security boundaries of the RAG Platform. It is the canonical input for threat-modelling exercises and pentest scoping.

## Trust boundaries

1. Public Internet → CDN/Caddy edge.
2. Edge → API process (FastAPI, container).
3. API → Postgres / Redis / S3 (private network).
4. API → External LLM providers (Internet egress only on this leg).

## Authentication

### Browser sessions

- Cookie name: `ragp_session`.
- Format: `<user_id>:<org_id>:<hmac>` where HMAC is SHA-256 of payload signed with `RAGP_SESSION_SECRET`.
- Lifetime: 14 days, sliding (extended on every authenticated request).
- HttpOnly, SameSite=Lax, Secure on prod, host-only.

### API keys

- Format: `rgp_<32 hex chars>`.
- Stored as SHA-256 hash plus a 8-char prefix used for display ("rgp_abcd...").
- Plaintext returned exactly once on creation; not retrievable thereafter.
- Last-used timestamp updated lazily (not on every call) to reduce write amplification.

## Authorization

All endpoints fall into one of three buckets:

- **Public**: no auth required (`/health`, `/pricing` static).
- **Session**: requires valid cookie. Most dashboard endpoints.
- **API key**: requires Bearer token. Currently only `/rag/query`.

Tenant isolation is enforced at the ORM layer. Every query against a tenant-scoped table includes `WHERE organization_id = :org`. There is a dedicated dependency `require_organization` that returns the current org id from session or API key context — endpoints must use it instead of trusting client-supplied `organization_id`.

## Known weaknesses (P0/P1 backlog)

- Some legacy endpoints (`POST /experiments`) still accept `organization_id` in the request body. The router cross-checks the dataset against the session org before persisting, but the contract is fragile and should be migrated to the dependency-only pattern.
- API keys do not yet have scopes. A leaked key gives full `/rag/query` access for the org. Scope (`rag:read`, `rag:write`, `dataset:write`) is on the backlog.
- No IP allow-list for API keys — out of scope for the pilot.

## Secrets management

- All secrets live in environment variables, prefix `RAGP_`.
- Production secrets are stored in 1Password; the deploy pipeline pulls them into a `.env.prod` rendered by `op` CLI.
- Secrets are never logged. `settings.py` masks `*secret*` and `*key*` fields when emitting startup banner.

## Rate limiting

Token bucket in Redis, two granularities:

- Per-organization: shared across all keys.
- Per-API-key: stricter, prevents one leaked key from burning the org quota.

Default limits (Free plan):
- 10 requests/sec/org, burst 20.
- 5 requests/sec/key, burst 10.

Higher tiers raise both linearly. Limits are enforced *before* any LLM call to avoid spending money on requests that will be rejected.

## Audit log

Every privileged action writes a row to `audit_events`:

- `dataset.create`, `dataset.delete`.
- `key.create`, `key.delete`.
- `pipeline.publish`, `pipeline.delete`.
- `experiment.create`, `experiment.cancel`.
- `subscription.start`, `subscription.cancel`.
- `member.invite`, `member.role_change`, `member.remove`.

Each event carries `org_id`, `user_id`, `event_type`, `resource_type`, `resource_id`, `metadata` (jsonb), `created_at`, `request_ip`, `user_agent`.

## Input validation

- Pydantic models on every endpoint.
- File uploads: MIME + extension whitelist, 10 MB hard cap.
- JSON params validated against plugin `params_schema` (JSON Schema 2020-12).
- SQL — only SQLAlchemy expression API; no raw `text()` on user input.

## Output handling

- All API responses are JSON.
- Markdown rendered in the frontend uses a sanitiser (DOMPurify) before insertion into the DOM.
- API responses do not include sensitive headers (no `Set-Cookie` leak from upstream services).

## Dependency hygiene

- Python deps pinned in `pyproject.toml` with hash-locked `uv.lock`.
- JS deps pinned in `pnpm-lock.yaml`.
- Dependabot enabled on the GitHub repo. Auto-merge for patches; manual review for minor/major.

## Incident response

Documented in `docs/incident-response.md` (TODO). High-level:

1. Triage in #ops Slack channel.
2. Pause writes if a data-corruption suspicion arises (toggle a flag in Redis).
3. Forensics via audit log + Postgres point-in-time recovery if needed.
4. Post-mortem within 48 hours; published in `docs/post-mortems/`.

## Deletion and right-to-be-forgotten

- Org deletion is hard-delete: all rows under `organization_id` plus all S3 objects.
- Data is also purged from Redis (sessions, rate-limit buckets, queue depth metadata).
- Backups age out within 30 days; deletion is therefore complete after ~31 days end-to-end.
- A user can delete their account independently from the org if they are not the only owner; the org is reassigned to another owner.

## Compliance posture

This is a pilot. No formal certifications (SOC 2, ISO 27001) yet. The architecture is built to support them later — audit log, encryption-at-rest, immutable backups, hash-only secrets.
