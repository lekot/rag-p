# Benchmark scripts (`scripts/bench/`)

Скрипты для замера unit-economics платформы на проде (`https://api.lekottt.ru`):
ingest TPS, query latency p50/p95/p99 и experiment throughput. Это runbook —
открывай его в день бенчмарк-сессии и иди по шагам сверху вниз.

> **Внимание.** Локальный прогон создаёт нагрузку на боевой кластер. Запускай
> только в согласованное окно. Не запускай на свежей миграции до прогрева.

## 0. Что мы измеряем и зачем

Бэкграунд — `docs/architecture-review-2026-04-27.md` секция «Себестоимость и ёмкость».
Тарифы выставлены, но не подтверждены замерами. Мы хотим получить:

| Метрика                       | Источник                           |
|-------------------------------|------------------------------------|
| Ingest: документов/MB/sec     | `locustfile_ingest.py` CSV         |
| Query latency p50/p95/p99     | `locustfile_query.py` CSV          |
| Experiment combos/min         | `locustfile_experiment.py` CSV     |
| CPU/RAM/IO во время нагрузки  | `snapshot_resources.sh` CSV        |
| Postgres connections/lag      | `snapshot_resources.sh` CSV        |

Финальный отчёт собирается по шаблону `docs/economics-benchmark-template.md`.

## 1. Prerequisites (локально)

Один раз:

```bash
python -m venv .bench-venv
source .bench-venv/bin/activate          # на Windows: .bench-venv/Scripts/activate
pip install -r scripts/bench/requirements.txt
```

Проверь, что есть SSH-доступ на прод-хост по алиасу `gemcraft-claude`:

```bash
ssh gemcraft-claude 'docker compose -f /opt/rag-p/deploy/compose/compose.prod.yml ps'
```

Если алиаса нет — добавь в `~/.ssh/config`:

```
Host gemcraft-claude
    HostName <ip>
    User <user>
    IdentityFile ~/.ssh/gemcraft-claude
```

## 2. Подготовить тестовый аккаунт на проде

`seed_dataset.py` создаёт benchmark-организацию, API key, dataset, заливает
корпус и генерирует golden Q&A. Запускается **один раз** перед сессией.

### 2.1. Активировать платный план

`/datasets/{id}/documents` и `/rag/query` требуют активной подписки. Варианты:

**Вариант A (быстрый, на ноч­ной сессии).** Временно отключить subscription
quota gate на API:

```bash
ssh gemcraft-claude
cd /opt/rag-p/deploy/compose
sudo sed -i 's/^RAGP_ENFORCE_SUBSCRIPTION_QUOTAS=.*/RAGP_ENFORCE_SUBSCRIPTION_QUOTAS=false/' .env
docker compose up -d api worker
```

После бенчмарка вернуть `=true` и перезапустить.

**Вариант B (правильный).** Активировать план через прямой SQL без YooKassa:

```bash
ssh gemcraft-claude
docker exec -it postgres psql -U ragp -d ragp <<'SQL'
INSERT INTO org_subscriptions (org_id, plan_id, status, period_start, period_end, q_used, storage_bytes_used)
SELECT '<ORG_ID_FROM_SEED>', id, 'active', now(), now() + interval '30 days', 0, 0
FROM plans WHERE name = 'Pro';
SQL
```

Подставь `<ORG_ID_FROM_SEED>` после первого запуска seed-скрипта (см. ниже —
seed напечатает org_id, но НЕ сможет залить документы пока план не активен;
запусти seed в два этапа: signup → активировать план → re-run с
`RAGP_BENCH_REUSE_EMAIL=1`).

### 2.2. Запустить seed

```bash
export RAGP_BENCH_BASE_URL=https://api.lekottt.ru
export RAGP_BENCH_EMAIL="bench+$(date +%s)@lekottt.ru"
export RAGP_BENCH_PASSWORD="<strong>"
export RAGP_BENCH_ORG_NAME="BenchOrg"

python scripts/bench/seed_dataset.py
```

Скрипт распечатает env-блок и запишет его в `scripts/bench/.bench-env`.
Если на этапе upload получишь HTTP 402 — иди в шаг 2.1, активируй план,
повтори с `RAGP_BENCH_REUSE_EMAIL=1`.

Подгрузи env в локальный shell:

```bash
set -a
. scripts/bench/.bench-env
set +a
```

Готово к замерам.

## 3. Сценарии

Все три locustfile принимают `--users`/`--spawn-rate`/`--run-time`/`--csv`
от Locust как обычно. Запускай **по одному за раз** — не смешивай нагрузку.

### 3.1. Query latency

```bash
mkdir -p results

# Прогрев 30 сек, потом 1/5/10/50 одновременных пользователей по 5 минут.
for U in 1 5 10 50; do
  locust -f scripts/bench/locustfile_query.py \
         --users $U --spawn-rate 1 --run-time 5m \
         --host "$RAGP_BENCH_BASE_URL" \
         --csv "results/query-c$U" --headless
done
```

В каждой папке появятся `results/query-cN_stats.csv` etc.

### 3.2. Ingest TPS

`locustfile_ingest.py` использует session cookie, не API key, — endpoint требует session.

```bash
locust -f scripts/bench/locustfile_ingest.py \
       --users 5 --spawn-rate 1 --run-time 5m \
       --host "$RAGP_BENCH_BASE_URL" \
       --csv results/ingest-u5 --headless
```

Замерь несколько concurrency: 1, 3, 5, 10. На малом железе уже на 5 будет
видна saturation embedder'а.

