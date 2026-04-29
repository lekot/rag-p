# Economics benchmark — отчёт сессии

> Шаблон. Скопируй в `docs/economics-benchmark-<YYYY-MM-DD>.md` и заполняй
> по ходу сессии. Цель — закрыть гэп из
> `architecture-review-2026-04-27.md` секции «Себестоимость и ёмкость».

## 0. Сводка

- **Дата сессии:** YYYY-MM-DD HH:MM ... HH:MM (Europe/Moscow)
- **Оператор:** _(Maks)_
- **Окружение:** prod (`https://api.lekottt.ru`), коммит API: `<sha>`, web: `<sha>`
- **Версия скриптов:** `scripts/bench/` @ `<sha>`
- **Hardware floor:** _(заполнить — текущий: 1 manager + 1 worker 2 CPU / 8 GB / 40 GB SSD, 12 000 ₽/мес)_

## 1. Подготовка

- [ ] Активирован план (вариант A / вариант B): _(описать)_
- [ ] `seed_dataset.py` отработал, env-блок сохранён
- [ ] Golden Q&A сгенерирован, count: _N_
- [ ] Корпус: 12 файлов, _N_ MB, чанков после ingest: _N_
- [ ] `snapshot_resources.sh` стартовал в параллельном tmux

## 2. Ingest capacity

### Сценарии

| Run                 | Users | Duration | Файлов залито | Bytes      |
|---------------------|------:|---------:|--------------:|-----------:|
| ingest-u1           |     1 |     5 m  |               |            |
| ingest-u3           |     3 |     5 m  |               |            |
| ingest-u5           |     5 |     5 m  |               |            |
| ingest-u10          |    10 |     5 m  |               |            |

### Результаты (вставь из `analyze_results.py`)

```
<paste markdown table from results/ingest-summary.md>
```

### Производные

- Средняя пропускная способность embedder: _N MB/sec_, _N chunks/sec_.
- Saturation point: _N concurrent users_.
- Bottleneck: _(CPU api / Ollama / Postgres / disk)_.
- Стоимость одного ingest: _N USD/MB_ при текущем железе.

## 3. Query latency

### Сценарии

| Run        | Users | Duration | Total req | Errors |
|------------|------:|---------:|----------:|-------:|
| query-c1   |     1 |    5 m   |           |        |
| query-c5   |     5 |    5 m   |           |        |
| query-c10  |    10 |    5 m   |           |        |
| query-c50  |    50 |    5 m   |           |        |

### Результаты

```
<paste markdown table from results/query-summary.md>
```

### Производные

- p50 / p95 / p99 при U=1: _N ms_.
- p50 / p95 / p99 при U=10: _N ms_.
- p50 / p95 / p99 при U=50: _N ms_.
- Точка деградации: _N concurrent users_, после которой p99 уходит за бюджет _X ms_.
- Bottleneck: _(generator / retriever / pgvector / network)_.
- Стоимость одного query: _N USD_ (embed + retrieve + LLM tokens по pricing провайдера).

## 4. Experiment throughput

### Сценарии

| Run              | Users | Grid    | Combos | Run-time | Завершилось |
|------------------|------:|---------|-------:|---------:|------------:|
| exp-small-u1     |     1 | small   |      1 |    30 m  |             |
| exp-medium-u3    |     3 | medium  |      4 |    1 h   |             |
| exp-large-u1     |     1 | large   |     12 |    1 h   |             |

### Результаты

```
<paste markdown table from results/exp-summary.md>
```

### Производные

- Средняя длительность одного combo: _N sec_.
- Combos/min: _N_.
- Comb./min при 3 параллельных experiment'ах: _N_ — линейно? сублинейно?
- Что ломается первым: _(scorer / generator API quota / Postgres / Ollama)_.
- Сколько full grid (12 combos) клиент может прогнать за час: _N_.

## 5. Resource usage

### docker stats summary

| Сервис   | Peak CPU% | Peak RAM | Peak Net I/O | Peak Block I/O |
|----------|----------:|---------:|-------------:|---------------:|
| api      |           |          |              |                |
| worker   |           |          |              |                |
| postgres |           |          |              |                |
| redis    |           |          |              |                |
| caddy    |           |          |              |                |

(вставить картинки/CSV из `results/resources-*/docker_stats.csv`)

### Postgres

- Peak active connections: _N_ (limit: _N_).
- `idle in transaction`: _N_ (норма: 0–1).
- Slow queries (>500 ms): _какие_, _сколько раз_.
- Blocked queries: _N_.

## 6. Себестоимость и тарифы

### Стоимость на текущем железе (12 000 ₽/мес)

- Один ingest 1 MB: _N ₽_.
- Один query: _N ₽_.
- Один experiment medium-grid (4 combos, 100-Q golden): _N ₽_.

### Сравнение с заявленными тарифами

| План  | Запросов/мес | Расчётная себест. за лимит | Цена | Маржа |
|-------|-------------:|---------------------------:|-----:|------:|
| Free  | 100          |                            |    0 |       |
| Solo  | 5 000        |                            |  990 |       |
| Team  | 50 000       |                            | 4 990|       |
| Pro   | 500 000      |                            |19 990|       |

### Tenant capacity

- Сколько одновременно активных tenants выдержит текущее железо: _N_.
- При каком %% load один tenant начинает мешать другому: _N_.
- Нужен ли queue/backpressure прямо сейчас: _да / нет, обоснование_.

## 7. Выводы

- [ ] Тарифная модель **подтверждена** / **требует пересмотра** (см. §6).
- [ ] Острые backlog-айтемы (приоритет P0):
  - _..._
- [ ] Backlog P1:
  - _..._

## 8. Артефакты

- `results/query-c1..50_stats.csv` ✅
- `results/ingest-u1..10_stats.csv` ✅
- `results/exp-*_stats.csv` ✅
- `results/resources-*/docker_stats.csv` ✅
- `results/resources-*/pg_stat_activity.csv` ✅
- Этот отчёт.

## 9. Известные искажения

- Корпус — синтетический (см. `scripts/bench/sample_docs/`); реальный клиент
  принесёт другую длину чанков и другой словарь. Цифры — нижняя граница.
- LLM-провайдер мерится с текущей конфигурацией; смена модели изменит и
  latency, и cost.
- Запуск делался в _(время суток)_; пиковая нагрузка от внешних клиентов
  была _(минимальная / умеренная / высокая)_.
