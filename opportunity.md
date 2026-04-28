# RAG-Platform — opportunity

> Версия: 0.1, 2026-04-27. Author: Макс Lekot.
> North Star документ. На каждом decision-gate возвращаемся сюда и проверяем — мы всё ещё про это или съехали.

## Problem

Сегодняшняя зрелая RAG-команда собирает свой пайплайн вручную из десятка инструментов:
**R2R** (или собственный код) для движка, **Langfuse** для observability, **RAGAS** для eval, **Promptfoo/Vellum** для prompt mgmt, **Postgres RLS / Cerbos / OpenFGA / Permify** для доступов, и склейка из своего FastAPI/Node-кода поверх. Каждый эксперимент — конфигурируется через YAML или код. Аналитик-без-кода сравнить две стратегии чанкования или два reranker'а не может — нужен инженер. Каждое улучшение качества стоит инженерочаса; «крутить руками» опции — невозможно.

Платформа RAG как **лаборатория с UI** для аналитика — рыночная дыра.

## Existing landscape

| Сегмент | Кто | Что закрывают | Что не закрывают |
|---|---|---|---|
| RAG-as-a-Service (SaaS) | Vectara, LlamaCloud, Pinecone Assistants, OpenAI File Search | Готовый «один правильный путь», UI чёрного ящика, лок vendor-in | Возможность подменить компонент; self-host; сравнение стратегий |
| Open-source RAG-движок | R2R, Onyx, Verba, Haystack, AnythingLLM | Сам пайплайн, REST API, базовый UI просмотра | Eval-loop в UI; A/B стратегий; comp-конфиг прав; prompt mgmt |
| Eval / observability | Langfuse, LangSmith, Promptfoo, RAGAS, Phoenix | Tracing, метрики, datasets | Только observability — не движок; не оркестрирует пайплайн |
| Authz | Permify, OpenFGA, Cerbos, Postgres RLS | Fine-grained authz | Не интегрировано с RAG-компонентами из коробки |
| Enterprise search | Glean, Hebbia, Elastic + ELSER | Source connectors + поиск + LLM-обвязка | Не платформа, а вертикаль; высокий чек, длинный sales |

Vectara — **продукт-RAG**, не платформа. Лок vendor-in, нельзя подменить компонент. Не закрывает дыру.

## The gap

**Лаборатория, в которой:**
- Параллельно держатся **3 чанкера, 5 embedding-моделей, 4 reranker'а, 3 LLM** — и в UI аналитик их **комбинирует и сравнивает**.
- Каждый эксперимент **автоматически прогоняется** через тестовый QA-сет, метрики side-by-side.
- **RLS / multi-tenant / RBAC** — встроены, не дописываются сбоку.
- **Prompt management** + **observability** + **eval** в **одной поверхности**.

Сейчас это собирается командой за 2-3 квартала. Цель — дать **из коробки**.

## Solution

**RAG-Platform** — open-core, self-hostable. **Pipeline-as-a-Service** для документов: на входе корпус, на выходе — лучшая связка с **fixed score** каждой альтернативной опции и трассируемым обоснованием. Один Helm chart разворачивается как self-host, managed SaaS или PaaS — отличается только конфигом тенантов.

**Core:**
- Plugin-API: `Chunker / Embedder / Retriever / Reranker / Generator` с JSON Schema params.
- Pipeline runner: ordered list of plugin instances + конфиг в Postgres с версионированием.
- Experiment store: каждый run сохраняет config_snapshot + dataset_id + metrics + traces.
- Eval-loop: RAGAS встроен, generate_testset из docs, side-by-side compare.
- Observability: Langfuse рядом, traces всех запросов.
- Authz: Permify, fine-grained per organization / pipeline / dataset.

**UI для аналитика (key differentiator):**
- Pipeline editor (form-based, generated from `params_schema`).
- Run dashboard, side-by-side compare, metric drift over time.
- Query trace: retrieved chunks, scores, rerank deltas, generated answer, eval breakdown.
- Dataset manager (upload, generate, annotate).

**Ingest:**
- Готовые парсеры (Unstructured.io / LlamaParse как опция).
- Cron / webhook reindex.
- Source connectors v2 (Slack, Confluence, GDrive — позже).

## Differentiators

1. **Pipeline-as-a-Service с fixed score.** Аналитик не выбирает «один из десяти движков» — система прогоняет **все валидные комбинации** на его корпусе и возвращает каждую опцию со скором. Vectara и R2R дают «один правильный путь».
2. **Лаборатория, а не движок.** Параллельно держатся **n чанкеров / m embedder'ов / k reranker'ов / l LLM** — UI комбинирует и сравнивает.
3. **Open-core, self-hostable.** Vectara/LlamaCloud — закрытая SaaS. Мы — AGPL core, paid managed как опция. Один Helm chart = SaaS / PaaS / OnPrem.
4. **Eval как first-class citizen.** Не «есть API, прикрути сбоку». Eval — встроен в каждый run, всегда.
5. **Multi-tenant из коробки.** Большинство open-source проектов — single-tenant. Мы — изначально multi-tenant.
6. **Production-grade infra.** k8s-native, не «работает на моём macbook». Helm chart, observability-stack включён.

