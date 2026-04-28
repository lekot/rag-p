# Queue Contract Proposal

Статус: proposed contract v0. Код начал двигаться в сторону ARQ/Redis, но этот контракт целиком ещё не реализован.

## Актуализация 2026-04-28

После ночных правок:

- `arq` и `redis` добавлены в API dependencies;
- Helm содержит worker deployment, включённый для staging;
- worker запускается через `arq ragp_api.workers.main.WorkerSettings`;
- появились фоновые maintenance задачи для usage/subscriptions;
- `routes_runs.py` всё ещё содержит TODO про async execution;
- разделение live/ingest/experiment/score/maintenance как SLA-контракт пока не зафиксировано в коде.

Вывод: broker выбран прагматично как ARQ/Redis для MVP, но queue contract всё ещё нужен. Следующий шаг не "выбрать библиотеку", а разнести классы работ, лимиты, retry/idempotency и метрики.

Отдельный внешний источник нагрузки:

- **n8n community node** будет слать machine-to-machine API calls. Для него особенно важны explicit 429/Retry-After, идемпотентные upload/index операции и понятные статусы long-running jobs.

## Текущее состояние

В исходном дизайне очереди были упомянуты, но не расписаны как контракт:

- `docs/architecture.md` упоминает async workers и Redis queue;
- ADR 0005 упоминает Hatchet/Celery для async experiment execution;
- `routes_runs.py`, `routes_experiments.py`, `experiment_runner.py` содержат TODO про queue/background task;
- Helm chart содержит `worker-deployment.yaml`; сейчас он уже ближе к рабочему ARQ path, но пока без полного разделения очередей и SLA.

Вывод: отдельного queue contract как source of truth всё ещё нет.

## Зачем нужен контракт

Нам нужны разные классы работ с разным SLA:

- live RAG query должен отвечать быстро;
- ingest может подождать;
- experiment/scoring может ждать дольше всех;
- maintenance/reindex не должен мешать клиентскому пути.

Один общий worker pool без приоритетов приведёт к тому, что experiment забьёт кластер, а живые запросы будут ждать.

Главный принцип:

```text
live query capacity is reserved
batch experiment capacity is throttled
tenant fairness is enforced before raw throughput
```

## Предлагаемые очереди

### `rag.live`

Интерактивные запросы клиента к уже построенному RAG.

Examples:

- retrieve contexts;
- generate answer;
- return answer with sources.

SLA:

- latency-sensitive;
- highest priority;
- не должен блокироваться ingest/experiment задачами;
- должен иметь reserved workers.

Concurrency:

- ограничение per tenant;
- глобальный лимит по live worker pool;
- при перегрузе лучше вернуть 429/503 с retry-after, чем ждать минуты.

### `rag.ingest`

Загрузка и подготовка корпуса.

Examples:

- parse document;
- chunk text;
- embed chunks;
- write vectors;
- update document/index status.

SLA:

- medium priority;
- может ждать;
- не должен съедать live capacity;
- должен иметь progress state.

Concurrency:

- per tenant ingest limit;
- per cluster embedding limit;
- отдельный лимит на Ollama embedding runtime.

### `rag.experiment`

Batch experiment orchestration.

Examples:

- expand experiment into pipeline variants;
- enqueue scoring jobs;
- aggregate leaderboard;
- calculate composite score.

SLA:

- low priority;
- может ждать дольше;
- должен быть resumable;
- должен уметь partial progress;
- должен иметь preflight estimate.

Concurrency:

- strict per tenant limit;
- global experiment limit;
- может использовать только leftover capacity или scheduled windows.

### `rag.score`

Атомарные scoring jobs, порождённые experiment.

Examples:

- run one question through one pipeline variant;
- calculate one metric/scorer pass;
- persist score result.

SLA:

- low priority;
- retryable;
- idempotent;
- expensive enough to meter.

Capacity metric:

```text
scoring_units_per_hour
```

### `rag.maintenance`

Фоновые системные задачи.

