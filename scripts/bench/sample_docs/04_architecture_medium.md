# Архитектура RAG-платформы

## Цель документа

Этот документ описывает текущую архитектуру системы и контракты между слоями. Используется как input для бенчмарка ёмкости и при онбординге новых разработчиков.

## Слои

### Frontend (Next.js, apps/web)

- App Router, серверные компоненты по умолчанию.
- tRPC для всего, что не публичный API.
- Аутентификация — cookie-based session, проксируется в FastAPI через `/auth/me`.
- Pipeline editor реализован как DAG-canvas, узлы = плагины, рёбра — порядок исполнения.

### Backend (FastAPI, apps/api)

- Python 3.11, SQLAlchemy 2.0 async, asyncpg.
- Routers по доменам: auth, datasets, keys, pipelines, experiments, runs, rag, billing, plugins, usage.
- Все routers подключены под префиксом `/api/v1` за исключением billing/usage (исторически — отдельный префикс).

### Plugin registry

- Каждый плагин — Python-класс, регистрируется через `@register_plugin("kind", "name")`.
- Виды плагинов: `loader`, `parser`, `chunker`, `embedder`, `retriever`, `reranker`, `generator`, `scorer`.
- Плагин принимает `params: dict[str, Any]` и валидируется JSON Schema.

### Postgres + pgvector

- Один кластер, multi-tenant: каждая таблица содержит `organization_id`.
- Векторное поле — `vector(1024)` (bge-m3) или `vector(1536)` (OpenAI), index `ivfflat` или `hnsw` в зависимости от размера датасета.
- BM25 — отдельный `tsvector` столбец с триггерным обновлением.

### Redis

- Сессии, rate-limiter, ARQ очереди (experiment_runner, golden_qa_generator).
- Один экземпляр, без кластеризации.

### Object storage (S3-compatible)

- Хранит исходные документы (raw bytes) для повторного парсинга.
- При удалении датасета файлы удаляются физически.

### LLM-провайдер

- Default: Ollama (локально на той же ноде) с моделью bge-m3 для эмбеддингов и deepseek-v4 для генерации.
- Fallback: LiteLLM-маршрутизация к OpenAI/Anthropic/Cohere если Ollama недоступен.

## Поток данных: ingest

1. Клиент шлёт `POST /api/v1/datasets/{id}/documents` (multipart).
2. API проверяет квоту хранилища и подписку.
3. Файл сохраняется в S3, метаданные пишутся в `documents`.
4. Текст извлекается parser-плагином (pdf, docx, html, md, plain).
5. Чанкер режет текст. Дефолт — `recursive-character`, chunk_size=512, overlap=64.
6. Каждый чанк эмбеддится синхронно в рамках того же HTTP-запроса.
7. Чанки записываются в `chunks` с populated `embedding` и `tsvector`.
8. Возвращается preview первых 5 чанков и общий count.

Узкие места:
- Embedding step доминирует: bge-m3 на CPU ~50ms/chunk, на GPU ~5ms/chunk.
- Сейчас всё происходит синхронно — большой документ блокирует HTTP-соединение. План: вынести в очередь.

## Поток данных: query

1. Клиент шлёт `POST /api/v1/rag/query` с Bearer API key.
2. API key валидируется, обновляется `last_used_at`.
3. Проверяется rate-limit и резервируется квота запросов.
4. Если указан `pipeline_id` — загружается published version, иначе используется default chain.
5. Query эмбеддится тем же эмбеддером, что и корпус.
6. Retriever возвращает top_k чанков (cosine + bm25, веса 0.6/0.4 по умолчанию).
7. Опциональный reranker меняет порядок (по умолчанию выключен).
8. Generator получает `system_prompt + context + question`, возвращает текст.
9. Run-запись пишется в БД с usage_tokens и cost_usd.
10. Audit log + usage event.

Узкие места:
- Generator (LLM call) — 1-3 секунды.
- Retriever — ~50 ms на дефолтном датасете до 100k чанков.
- Postgres connection pool: пул 20 на API, при 50 concurrent users часть блокируется.

## Контракты

### POST /datasets/{id}/documents

- Multipart: `file` (≤10 MB), `chunker_name`, `chunker_params` (JSON string).
- 201: `{document_id, chunk_count, embedded, chunks_preview}`.
- 402: либо нет подписки (`code=no_active_plan`), либо превышен storage (`code=storage_quota_exceeded`).
- 413: размер файла > 10 MB.
- 415: неподдерживаемый MIME/extension.
- 422: невалидные `chunker_params`.

### POST /rag/query

- Body: `{dataset_id, query, top_k?, pipeline_id?}`.
- 200: `{answer, chunks, usage, trace}`.
- 401: невалидный или отсутствующий Bearer.
- 402: исчерпан баланс при overage.
- 404: dataset не существует или не принадлежит этой org.
- 422: pipeline без published version.
- 429: rate-limit (per-org или per-key).

### POST /experiments

- Body: `{name, organization_id, dataset_id, plugin_grid}`.
- `plugin_grid` — `dict[str, list[NodeSpec]]`, slots обычно `chunkers/retrievers/generators`.
- 201: возвращает experiment с `status=queued`. Реальная работа идёт в ARQ-воркере.
- Статус — `queued | running | completed | failed | error | cancelled`.
- Ошибки на стороне scorer'а не валят весь experiment, помечаются per-combination.

## Безопасность

- Tenant isolation — на уровне ORM-фильтров `organization_id`. Проверяется в каждом router'е.
- API key — sha256-хэш в БД, raw возвращается только при создании.
- Cookie — HttpOnly, Secure (на проде), SameSite=Lax.
- CORS — белый список доменов из `RAGP_CORS_ORIGINS`.
- Rate-limit — token bucket в Redis: per-org и per-key.

## Наблюдаемость

- Структурированные логи (json), трейсы через OpenTelemetry (опционально).
- Метрики Prometheus — встроенный exporter в FastAPI.
- Алерты — пока вручную, dashboard в Grafana.

## Open questions

- Async ingest очередь — обсуждалось, не реализовано.
- Cost calibration — себестоимость одного query пока не сошлась с тарифной моделью.
- Multi-region — out of scope для пилота.

## Что меняется в ближайшем спринте

- Унесение embedding-фазы в ARQ-воркер.
- Per-tenant rate-limit с конфигом из плана.
- Прокидывание trace-id через все слои для дебага медленных запросов.
- Подключение второго embedder (multilingual-e5-large) как опции.
