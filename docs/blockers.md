# Blockers — night run 2026-04-27/28

Открытые блокеры и архитектурные дилеммы, найденные во время автономного прогона. Каждый пункт помечен `[BLOCKED-NIGHT-RUN]`. Назначение: дать утреннему ревью список того, что НЕ было решено и почему.

Формат:

```
## [BLOCKED-NIGHT-RUN] <короткий заголовок>
- **Where**: <файл/компонент>
- **Why blocked**: <причина — нужен внешний ввод / решение Макса / стоимость>
- **Workaround applied**: <что я временно сделал, если что-то>
- **Decision needed**: <что нужно решить чтобы разблокировать>
```

---

## ~~[BLOCKED-NIGHT-RUN] P0 tenant isolation: UI использует shared/default org~~ RESOLVED

- **Where**: `apps/web/src/server/context.ts`, `apps/web/src/server/routers/datasets.ts`, `apps/api/src/ragp_api/api/v1/routes_datasets.py`, `apps/api/src/ragp_api/deps_auth.py`.
- **Observed 2026-04-28**: после регистрации новый пользователь видит существующие datasets. Это не похоже на админский email; текущий web context подставляет `NEXT_PUBLIC_ORG_ID` / `00000000-0000-0000-0000-000000000001`, а API `GET /datasets?organization_id=...` доверяет org id из query.
- **Resolved 2026-04-28**: datasets API теперь берёт org scope из session/API key (`require_organization`), legacy `X-Organization-Id` выключен по умолчанию и включается только в test/dev config. Web context больше не использует `NEXT_PUBLIC_ORG_ID`, а получает org через `/auth/me`; upload идёт через Next same-origin proxy с cookie. Добавлен negative test: пользователь B не видит dataset пользователя A, query/body/header не могут подменить org.

---

## [BLOCKED-NIGHT-RUN] Celery/ARQ для experiment runner

- **Where**: `apps/api/src/ragp_api/services/experiment_runner.py`, `routes_experiments.py`
- **Status update 2026-04-28**: ARQ/Redis выбран де-факто для MVP: dependency, Helm worker deployment и staging flag уже появились.
- **Why still blocked**: experiment runner и queue SLA ещё не сведены в production contract: нет явного разделения live/ingest/experiment/score/maintenance pools, fairness, idempotency и backpressure.
- **Workaround applied**: ARQ worker path есть, но часть execution path всё ещё синхронная/частичная.
- **Decision needed**: Утвердить ARQ как MVP broker и реализовать queue contract из `docs/queue-contract-proposal.md`.

---

## ~~[BLOCKED-NIGHT-RUN] Self-test метрика — прокси без golden Q&A~~ RESOLVED (Phase 5)

- **Where**: `apps/api/src/ragp_api/services/experiment_runner.py`
- **Resolved**: Phase 5 реализована. `POST /datasets/{id}/golden` генерирует golden Q&A через DeepSeek по чанкам. Когда golden items есть — experiment runner использует `retrieval_hit` + `answer_similarity` вместо self-test heuristic.
- **Fallback**: Self-test hit-rate остаётся как запасной вариант когда golden items отсутствуют.

---

## ~~[BLOCKED-NIGHT-RUN] Токены usage в pipeline-path ask~~ RESOLVED

- **Where**: `apps/api/src/ragp_api/api/v1/routes_datasets.py::ask_dataset` (pipeline path)
- **Resolved**: `run_pipeline` агрегирует usage из всех generator-трейсов и возвращает `{"usage": {"prompt_tokens": N, "completion_tokens": M}}`. `ask_dataset` и `rag/query` (pipeline path) используют это значение в AskOut/RagQueryOut. Тест `test_ask_pipeline_path_returns_usage` добавлен.

---

## ~~[BLOCKED-NIGHT-RUN] Pre-existing test failure — test_plugins_registry~~ RESOLVED

- **Where**: `apps/api/tests/test_plugins_registry.py`
- **Resolved**: `EXPECTED_NAMES` дополнен `ollama-embedder` и `cohere-embedder`. Тест переименован в `test_registry_has_all_expected_plugins` (стало 8 плагинов, не 6). Все 5 тестов в файле проходят.

---

## ~~[BLOCKED-NIGHT-RUN] Pytest не в CI gate~~ RESOLVED

- **Where**: `.github/workflows/ci.yml`
- **Resolved**: CI теперь содержит pytest job с Postgres/pgvector service, `uv sync --all-packages --all-extras` и `uv run pytest`.

---

## [BLOCKED-NIGHT-RUN] n8n community node как продуктовый вход

- **Where**: будущий integration package / docs / public API contract.
- **Why blocked**: Есть `POST /api/v1/rag/query` и API keys, но нет zero-code интеграции для n8n users.
- **Workaround applied**: Пользователь может дергать HTTP Request node вручную по `/docs`, но это не community node и не polished journey.
- **Decision needed**: Спроектировать n8n node contract: credentials, query action, upload/index action, status polling, examples, rate-limit semantics.

---

## [BLOCKED-NIGHT-RUN] Atomic Q reservation for live API usage

- **Where**: `services/rate_limiter.py`, `services/usage.py`, `routes_rag.py`.
- **Why blocked**: Сейчас preflight проверяет `q_used`, а списание Q выполняется после генерации в usage tracking. Это лучше прежнего wallet-only gate, но ещё не идеальный enterprise contract: при гонках и fail-open usage recording возможен перерасход сверх hard quota.
- **Workaround applied**: Подписка и rate limit уже блокируют очевидные no-plan/quota-exceeded кейсы; для YooKassa/subscription lifecycle добавлена DB idempotency.
- **Decision needed**: Ввести явный `reserve_q` до генерации после проверки dataset/pipeline ownership, а `record_usage_event` оставить только для audit/cost/overage settlement. Нужно одновременно обновить старые billing/rag tests с wallet-model на subscription-model.

<!-- ОТКРЫТЫЕ БЛОКЕРЫ ДОБАВЛЯЮТСЯ ВЫШЕ ЭТОЙ ЛИНИИ -->
