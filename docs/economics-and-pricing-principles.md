# Economics and Pricing Principles

Статус: рабочая модель для обсуждения. Числа ниже не являются публичными тарифами.

## Актуализация 2026-04-28

После ночных правок появились публичные тарифные уровни и subscription/billing код, но это ещё не закрывает экономику.

Текущий статус:

- pricing UI и плановые квоты появились;
- YooKassa acquiring учтён в расчётах;
- welcome bonus убран;
- subscription enforcement находится в работе и требует ревью атомарности, idempotency и тестов;
- тарифы всё ещё должны быть подтверждены benchmark'ами ingest/query/experiment capacity.

Отдельный продуктовый канал, который нужно заложить в экономику:

- **n8n community node**. Пользователи n8n могут быть естественной аудиторией RAG Platform, потому что им нужен готовый RAG step внутри workflow. Для тарификации это важно: n8n-использование будет чаще выглядеть как machine-to-machine live queries и batch automations, а не как ручная работа в UI.

Минимальные метрики для n8n-канала:

- количество query calls per workflow execution;
- burstiness по расписанию/trigger'ам;
- retry behavior со стороны n8n;
- средний размер входного вопроса и контекста;
- доля upload/index jobs из workflow;
- tenant-level concurrency и rate limits для API keys.

## Контекст

Текущая инфраструктура пилота стоит около $130/мес:

- балансировщик;
- одна manager-нода кластера;
- одна worker-нода 2 CPU / 8 GB RAM / 40 GB boot SSD;
- 20 GB network SSD.

Грубая оценка для отказоустойчивого пилота: $300+/мес при расширении Kubernetes до нескольких нод. Это всё ещё "минимально живое" железо, не доказанная ёмкость под реальные нагрузки.

Рабочее допущение для первичной модели:

- текущий кластер выдерживает 2 клиентов;
- отказоустойчивый кластер выдерживает 4 клиентов;
- это надо подтвердить замерами, а не считать фактом.

## Главный принцип

Тарифы нельзя выводить напрямую из стоимости кластера. Стоимость кластера даёт только infra floor.

Тариф должен строиться от измеренной ёмкости:

- ingest capacity;
- query capacity;
- experiment/scoring capacity;
- storage/chunks growth;
- tenant concurrency;
- деградация live-запросов при фоновых задачах.

Иначе можно легко получить красивый тариф с отрицательной экономикой.

## Что именно тарифицировать

### 1. Workspace / tenant base

Фиксированная плата за tenant/project:

- доступ к UI/API;
- хранение метаданных;
- минимальная квота документов;
- минимальная квота live-запросов;
- доля постоянной инфраструктуры.

Формула raw infra floor per tenant:

```text
base_infra_cost_per_tenant =
  cluster_month_cost / expected_active_tenants
```

Примеры:

```text
$130 / 2 tenants = $65 raw infra / tenant / month
$300 / 4 tenants = $75 raw infra / tenant / month
```

Это только себестоимость инфраструктуры без маржи, поддержки, idle, failed jobs, мониторинга и разработки.

### 2. Indexed corpus

Клиент мыслит документами, страницами или GB. Система платит за chunks, embeddings, index size и storage.

Публично можно продавать:

- GB документов;
- количество документов;
- количество страниц;
- количество "indexed characters".

Внутренне считать нужно:

```text
indexed_corpus_cost =
  ingest_compute_cost
  + embedding_compute_cost
  + storage_cost
  + vector_index_growth_cost
```

Полезные внутренние метрики:

- `documents_count`;
- `raw_bytes`;
- `parsed_chars`;
- `chunks_count`;
- `embedding_dim`;
- `vector_storage_bytes`;
- `index_build_time_seconds`;
- `index_update_time_seconds`.

### 3. Live RAG queries

Live-запрос — это интерактивный пользовательский запрос, который не должен ждать эксперимент.

Внутренняя стоимость:

```text
live_query_cost =
  retrieval_cost
  + optional_rerank_cost
  + generation_cost
  + api/web overhead
```

Если используется Ollama/local model, внешнего token bill может не быть, но стоимость всё равно есть:

- CPU/RAM;
- занятый model runtime;
- latency;
- очередь;
- opportunity cost: пока модель отвечает одному клиенту, она не отвечает другому.

Публично это можно продавать как пакеты:

- `N` live-запросов в месяц;
- extra query credits;
- лимиты concurrency per tenant;
- лимиты max context / output size.

### 4. Experiments / scoring

Experiment нельзя смешивать с live-запросами. Это batch workload с мультипликатором нагрузки.

Базовая единица:

```text
1 scoring unit =
  1 question
  × 1 pipeline variant
  × 1 scorer/metric pass
```

Размер эксперимента:

```text
experiment_units =
  dataset_questions
  × pipeline_variants
  × scorer_metrics
```

Пример:

```text
100 questions × 12 pipeline variants × 4 metrics = 4800 scoring units
```

Raw infra cost эксперимента можно считать двумя способами.

Через долю кластера:

```text
experiment_raw_cost =
  cluster_month_cost
  × (experiment_duration_hours / 730)
  × cluster_capacity_share
```

Через пропускную способность scoring units:

```text
cluster_hour_cost = cluster_month_cost / 730

cost_per_scoring_unit =
  cluster_hour_cost / scoring_units_per_cluster_hour

experiment_raw_cost =
  experiment_units × cost_per_scoring_unit
```

Вторая модель лучше для тарифов, потому что эксперимент на 20 вопросов и 3 варианта не равен эксперименту на 500 вопросов и 40 вариантов.

## Utilization и параллельность

Себестоимость падает при росте utilization, но только пока не деградируют live-запросы.

Нужно измерить:

```text
max_parallel_live_queries
max_parallel_ingest_jobs
max_parallel_experiments
scoring_units_per_hour
live_query_p95_with_no_experiment
live_query_p95_with_experiments
```

Если experiment может идти в фоне и ждать, ему можно давать оставшуюся ёмкость. Но live query должен иметь reserved capacity.

Рабочий принцип:

```text
live capacity is reserved
experiment capacity is opportunistic or scheduled
```

## Минимальные замеры перед тарифами

Для текущего кластера и для отказоустойчивого пилота нужно прогнать одинаковый benchmark.

### Ingest benchmark

- corpus size: 10 MB, 100 MB, 1 GB;
- document types: md/txt first, later pdf/docx/html;
- chunks count;
- embedding time через Ollama;
- storage growth;
- Postgres/vector index growth;
- failure/retry rate.

### Live query benchmark

- p50/p95/p99 latency;
- max concurrent live queries;
- answer quality smoke;
- CPU/RAM/Ollama/Postgres bottleneck;
- degradation while ingest is running;
- degradation while experiment is running.

### Experiment benchmark

- dataset sizes: 20, 100, 500 questions;
- pipeline variants: 1, 4, 12, 40;
- scorer metrics: 1, 4;
- total duration;
- scoring units per hour;
- max parallel experiments before live p95 breaks.

## Pricing shape

Предварительная структура тарифов:

```text
monthly_plan =
  workspace_base
  + included_corpus_quota
  + included_live_query_quota
  + included_experiment_credits

overage =
  extra_indexed_corpus
  + extra_live_queries
  + extra_scoring_units
```

Публичные единицы должны быть простыми:

- documents/pages/GB for corpus;
- questions for live RAG;
- experiment credits for scoring.

Внутренние единицы должны быть точными:

- chunks;
- tokens/chars;
- vectors;
- scoring units;
- CPU/RAM seconds;
- model runtime seconds.

## Важные ограничения

- Эксперименты должны иметь visible preflight estimate: сколько questions, variants, scoring units и примерное время.
- Tenant должен иметь quota, иначе один клиент может съесть весь кластер.
- Free/unlimited experiments давать нельзя.
- Live query и experiment workloads должны быть разнесены очередями и worker pools.
- Пока нет auth/access control, любой знающий адрес может генерировать cost.
- Для n8n/API клиентов нужны отдельные API-key лимиты: запросы из automation workflow могут приходить пачками и должны получать 429/Retry-After, а не ломать live UI.

## Открытые вопросы

- Какой минимальный paid plan покрывает infra floor и support?
- Продаём ли self-host license отдельно от managed usage?
- Будет ли public API endpoint для клиентских RAG-запросов или только UI?
- Какой public contract у n8n community node: только query или ещё upload/index/status?
- Как тарифицировать re-index после обновления корпуса?
- Считаем ли failed experiment units платными, если ошибка в нашей инфраструктуре?
- Нужен ли scheduled/batch window для дешёвых экспериментов?