## Success metrics for MVP (8 weeks)

**Hard goals:**
- 10 человек скачали open-source self-host и **запустили** на своём корпусе. Метрика: github stars + analytics на demo сайте.
- 5 человек сделали **A/B сравнение** двух пайплайнов через UI и **получили улучшение метрики на 10%+**.
- demo-домен на rag-p.maxlekot.ru работает 24/7 с реальным корпусом (i-ching ИЛИ 1С BZ).

**Soft goals:**
- Один лонгрид на /blog/ (или dev.to / Habr) с 1000+ просмотрами.
- Twitter/Telegram thread за 8 недель — публичный buildjournal.
- Один PR от внешнего контрибьютора (любой, хотя бы typo) — сигнал, что репо живой.

**Не-goals (выкидываем сразу):**
- Cloud SaaS с биллингом. Только self-host MVP.
- Source connectors к Slack/Confluence. Этап v2.
- Fine-tune embedding моделей. v3.
- GraphRAG, agentic RAG. v3.
- Mobile app. Никогда.
- Свой UI-фреймворк / свой LLM-клиент / свой embedding model. **Никогда**.

## Tech stack

| Слой | Выбор | Почему |
|---|---|---|
| Backend | Python + FastAPI | Все RAG-библиотеки питоновские |
| Frontend | Next.js + TypeScript + shadcn/ui + tRPC | Стандарт; быстро с агентами |
| DB | Postgres + pgvector + tsvector | Один сервер закрывает векторы и BM25 |
| Queue / jobs | Hatchet или Celery + Redis | Hatchet используется R2R; Celery если хотим проще |
| Authz | Permify | Чище API чем OpenFGA, моложе но активный |
| Auth | Clerk на старте | Managed, заменим когда подрастём |
| Tracing | Langfuse (self-host) | Встроим в compose рядом с приложением |
| LLM-обёртки | LiteLLM | Унифицированный API под 100+ моделей |
| Парсинг docs | Unstructured.io + LlamaParse как опция | Покрывают сложные случаи |
| Eval | RAGAS | Стандарт |
| Деплой | k8s (k3s в проде, kind/minikube локально) | HA, multi-node, production-ready |
| GitOps | ArgoCD или Flux | Декларативный деплой |
| Secrets | external-secrets-operator + Bitwarden/Vault | Не хардкодить в манифестах |
| Observability | Prometheus + Grafana + Loki | Стандарт |
| Лицензия | AGPL-3.0 для core, MIT для clients/SDK | Защита от облачных перепродавцов |

## Open questions

1. **Open-core vs full-AGPL?** Или модель «core open, enterprise edition closed» (как GitLab)?
2. **Хостовать ли cloud-версию вообще?** На MVP — нет. Дальше — может быть.
3. **Cohere rerank API стоит денег.** Дать ли локальный reranker как default? Тестировать качество.
4. **Postgres pgvector vs выделенный vector DB (Qdrant)?** Pgvector проще на старте; на масштабе уступает.
5. **На каком корпусе делать demo?** И-цзин (зрелищно, но узко) или 1С BZ (полезно, но скучно для не-1С-аудитории)?
6. **Нужна ли поддержка не-Python embedding models?** Для русского ru-tiny от cointegrated — ниша.

## Risks

| Риск | Вероятность | Тяжесть | Митигация |
|---|---|---|---|
| Конкуренты приходят первыми | High | High | Скорость; ниша на русскоязычный рынок; open-source distribution |
| 6 детей + соло-фаундер = burn out | High | High | Гибрид: работа в параллели первые 6 мес, MVP по вечерам |
| Distribution не заработает | High | High | Контент-первый подход: лонгриды, threads, OSS со старта |
| Нет PMF | Medium | High | Decision-gate в неделю 4: если не нравится, pivot |
| k8s overengineered для MVP | Medium | Medium | Можно начать с Coolify / Dokku; k8s через 4-5 неделю когда core работает |
| Cohere/OpenAI цены съедят | Low | Medium | Cost-tracking + локальные модели как fallback |

## Decision gates

- **End of week 4:** Core (plugin-API + hybrid + rerank + eval-loop) работает? UX обещает? Если нет — pivot или drop.
- **End of week 8:** Public demo живой? 10 self-host инсталляций есть? Если нет — review distribution-стратегии.
- **+3 месяца после MVP:** Есть paying interest или 0 ₽ выручки? Если выручки нет — задаваться вопросом «это hobby или business».