### 3.3. Experiment throughput

```bash
# 1 user, small grid (1 combo) — измеряем latency одного combo.
RAGP_BENCH_GRID_SIZE=small \
  locust -f scripts/bench/locustfile_experiment.py \
         --users 1 --spawn-rate 1 --run-time 30m \
         --host "$RAGP_BENCH_BASE_URL" \
         --csv results/exp-small-u1 --headless

# 3 users, medium grid (4 combos) — параллельность.
RAGP_BENCH_GRID_SIZE=medium \
  locust -f scripts/bench/locustfile_experiment.py \
         --users 3 --spawn-rate 1 --run-time 1h \
         --host "$RAGP_BENCH_BASE_URL" \
         --csv results/exp-medium-u3 --headless
```

Locust на experiment'ах меряет полное время прогона (создание + polling до
terminal status). RPS на endpoint'ах `EXPERIMENT/...-combo` ≈ combos/sec.

### 3.4. Resource snapshot (parallel)

В **отдельном** tmux-pane, до того как стартанул locust:

```bash
RAGP_BENCH_HOST=gemcraft-claude \
RAGP_BENCH_INTERVAL=10 \
RAGP_BENCH_DURATION=1800 \
RAGP_BENCH_OUT=results/resources-query-c50 \
bash scripts/bench/snapshot_resources.sh
```

`DURATION` ≥ длительности locust-прогона + 60 сек на остывание.
В `results/resources-*` ляжет `docker_stats.csv` и `pg_stat_activity.csv`.

## 4. Анализ результатов

```bash
python scripts/bench/analyze_results.py results/query-c*_stats.csv \
  > results/query-summary.md

python scripts/bench/analyze_results.py results/ingest-*_stats.csv \
  > results/ingest-summary.md

python scripts/bench/analyze_results.py results/exp-*_stats.csv \
  > results/exp-summary.md
```

Получишь markdown-таблицы с p50/p95/p99 и error rate. Перенеси цифры в
шаблон отчёта `docs/economics-benchmark-template.md` (заполняй сразу
во время сессии — потом сложно восстановить контекст).

## 5. Интерпретация (cheatsheet)

| Симптом                                | Гипотеза                                                                    |
|----------------------------------------|------------------------------------------------------------------------------|
| `query` p99 → 5+ сек                   | Generator (LLM) — узкое место. Глянь `docker stats` API/network egress.      |
| `query` errors 429                     | Дошли до rate-limit плана. Подними план или уменьши `--users`.              |
| `query` errors 402                     | Закончился баланс при overage. Активируй план без overage или пополни.       |
| `ingest` p99 пропорционально размеру   | Embedder доминирует. CPU api-контейнера ~100% во время прогона.              |
| `ingest` стабильное p99, но низкий RPS | Connection pool / embedder batch — рост concurrency не помогает.            |
| `experiment` time линейно от combos    | Scorer работает однопоточно. Параллелим на уровне combo.                     |
| `pg_stat_activity` много `idle in tx`  | Утечка транзакций — баг в коде, не в нагрузке.                              |
| `docker stats` mem → swap              | Embedding model не помещается в RAM. Меньше batch_size или больший инстанс. |

## 6. После замеров — обязательные шаги

1. **Удалить bench-аккаунт.** Через UI: account → delete organisation.
   Или SQL по `org_id`.
2. **Вернуть `RAGP_ENFORCE_SUBSCRIPTION_QUOTAS=true`** если меняли.
3. **Заархивировать** папку `results/` в `.tmp-bench-<date>/` и положить в
   private storage. CSV содержат имена endpoint'ов и могут попасть в публичную
   историю если коммитить — не коммитить!
4. **Заполнить отчёт** `docs/economics-benchmark-template.md`. Без отчёта
   замер бесполезен — через неделю никто не вспомнит детали.

## 7. Структура папки

```
scripts/bench/
├── README.md                       — этот файл
├── requirements.txt                — locust>=2.20, httpx>=0.27
├── _common.py                      — env helpers, query mix, corpus loader
├── locustfile_ingest.py            — IngestUser (session cookie)
├── locustfile_query.py             — QueryUser (Bearer API key)
├── locustfile_experiment.py        — ExperimentUser (session cookie)
├── seed_dataset.py                 — одноразовая подготовка bench-org
├── snapshot_resources.sh           — параллельный сборщик docker/pg метрик
├── analyze_results.py              — стdlib-only сводка locust CSV
└── sample_docs/                    — корпус ~900 KB, .md + .txt
```

## 8. Известные ограничения

- `seed_dataset.py` ожидает, что endpoint `POST /datasets/{id}/golden` уже
  работает и возвращает 200/201. Если генерация Golden Q&A временно сломана —
  скрипт пишет WARN и продолжает; experiment-сценарий тогда работать не будет
  (нет ground-truth для метрик). Запусти experiment руками после ручной
  загрузки golden set.
- `locustfile_experiment.py` интерпретирует `EXPERIMENT/...-combo` события как
  per-combo throughput. Это синтетика: реально все combos конкретного
  experiment'а закончились одновременно. Цифра валидна как «среднее время на
  combo», не как реальный hit-rate скорера.
- `snapshot_resources.sh` опрашивает прод по SSH. Если SSH-сессия упадёт
  посреди замера, CSV-файлы будут неполные. Запускай в `tmux` и проверь, что
  сессия жива (поллинг каждые 10 сек — новые строки в `docker_stats.csv`).
