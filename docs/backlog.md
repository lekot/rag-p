# Backlog — следующие задачи после Wave 2

После 2026-04-29 в main помержено 13 PR (Wave 2 + Wave 3 partial). Ниже — задачи, которые остались pending. Каждая описана как готовое ТЗ для Sonnet-агента в worktree-режиме.

Соглашение: исполнитель **НЕ запускает локально** `pytest`, `mypy`, `pnpm build/typecheck` — только `python -m py_compile` и `ruff format <file>`. Heavy проверки — в CI на ветке после push.

---

## 1. Password reset flow

**Why.** На проде нет способа восстановить пароль. После Wave 2 уже есть login rate-limit (защита от brute-force) и audit log базовый — пора закрыть оставшийся auth-gap.

**Endpoints (новые):**
- `POST /api/v1/auth/forgot-password` body `{email}` → всегда `200 {"detail": "If the email is registered, a reset link has been sent"}` (silent-success, чтобы не палить existence).
- `POST /api/v1/auth/reset-password` body `{token, new_password}` → `200` или `400 {"detail": "invalid_or_expired_token"}`.

**DB:** новая таблица `password_reset_tokens` (id uuid, user_id FK, token_hash unique sha256, expires_at NOT NULL, used_at nullable, created_at). Migration `0017_password_reset_tokens` (down_revision = `0016_api_key_lifecycle`).

**Web:**
- `apps/web/src/app/forgot-password/page.tsx`, `apps/web/src/app/reset-password/page.tsx`.
- Линк "Забыли пароль?" на `/login`.
- В `middleware.ts` — обе страницы public.

**Service:**
- `services/password_reset.py`: `request_reset(db, email)`, `complete_reset(db, token, new_password)`. Token = `secrets.token_hex(32)`, сравнение через `secrets.compare_digest`.
- `services/email.py`: `send_password_reset_email(to, link)`. Если `RAGP_SMTP_HOST=""` (default) — `logger.info` на link (dev mode для пилота). Иначе SMTP через `aiosmtplib`.
- `services/sessions.py`: `invalidate_user_sessions(db, user_id)` после успешного reset.
- `services/audit.py`: события `password_reset.requested`, `password_reset.completed`.

**Env:** `RAGP_SMTP_HOST`, `RAGP_SMTP_PORT=587`, `RAGP_SMTP_USER`, `RAGP_SMTP_PASSWORD`, `RAGP_SMTP_FROM`, `RAGP_SMTP_USE_TLS=true`, `RAGP_PASSWORD_RESET_TOKEN_TTL_MINUTES=60`.

**Test plan** (`tests/test_password_reset.py`):
- request_reset / unknown email → silent 200
- token expires after TTL
- single-use (повторное reset с тем же токеном — 400)
- sessions invalidated после успешного reset
- audit events записаны

**Acceptance:** 3 коммита (db migration / api+service / web pages), CI зелёный.

---

## 2. Audit log expansion

**Why.** Сейчас `services/audit.py` логирует только signup/login/logout/key.create/key.revoke. Для compliance и incident review нужны dataset/billing/key-scope события.

**Дополнить event types:**
- `dataset.upload`, `dataset.delete`
- `golden.generate`
- `experiment.start`, `experiment.promote`
- `billing.checkout`, `billing.subscription_started`, `billing.plan_switched`
- `key.scope_change`

**Где звать:**
- `routes_datasets.py` (upload/delete/golden handlers).
- `routes_experiments.py` (create/promote).
- `routes_billing.py` (checkout init, webhook successful → subscription started/switched).
- `routes_keys.py` (если будет endpoint для смены scope; пока нет — отложить эту строку).

**Test plan** (`tests/test_audit_expanded.py`):
- Каждое событие → запись в `audit_events` с правильным event_type, org_id, user_id, resource_id (если применимо), metadata_json.
- Audit fail-safe: при ошибке записи audit, основной endpoint не падает (это уже в audit.py:36-59).

**Acceptance:** 1-2 коммита, CI зелёный.

---

## 3. Queue contract enforcement (live/ingest/experiment/score/maintenance pools)

**Why.** Сейчас один ARQ pool обрабатывает всё. Experiment может задавить live query SLA. См. `docs/queue-contract-proposal.md` v0.

**Что делать:**

1. **Очереди** в ARQ: `rag.live`, `rag.ingest`, `rag.experiment`, `rag.score`, `rag.maintenance`. Каждая — отдельный `arq.WorkerSettings`-класс с своим `queue_name`, `max_jobs`, и `cron_jobs`.
2. **Compose services** — отдельные worker-deployment'ы:
   - `worker-live` (max_jobs=4, queue=rag.live)
   - `worker-ingest` (max_jobs=2, queue=rag.ingest)
   - `worker-experiment` (max_jobs=1, queue=rag.experiment + rag.score)
   - `worker-maintenance` (cron only)
3. **Per-tenant fairness**: redis sorted set `tenant_quota:{tenant_id}` в каждом enqueue-helper. При превышении — return 429 (для sync) или delay (для batch).
4. **Task envelope**: единый формат payload `{task_id, task_type, tenant_id, idempotency_key, ...}` (см. proposal section "Task envelope"). Все enqueue-helpers — единая обёртка `services/queue.py::enqueue(queue_name, task_type, payload, tenant_id, idempotency_key)`.
5. **Idempotency**: по `idempotency_key` через redis SETNX с TTL.

**Backpressure:**
- `rag.live` overload → 429 + Retry-After.
- `rag.ingest` overload → "quota exceeded" в response upload-endpoint.
- `rag.experiment` overload → schedule (queue position в response create_experiment).

