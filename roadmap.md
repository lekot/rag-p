# RAG-Platform — 8-week roadmap (v0.2)

> Обновлено после ревью Макса: неделя 1 ужата до вечера, освободившееся время + дополнительный спринт уходит на **k8s baseline**, который изначально был забыт. На пилоте — k3s на 2 нодах Hetzner или minikube для локальной разработки.

## Pre-week 0 — definition of done

Перед стартом фиксируем **success metric для MVP**:
- 10 self-host инсталляций.
- 5 A/B сравнений с улучшением 10%+ через UI.
- Demo на `rag-p.maxlekot.ru` 24/7.

Если через 8 недель этого нет — review.

---

## Week 1 — Scaffolding + Kubernetes baseline

**День 1 (вечер):** Скаффолд проекта.
- Repo + Conventional Commits + GitHub Actions skeleton.
- `apps/api` (FastAPI) + `apps/web` (Next.js + tRPC + shadcn/ui).
- `docker-compose.dev.yml` для локальной разработки: postgres+pgvector, redis, langfuse, permify.
- Spike: trivial RAG end-to-end через LlamaIndex на тестовом корпусе. Цель — увидеть `200 OK` и сгенерированный ответ.

**Дни 2–4:** Kubernetes baseline.
- **Локально:** kind или k3d (minikube тяжелее) — кластер на 3 ноды на твоём ноутбуке.
- **Helm-чарты** для всех компонентов: api, web, postgres (через CloudNativePG operator), redis, langfuse, permify.
- **Ingress:** Traefik (k3s default) или nginx-ingress.
- **Cert-manager** для TLS.
- **External-secrets-operator** + локальный Vault или Bitwarden для секретов.
- **GitOps:** ArgoCD или Flux. Главная ветка → автодеплой в staging-namespace.

**День 5:** Staging-кластер на Hetzner.
- 2 ноды по €5/mes (CX22) с k3s.
- Cloudflare DNS на rag-p-staging.maxlekot.ru.
- ArgoCD pull from GitHub → деплой на push в main.
- HA проверка: `kubectl drain node-1` — должен переехать на node-2.

**Не делаем на этой неделе:** plugin-архитектуру, UI, eval. Только инфра + один тривиальный pipeline для проверки что k8s pod'ы видят друг друга.

---

## Week 2 — Plugin architecture

- Интерфейсы: `Chunker`, `Embedder`, `Retriever`, `Reranker`, `Generator`. Каждый — abstract class с `params_schema` (JSON Schema), `cost_estimate()`, `health_check()`.
- 2-3 чанкера: RecursiveCharacter, Semantic, MarkdownAware (все обёртки над LangChain/LlamaIndex).
- 2-3 embedder: OpenAI, Cohere, BGE-M3 (локально через sentence-transformers).
- Pipeline = ordered list of plugin instances. Конфиг в Postgres с версионированием (`pipelines`, `pipeline_versions`).
- API: `POST /pipelines`, `POST /pipelines/:id/runs` (синхронный для старта).
- Queue: Hatchet или Celery — пока не критично, можно sync.

---

## Week 3 — Hybrid search + rerank

- BM25 через Postgres `tsvector` + `ts_rank`.
- Dense через pgvector cosine similarity.
- **RRF** слияние: `score = Σ 1/(k + rank_i)`, k=60 по умолчанию.
- Rerank: Cohere rerank-v3 (API) + BGE-reranker-v2-m3 (локально, GPU желателен).
- Pipeline node может включать/выключать rerank.

---

## Week 4 — Eval-loop ⭐ key differentiator

- `datasets` table в Postgres (QA-pairs с `golden_answer`, `golden_contexts`).
- `dataset_generator` через RAGAS `generate_testset` от загруженных docs.
- `runs` table: `pipeline_version_id`, `dataset_id`, `metrics_json`, `traces_json`.
- Метрики: faithfulness, answer_relevance, context_precision, context_recall.
- API: `POST /datasets`, `POST /datasets/:id/generate`, `POST /pipelines/:id/runs`.
- Side-by-side compare двух runs (по runId + runId).