Examples:

- reindex;
- cleanup;
- refresh derived stats;
- retry dead-lettered jobs manually.

SLA:

- lowest priority;
- scheduled/off-peak by default.

## Приоритеты

Приоритеты не должны быть единственным механизмом защиты. Нужны отдельные очереди и worker pools.

Recommended order:

```text
rag.live        highest, reserved
rag.ingest      medium
rag.experiment  low orchestration
rag.score       low batch compute
rag.maintenance lowest
```

Важно: если использовать Celery/RabbitMQ priority queues, нужно учитывать prefetch. Для отзывчивости high-priority tasks нужен маленький prefetch, например `worker_prefetch_multiplier = 1`, иначе worker может заранее забрать low-priority jobs.

## Worker pools

### `live-worker`

Consumes:

- `rag.live`

Never consumes:

- `rag.experiment`;
- `rag.score`;
- `rag.maintenance`.

Purpose: защитить interactive SLA.

### `ingest-worker`

Consumes:

- `rag.ingest`

Optional:

- small `rag.maintenance` jobs during idle.

Purpose: document processing and embeddings.

### `experiment-worker`

Consumes:

- `rag.experiment`;
- `rag.score`.

Purpose: batch scoring and leaderboard calculation.

### `maintenance-worker`

Consumes:

- `rag.maintenance`;
- dead-letter retries by explicit command.

## Task envelope

Every queued task should use a common envelope:

```json
{
  "task_id": "uuid",
  "task_type": "rag.score.run_question",
  "tenant_id": "org_123",
  "actor_user_id": "user_123",
  "priority": "live|normal|batch|maintenance",
  "idempotency_key": "stable-key",
  "created_at": "2026-04-27T00:00:00Z",
  "not_before": null,
  "deadline_at": null,
  "attempt": 1,
  "max_attempts": 3,
  "payload": {}
}
```

Required fields:

- `task_id`;
- `task_type`;
- `tenant_id`;
- `priority`;
- `idempotency_key`;
- `payload`.

Optional but recommended:

- `actor_user_id`;
- `deadline_at`;
- `not_before`;
- `max_attempts`;
- correlation/trace IDs.

## Idempotency

All queue tasks must be idempotent.

Recommended idempotency keys:

```text
ingest document:
  tenant_id + dataset_id + document_id + content_hash + chunker_config_hash

live query:
  tenant_id + request_id

score unit:
  tenant_id + experiment_id + question_id + pipeline_variant_id + scorer_id

leaderboard aggregate:
  tenant_id + experiment_id + leaderboard_version
```

If a task is retried, it should update the same DB row, not create duplicate results.

## State model

Each long-running domain object should have explicit status.

Documents:

```text
uploaded -> parsing -> chunking -> embedding -> indexed -> failed
```

Runs/live queries:

```text
queued -> running -> completed -> failed -> cancelled
```

Experiments:

```text
draft -> estimated -> queued -> running -> partially_completed -> completed -> failed -> cancelled
```

Score units:

```text
queued -> running -> completed -> failed -> skipped
```

## Backpressure

Backpressure is part of the contract.

When `rag.live` is overloaded:

- return 429 or 503;
- include retry-after;
- do not silently enqueue unbounded live work.

When `rag.ingest` is overloaded:

- accept only within tenant quota;
- otherwise return "quota exceeded" or "try later";
- show queue position/estimated start where possible.

When `rag.experiment` is overloaded:

- allow scheduling;
- show estimate;
- do not start if tenant/global concurrency is exhausted.

## Tenant fairness

Minimum rules:

- max live concurrency per tenant;
- max ingest jobs per tenant;
- max active experiments per tenant;
- max score units in flight per tenant;
- max queued jobs per tenant.

Example initial defaults:

```text
live queries:        1-2 concurrent per tenant
ingest jobs:         1 concurrent per tenant
active experiments:  1 concurrent per tenant
score units:         bounded by plan
```

These are placeholders until benchmark data exists.