**Большая задача — разбить на 3-4 PR'а:**
1. `feat(queue): single envelope + enqueue helper + idempotency`
2. `feat(queue): split workers per queue (live/ingest/experiment/maintenance)`
3. `feat(queue): per-tenant fairness via redis sorted sets`
4. `chore(queue): backpressure + 429/retry-after on overloaded routes`

**Test plan:** unit на envelope + idempotency, integration на per-tenant cap, load-test через `scripts/bench/` (можно reuse).

**Acceptance:** 4 PR'а последовательно, каждый CI зелёный.

---

## 4. Production e2e smoke (Playwright)

**Why.** После Wave 2 merge нужен end-to-end на проде: signup → /pricing → checkout sandbox → активный план → upload → ingest done → /rag/query через API key → 200 + answer.

**Что делать:**

- `tests/e2e/` (новый каталог) — Playwright tests:
  - `01_signup_and_pricing.spec.ts` — signup → ожидать редирект `/pricing?welcome=1`.
  - `02_subscription_and_quota.spec.ts` — выбор плана → YooKassa **sandbox** flow → возврат → активный план в `/account`.
  - `03_dataset_lifecycle.spec.ts` — upload .txt → ждать `indexed` status → search → ask с citations.
  - `04_api_key_and_rag_query.spec.ts` — create API key (read scope) → POST `/rag/query` → 200 + answer.
  - `05_quota_enforcement.spec.ts` — превысить query quota → 402.
  - `06_team_invite.spec.ts` — invite member → accept → видит datasets.
- Скриншоты на каждом шаге → артефакты.
- Diff против `prod-pricing-playwright.png`, `prod-signup.png` (existing baseline).

**Configuration:**
- `playwright.config.ts` — base URL `https://lekottt.ru`, timeout 30s.
- Test user — фиксированный test+yyyymmdd@lekottt.ru, пересоздаётся в before-all.
- YooKassa в test mode (`RAGP_YOOKASSA_TEST_MODE=true` на проде временно для smoke, либо отдельный test-org с pre-activated подпиской).

**Где запускать:**
- Локально через `pnpm exec playwright test`.
- В CI как отдельный job (post-deploy, на запросе через workflow_dispatch).

**Acceptance:** 6 spec файлов + playwright.config + CI workflow `e2e-smoke.yml`.

---

## 5. Прочее (low priority backlog)

- **MFA/2FA** через TOTP. После password reset — следующий enterprise blocker.
- **Settings page → Delete org** UI (backend `request_account_deletion` уже есть в GDPR PR).
- **Cron на cascade hard-delete** для GDPR `pending_deletion` orgs/users старше 30 дней.
- **Cohere config rotation runbook** (когда Amnezia ключ Maxim обновит, как через `gh secret set COHERE_AMNEZIA_CONF`).
- **n8n npm publish** — ветка `feat/n8n-community-node` смержена, но пакет не опубликован. Нужен manual `cd integrations/n8n && npm publish --access public`.
- **Vault/ESO** — отложено до KMS-backed инфры. Сейчас .env на хосте, ротация через CD secrets — приемлемо для пилота.

---

## Manual prod steps (после Wave 2 deploy)

Не код, но требуется от Макса вручную после CD завершения:

1. **GitHub Secrets** — добавить:
   - `COHERE_AMNEZIA_CONF` (multi-line, содержимое локального `cohere.awg.conf` в корне репо — gitignored).
   - `RAGP_PGBACKUP_S3_*` если bucket для backup'ов отдельный (или переиспользовать существующий `RAGP_S3_*`).
   - `GRAFANA_*` / `ALERTMANAGER_*` — **не нужны**, observability через Prometheus/Grafana отменили (хостер мониторит сервер).
   - **SMTP для password reset** (без них письмо со ссылкой не отправляется — link только в логах API):
     ```
     gh secret set RAGP_SMTP_HOST --env production --body "smtp.example.com"
     gh secret set RAGP_SMTP_USER --env production --body "noreply@lekottt.ru"
     gh secret set RAGP_SMTP_PASSWORD --env production --body "<app-password>"
     gh secret set RAGP_SMTP_FROM --env production --body "RAG-P <noreply@lekottt.ru>"
     ```
     Опционально через `gh variable set` (не секреты): `RAGP_SMTP_PORT` (default 587), `RAGP_SMTP_USE_TLS` (default true), `RAGP_PASSWORD_RESET_TOKEN_TTL_MINUTES` (default 60).

2. **Selectel S3** — создать bucket `rag-p-pg-backups` (или префикс в существующем).

3. **YooKassa** — поставить `RAGP_YOOKASSA_REQUIRE_IP_CHECK=true` и `RAGP_YOOKASSA_REVALIDATE_PAYMENT=true` в `.env` на хосте (defaults в коде = true, но фактический `.env` мог быть скопирован раньше).

4. **Smoke** — после deploy:
   - `curl https://api.lekottt.ru/healthz` → ok.
   - `curl -X POST https://api.lekottt.ru/api/v1/billing/webhook/yookassa -d '{}'` → теперь должен вернуть 403 ip_not_allowed (а не 200 как раньше).
   - Через UI: signup → /pricing редирект → upload .txt → /rag/query.

5. **n8n publish** — `cd integrations/n8n && npm publish --access public` если решено публиковать.

6. **Сохранить cohere.awg.conf** в безопасном месте (1Password, etc) — он gitignored, при потере локально нужно будет регенерировать из `cohere.vpn` URI.
