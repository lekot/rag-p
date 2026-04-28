# Observability — метрики, логи, дашборды

## Архитектура стека

| Компонент | Роль |
|---|---|
| `prometheus-fastapi-instrumentator` | Метрики HTTP FastAPI (`/metrics`) |
| `prometheus_client` (в worker) | Метрики ARQ-воркера (`:<9090>/metrics`) |
| `ServiceMonitor` (api + worker) | Автообнаружение Prometheus через CRD |
| `kube-prometheus-stack` | Prometheus + Grafana (установлен на кластере отдельно) |
| `loki-stack` | Loki + Promtail — агрегация логов подов |
| ConfigMap `rag-p-dashboards` | Дашборды Grafana, монтируются через sidecar |

## Включение в staging

В `values.staging.yaml` уже включено:
```yaml
observability:
  enabled: true
  loki:
    enabled: true
```

`kube-prometheus-stack` должен быть установлен на кластере **до** деплоя чарта — ServiceMonitor'ы требуют CRD `monitoring.coreos.com/v1`.

## Доступ к Grafana

### Через port-forward (быстро, без ingress)

```bash
kubectl -n monitoring port-forward svc/prometheus-grafana 3000:80
```
Grafana: http://localhost:3000 (логин `admin`, пароль — из секрета `prometheus-grafana`).

```bash
kubectl -n monitoring get secret prometheus-grafana \
  -o jsonpath="{.data.admin-password}" | base64 -d
```

### Через ingress (если настроен в kube-prometheus-stack)

Зависит от конфигурации кластера — смотри `kube-prometheus-stack.grafana.ingress` в values.

## Метрики API

Endpoint: `GET /metrics` (без авторизации, только агрегатные счётчики).

Ключевые метрики от `prometheus-fastapi-instrumentator`:

| Метрика | Тип | Описание |
|---|---|---|
| `http_requests_total` | Counter | Запросы по method/handler/status |
| `http_request_duration_seconds` | Histogram | Латентность (buckets: 0.1...10s) |
| `http_requests_in_progress` | Gauge | Текущие in-flight запросы |

## Метрики Worker

Endpoint: `http://<pod>:9090/metrics`

| Метрика | Тип | Описание |
|---|---|---|
| `ragp_worker_jobs_total{status="completed\|failed"}` | Counter | Задачи по статусу |
| `ragp_worker_job_duration_seconds` | Histogram | Длительность задачи |

## Дашборды Grafana

ConfigMap `rag-p-dashboards` монтируется автоматически через sidecar (label `grafana_dashboard: "1"`).

### RAG Platform — API (`ragp-api-v1`)

- **Request Rate (QPS)** — запросы/сек по endpoint
- **Error Rate (5xx)** — частота серверных ошибок
- **Latency p50/p95/p99** — перцентили латентности по endpoint
- **In-Flight Requests** — активные соединения
- **Top Endpoints** — топ-10 endpoint по трафику за 1h

### RAG Platform — Worker (`ragp-worker-v1`)

- **Jobs per Second** — пропускная способность воркера
- **Success/Failure Ratio** — доля успешных задач
- **Job Duration p50/p95** — перцентили длительности
- **Redis Queue Length** — глубина очереди `arq:queue:default`
- **Total / Failed Jobs (1h)** — итоговые счётчики

## Логи через Loki

Promtail (в составе `loki-stack`) автоматически собирает логи всех подов namespace `rag-p`.

Пример запроса в Grafana Explore:
```logql
{namespace="rag-p", app_kubernetes_io_component="api"} |= "ERROR"
```

Доступ к Loki:
```bash
kubectl -n rag-p port-forward svc/rag-p-loki 3100:3100
# затем в Grafana: Add datasource → Loki → http://localhost:3100
```

## Алерты

Алерты запланированы на следующую итерацию. Первоочередные:
- p95 латентность API > 2s за 5 минут
- Error rate > 5% за 5 минут
- Worker failed jobs > 0 за 15 минут
- Redis queue depth > 50 задач

## Оператор — чеклист при первом включении

1. Убедиться, что `kube-prometheus-stack` установлен в кластер:
   ```bash
   kubectl get crd servicemonitors.monitoring.coreos.com
   ```
2. Установить/обновить чарт с `observability.enabled=true` (staging values уже включают это)
3. Проверить что ServiceMonitor'ы появились:
   ```bash
   kubectl -n rag-p get servicemonitor
   ```
4. Проверить что Prometheus видит targets:
   ```bash
   kubectl -n monitoring port-forward svc/prometheus-operated 9090:9090
   # http://localhost:9090/targets → ищи ragp-api, ragp-worker
   ```
5. Открыть Grafana → папка "RAG Platform" → проверить дашборды