## Retry and dead-letter policy

Retryable:

- transient network error;
- Ollama temporarily unavailable;
- Postgres serialization/deadlock;
- worker crash.

Not retryable:

- invalid plugin config;
- missing tenant/resource;
- quota exceeded;
- unsupported file type.

Policy:

```text
max_attempts: 3 by default
backoff: exponential with jitter
dead-letter queue: required for exhausted retries
manual retry: admin-only
```

Dead-letter payload must preserve:

- original task envelope;
- last error;
- attempts count;
- timestamps.

## Metrics

Queue system must emit:

- queue depth by queue;
- oldest task age by queue;
- running jobs by queue;
- jobs/sec by queue;
- failure rate by task type;
- retry count;
- dead-letter count;
- per tenant queue depth;
- per tenant active jobs;
- live query p50/p95/p99;
- scoring units per hour.

For economics:

- CPU/RAM seconds by task type;
- Ollama runtime seconds;
- Postgres query time;
- vector index growth;
- storage bytes per tenant.

## Broker choice

ARQ/Redis is the current MVP direction because it is already present in code and Helm. This section keeps alternatives as fallback options.

Pragmatic MVP options:

### ARQ + Redis

Pros:

- already added to API dependencies and Helm;
- fits async Python/FastAPI without a Celery compatibility layer;
- lower operational weight than RabbitMQ/Hatchet;
- enough for MVP worker pools, retries and cron jobs.

Cons:

- priority/fair scheduling must be explicit in queues/pools and DB state;
- fewer enterprise workflow patterns than Celery/RabbitMQ;
- long-running experiment orchestration may need an additional DB-backed coordinator.

Recommended current MVP choice:

```text
ARQ + Redis, with separate queues/pools and DB-backed idempotency.
```

### Celery + Redis

Pros:

- Redis already exists in chart;
- fastest path;
- good enough for early async jobs.

Cons:

- priority semantics are less clean than RabbitMQ;
- careful configuration needed for prefetch and reliability.

### Celery + RabbitMQ

Pros:

- mature task queue setup;
- RabbitMQ supports priority queues;
- good fit for separate queues and worker pools.

Cons:

- adds another service to operate;
- priority queues are harder to reason about than FIFO;
- still need separate pools for live vs batch.

### Hatchet

Pros:

- workflow-level concurrency;
- per-tenant fairness maps well to experiments;
- better fit for long-running workflows.

Cons:

- heavier adoption;
- more moving parts;
- probably too much before the product path is closed.

Fallback / later options:

```text
Celery + RabbitMQ if queue correctness and priority semantics matter immediately.
Hatchet later if experiments become the core workflow engine.
```

ARQ should remain the default unless benchmarks or reliability requirements prove it insufficient.

## API contract sketch

### Live query

```http
POST /api/v1/query
```

Behavior:

- synchronous if capacity is available;
- returns answer/sources;
- can return 429/503 under overload.

### Ingest

```http
POST /api/v1/datasets/{dataset_id}/documents
```

Behavior:

- creates document;
- enqueues ingest task;
- returns document id and status;
- client polls document status or subscribes later.

### Experiment estimate

```http
POST /api/v1/experiments/estimate
```

Returns:

- questions count;
- pipeline variants count;
- scorer metrics count;
- scoring units;
- estimated duration;
- estimated credit cost.

### Experiment start

```http
POST /api/v1/experiments
```

Behavior:

- creates experiment;
- enqueues orchestration;
- experiment worker expands score units;
- score workers process bounded queue.

## Open questions

- Do live queries run synchronously in API process or through `rag.live` queue with short timeout?
- Is Ollama shared between ingest embeddings and live generation, or do we split models/runtimes?
- Do experiments run only during scheduled windows on cheap plans?
- What is the first paid-plan concurrency limit?
- Do we need per-tenant fair scheduling in broker, or is separate DB scheduler enough for MVP?
- Where do progress events live: polling, SSE, WebSocket, or tRPC subscription?
