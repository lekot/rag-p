# Night run summary 2026-04-27/28

## Доставлено в прод

- `dbde535` — token usage passthrough in pipeline path + Runs UI: поле `usage` (prompt/completion tokens) доходит до `/rag/query` и до Ask UI через pipeline-path; страница Runs показывает историю вызовов.
- `f766698` — public RAG query endpoint + /docs UI page: публичный `POST /api/v1/rag/query` с Bearer-авторизацией; страница `/docs` с полным API reference и curl-примером.
- `23c33b3` — auth UI: login, signup, account, управление API-ключами; сессионные cookie; форма создания/отзыва ключей.
- `f0885e5` — real Dashboard с живыми счётчиками (datasets, experiments, pipelines, runs) и workflow-подсказкой.
- `ecb6ed3` — golden Q&A generation via DeepSeek + real eval metrics: `POST /datasets/{id}/golden` генерирует вопросы по чанкам; experiment runner использует `retrieval_hit` + `answer_similarity` когда golden items есть.
- `ebe86d3` — full dataset→experiment→pipeline→ask workflow (Phase 1–4): загрузка файлов, recursive-character chunker, pgvector, experiment grid, leaderboard, promote to pipeline.
- `5f0e61b` — PDF и DOCX support в upload.
- `3c77eff` — anti-hallucination system prompt с citations в generator.
- `5cfd207` — поддержка текстовых форматов: json, csv, yaml, xml, html, md.
- `63fc5fb` — full RAG-cycle /ask endpoint и Ask UI секция.
- `f766698`+сегодня — `/docs` Try-it-now playground: интерактивная форма прямо в браузере для проверки API-ключа и датасета; prefill dataset_id из URL-параметра.

## Архитектура (текущее состояние)

```mermaid
flowchart TD
    A[/signup/ email+password+org] -->|session cookie| B[Dashboard]

    B -->|POST /api/v1/keys| K[API Key rgp_xxx\nsha256 в БД]

    B --> D[Datasets]
    D -->|upload .txt .md .json .csv\n.yaml .xml .html .pdf .docx| ING[Ingest pipeline]
    ING --> CHK[recursive-character chunker]
    CHK --> EMB[ollama-embedder bge-m3\n1024-dim]
    EMB --> PG[(pgvector)]

    D -->|Generate Golden Q&A| GQ[DeepSeek generates\nquestions per chunk]
    GQ --> GT[(golden_items в БД)]

    B --> EXP[Experiments]
    EXP -->|plugin_grid cartesian product| RUN[experiment runner\nself-test или golden_metrics]
    RUN --> GT
    RUN --> LEAD[Leaderboard]
    LEAD -->|promote_to_pipeline| PIP[Pipeline\nпривязан к dataset]

    PQ[Ask UI / POST /rag/query\nBearer rgp_xxx] --> EMB2[embedder]
    EMB2 --> RET[pgvector-hybrid retriever]
    RET --> GEN[litellm-generator\ndeepseek-v4-flash]
    GEN --> ANS[answer + citations + usage + trace]
    ANS --> RUNS[(Runs в БД)]
```

## Открытые блокеры

см. [docs/blockers.md](./blockers.md)

Актуальные (нерешённые / частичные):
- **ARQ queue contract** — ARQ/Redis worker path уже появился, но experiment/live/ingest/score/maintenance SLA, fairness и idempotency ещё не сведены в контракт реализации.
- **Subscription enforcement** — pricing/subscription слой появился, но требует ревью атомарности quota, YooKassa idempotency, plan switch и тестов.
- **n8n community node** — нужен как zero-code вход для пользователей n8n поверх `POST /api/v1/rag/query` и будущих upload/index/status actions.

Закрыто после старой записи:
- **Pytest в CI gate** — `.github/workflows/ci.yml` теперь содержит pytest job с Postgres/pgvector service.
- **P0 tenant isolation для datasets** — `NEXT_PUBLIC_ORG_ID` удалён из web authority, API datasets/documents/search/ask/golden/generate scoped через session/API key, добавлен negative cross-tenant test.

## Что НЕ сделано (бэклог)

- Celery/ARQ для experiment runner background jobs
- Vault + ESO для secrets management (deferred per #40)
- LLM-as-judge metric (исключено по решению Макса)
- Settings page (members, invite by email, change password, delete org)
- Cohere reranker (cohere blocked from RU IP — оставлен в реестре, не используется)
- Background usage tracking + billing dashboard
- Старый бинарный .doc parser (textract/antiword)
- n8n community node: credentials, query action, upload/index action, status polling, examples

## Workflow для нового пользователя

1. `/signup` → email + пароль + имя организации
2. Dashboard → "View Datasets" → "Upload / Create"
3. Загружает `.txt` / `.pdf` / etc — авто-чанкование + эмбеддинг через bge-m3
4. `Datasets/{id}` → Search или Ask на месте, видит ответ + citations
5. Опционально: "Generate Golden Q&A" — DeepSeek генерит вопросы по чанкам
6. `Experiments/new` — выбор датасета и грид плагинов → "Run experiment" → leaderboard
7. На странице experiment'а — "Promote winner" → создаёт Pipeline, привязанный к датасету
8. `Account` → "New API Key" → копирует `rgp_...` один раз
9. `POST /api/v1/rag/query` с Bearer → программный доступ
10. `/docs` → "Try it now" → тест прямо в браузере без curl