### 🛑 Decision gate (конец недели 4)

Опросник:
- [ ] Core работает — pipeline + hybrid + rerank + eval?
- [ ] UX обещает? Готов показать первому потенциальному пользователю?
- [ ] Видишь ли ты «как мы туда придём» по дистрибуции?

Если 3 «да» — продолжаем. Если 2 — pivot одного компонента. Если 1 или 0 — стоп, обсудить.

---

## Week 5 — UI for analyst

- Dashboard: pipelines, runs, charts (Recharts).
- Pipeline editor: form-based выбор плагинов через `params_schema` → React JSON Schema Form.
- Run detail view: query → retrieved chunks с scores → rerank deltas → generated answer → eval breakdown.
- Trace per query — linkout в Langfuse.

---

## Week 6 — Multi-tenant + RLS

- **Permify** в кластере. Tenant model: `organization → user → role → permissions`.
- Tenant isolation: `documents`, `pipelines`, `datasets`, `runs` привязаны к `organization_id`.
- Filters на retrieve уровне: WHERE organization_id = $current_org.
- Roles: viewer (run only), editor (configure + run), admin (manage members).
- Integration test: tenant A не видит данные tenant B (negative test обязателен).

---

## Week 7 — Ingest + production polish

- Ingest API: upload PDF/docx/md/html → парсинг через Unstructured.io в Hatchet/Celery → chunks в БД.
- LlamaParse как опция для сложных PDF (env-флаг).
- Re-index на изменение docs (webhook или cron).
- Cost tracking per organization (LiteLLM даёт usage из коробки).
- Quotas (запросы/день, токены/месяц).
- Rate limits (per-org).
- Logging structured (loguru или structlog), Loki в кластере, Grafana дашборды.
- Error handling: dead-letter queue для упавших jobs.

---

## Week 8 — Demo + deploy + landing

- Demo-домен на твоём корпусе (выбор на decision-gate: i-ching или 1С BZ).
- **Helm chart** в репо для self-host: `helm install rag-p ./charts/rag-p`.
- **Docker-compose** альтернатива для тех, кто не в k8s.
- Cloud demo на `rag-p.maxlekot.ru` с тестовым tenant (read-only для анонимов).
- Landing page: один экран на shadcn — pitch + видео-демо + GitHub link + waitlist email.
- Open-source repo public, README с quickstart, лицензия (AGPL-3.0 для core).
- Анонс: лонгрид на /blog/, twitter thread, post в DevsChat / r/MachineLearning / Habr.

---

## Buffer / known risks

| Риск | Buffer |
|---|---|
| Eval-loop капризничает на real-world | +5 дней |
| UI dynamic forms ломаются на edge cases | +3 дня |
| Multi-tenant perf на pgvector | +5 дней или known limit для v1 |
| k8s upgrade / config issues | +3 дня |

Итого: **8 недель MVP + 0-2 недели buffer = 9-10 недель до публичного demo.**

---

## Infra cost estimate (pilot)

| Компонент | Где | Стоимость |
|---|---|---|
| Staging k3s, 2 ноды | Hetzner CX22 × 2 | €10-12/мес |
| Production k3s, 3 ноды | Hetzner CX32 × 3 | €25-30/мес |
| Cohere rerank API | По usage | $0-50/мес для пилота |
| OpenAI embeddings + LLM | По usage | $20-100/мес для демо |
| Domain + сертификаты | Selectel + Let's Encrypt | €0 (уже есть) |
| LlamaParse (если нужен) | Managed | $0-25/мес |
| **Итого MVP** | | **~€60-200/мес** |

Бутстрап-режим. Терпимо.

---

## What we're NOT doing

- Свои чанкеры / embedding / reranker / LLM. **Никогда.**
- Cloud SaaS с биллингом на MVP.
- Source connectors (Slack, Confluence). v2.
- Fine-tuning. v3.
- GraphRAG, agentic. v3.
- Mobile.
- Custom auth (Clerk на старте).
