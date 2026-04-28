# Architecture Review Notes — 2026-04-27

Статус: рабочая заметка перед следующим заходом. Не ADR и не план реализации.

## Актуализация 2026-04-28

После ночных правок Sonnet/Opus часть старого риска закрыта или перешла в другой статус.

Закрыто / стало лучше:

- CSS/PostCSS/Next production path был стабилизирован отдельным деплоем.
- Публичный клиентский путь появился в минимальном виде: signup/login, API keys, публичный `/docs`, playground и `POST /api/v1/rag/query`.
- UI больше не является полностью открытым: основные приватные страницы закрыты middleware/auth gate, публичными остаются маркетинг/доки/правовые страницы.
- CI теперь содержит pytest job с Postgres/pgvector service, web lint/typecheck и Helm lint. Старый пункт "pytest не в CI gate" закрыт по коду.
- Ollama добавлен как embedder/runtime path; Cohere остаётся в реестре, но больше не должен считаться обязательной опорой продукта.
- Pricing UI и тарифные уровни появились, но экономика ещё требует проверки замерами и связки с billing/subscription enforcement.
- ARQ/Redis worker path появился в зависимостях, Helm и worker deployment. Это не равно завершённому queue contract: orchestration, fairness, priorities и quota/backpressure ещё надо довести.
- P0 tenant isolation для datasets закрыт: org scope идёт из session/API key, web больше не использует `NEXT_PUBLIC_ORG_ID`, legacy org header выключен по умолчанию.

Открыто / частично:

- Subscription/billing код сейчас выглядит как незавершённый слой: нужны idempotency, корректный plan switch, атомарные quota checks и тесты на webhooks.
- Account/billing UX ещё смешивает старую wallet/top-up модель и новую subscription модель.
- Customer journey "загрузил RAG -> подключил свой продукт" есть через API key и docs, но нет SDK/n8n/готовых workflow-интеграций.
- Queue contract пока не реализован как продуктовый SLA: live query, ingest, experiment и maintenance не имеют явно разделённых pools/лимитов/метрик.
- Тарифы опубликованы как форма, но не доказаны load/economics benchmark'ами.

Новый backlog item:

- **n8n community node**: отдельная интеграция для пользователей n8n, чтобы подключаться к RAG Platform без кода. Минимум: credentials node для API key/base URL, query node для `rag/query`, upload/index node для документов, optional dataset/pipeline selectors и пример workflow.

Контекст: фронт на проде был найден в состоянии "голый HTML без CSS". В ходе фикса всплыли не только CSS/PostCSS проблемы, но и хрупкость текущего delivery loop. CD сейчас отдельно пилит Opus; эту заметку используем после его готовности как входной backlog.

## Что уже выглядит сильным

- Идея продукта понятная: RAG-лаборатория, где пользователь без кода собирает pipeline из chunker/embedder/retriever/reranker/generator и сравнивает варианты.
- Плагинная модель через `params_schema` выглядит правильным ядром: схема плагина может быть source of truth и для API-валидации, и для UI-форм.
- ADR-документы полезные: multi-tenancy, k8s-only, plugin architecture, fixed score описаны как продуктовые решения, а не просто "документация ради документации".
- API уже имеет неплохой тестовый слой: локально было 24 passed / 1 failed.
- Helm chart не игрушечный: есть web/api, CNPG, Redis, migrations job, optional Langfuse/Permify/LiteLLM/Ollama.
- UI стек простой и понятный: Next + tRPC + shadcn/ui, без тяжёлой самодельной frontend-архитектуры.

## Что не нравится / где хрупко

- Контракты между слоями расходятся. Пример: frontend/tRPC ожидает поля, которые FastAPI response model не всегда отдаёт.
- Web build сейчас не является gate: `ignoreDuringBuilds: true` и `ignoreBuildErrors: true` позволяют собирать красный TypeScript/ESLint.
- `pnpm --filter web typecheck` красный на dynamic route params.
- API тест реестра плагинов устарел относительно фактического registry: появились `cohere-embedder` и `ollama-embedder`, тест всё ещё ожидает старый набор.
- tRPC слой между Next и FastAPI сейчас выглядит как дополнительный адаптер без строгого contract source of truth. Ошибки типов размазываются между React, tRPC и FastAPI.
- Tenant isolation заявлен в ADR сильнее, чем реализован в коде: местами `organization_id` приходит из body/query/header, местами фильтруется в endpoints, а не на едином repository/service уровне.
- Web readiness/liveness смотрели на пользовательский `/`, из-за чего SSR-дефект блокировал rollout. Это должен чинить CD-контур, но архитектурный запах остаётся.
- Документация местами обгоняет реализацию: workers, Permify, Langfuse, RAGAS, async queue, experiment runner, billing/cost tracking описаны как направление, но не как завершённые capability.

## Уточнения Макса

- Cohere не взлетел. Целевой путь сейчас — Ollama, а работа по этому шагу была в процессе, когда всплыл нерабочий CSS и всё было сброшено в нуль-приоритет.
- UI на момент комментария был открыт: кто знает адрес, тот мог зайти и гонять что хочет. После ночных правок появился auth gate, но его ещё нужно проверить end-to-end и покрыть тестами.
- Тарифы начали оформляться публично, но не посчитаны до доказанной себестоимости и capacity model.
- Текущая инфраструктура уже стоит около $130/мес:
  - балансировщик;
  - одна manager-нода кластера;
  - одна worker-нода: 2 CPU / 8 GB RAM / 40 GB boot SSD;
  - 20 GB network SSD.
- Если расширить Kubernetes до отказоустойчивого варианта и добавить хотя бы минимальное количество нод за пределами пилота, ожидаемый cost floor может стать $300+/мес на "типа живом" железе, всё ещё без доказанной готовности к реальным нагрузкам.
- Точки входа и выхода клиентского пути были не зафиксированы:
  - что именно клиент загружает;
  - что считается "загрузил RAG";
  - как клиент потом шлёт свои запросы;
  - какой API/SDK/UI-flow является production entrypoint;
  - как клиент забирает результат и встраивает это в свой продукт.
- Сейчас они частично закрыты через `/docs`, API key и `rag/query`, но остаются открытыми SDK/workflow-интеграции, n8n node, production examples и explicit "how to embed into your product".

## Себестоимость и ёмкость

На текущий момент нельзя честно назначать тарифы, пока не измерены хотя бы базовые unit economics.

Нужно понять ёмкость конкретной архитектуры:

1. Ingest capacity:
   - сколько документов/MB можно загрузить за час;
   - сколько chunks получается на типовом корпусе;
   - сколько времени занимает chunking + embedding через Ollama;
   - как растёт storage и pgvector index.
2. Query capacity:
   - сколько одновременных пользовательских запросов выдерживает один worker/API/web комплект;
   - latency p50/p95/p99 для retrieve -> rerank/generate;
   - что становится bottleneck: CPU, RAM, Postgres, Ollama, сеть, диск.
3. Scorer/eval capacity:
   - сколько стоит прогнать один dataset по одному pipeline;
   - сколько комбинаций реально можно прогнать за ночь/час;
   - что происходит при нескольких клиентах, которые одновременно запускают эксперименты.
4. Tenant capacity:
   - сколько tenants можно держать на текущем железе;
   - какой лимит документов/chunks/query per tenant нужен, чтобы один клиент не съел кластер;
   - где нужен queue/backpressure.

Пока эти числа неизвестны, тарифы будут гаданием. Минимальная модель тарифа должна опираться на:

- фиксированный infra floor: $130/мес сейчас, вероятно $300+/мес при отказоустойчивом пилоте;
- переменную стоимость ingest;
- переменную стоимость query;
- переменную стоимость eval/scoring;
- лимиты по storage/chunks;
- запас на idle, retries, failed jobs и support.

Рабочая гипотеза Макса: текущий k8s floor может оказаться слишком дорогим для раннего пилота, если продукт ещё не доказал способность обслуживать несколько клиентов и не имеет понятной клиентской точки входа/выхода.

## Текущая продуктовая дыра

Сейчас уже есть больше, чем демо-ядро: "загрузить документы / собрать pipeline / получить API key / вызвать `rag/query`". Но customer journey ещё не замкнут до уровня "пользователь встроил RAG в свой рабочий процесс".

Минимальный путь клиента должен быть описан явно:

1. Клиент создаёт tenant/project.
2. Клиент загружает документы или подключает источник.
3. Система строит индекс/embeddings и показывает статус готовности.
4. Клиент получает endpoint/key/виджет/инструкцию, как задавать вопросы своему RAG.
5. Клиент видит ответы, источники, лимиты, стоимость и качество.
6. Клиент может обновлять корпус и понимать, что произошло с индексом.
7. Клиент может подключить RAG Platform к внешнему workflow без разработки, например через n8n community node.

Пока этот путь не закрыт, pipeline editor остаётся лабораторией, а не продуктовым входом.

## Первый порядок разбора после CD

1. Закрыть P0 tenant isolation: org scope только из authenticated session/API key, без client-provided `organization_id` как authority.
2. Зафиксировать целевой runtime path: Ollama-first, без Cohere как обязательного dependency.
3. Проверить auth gate end-to-end: UI закрыт, session cookie корректно пробрасывается из Next в FastAPI, `/auth/me` является source of truth.
4. Описать customer journey: upload -> index -> query endpoint -> answer/source -> limits/cost.
5. Свести API contracts:
   - FastAPI response models;
   - tRPC schemas;
   - UI expectations;
   - negative tests на mismatch.
6. Вернуть web typecheck/build в блокирующий режим.
7. Починить API plugin registry test под фактический Ollama-first набор.
8. Посчитать себестоимость одного ingest и одного query path:
   - CPU/RAM;
   - текущий infra floor $130/мес;
   - отказоустойчивый floor $300+/мес;
   - Ollama latency;
   - storage/vector growth;
   - возможная очередь;
   - лимиты на tenant.
9. Измерить ёмкость scorer/eval path до обсуждения публичных тарифов.
10. Добавить integration backlog: n8n community node, SDK/examples, готовые workflow recipes.
11. После этого уже возвращаться к фичам: experiments, eval-loop, leaderboard, billing/pricing.

## Рабочая гипотеза

Главный риск сейчас не в RAG-алгоритмах. Главный риск — незамкнутый продуктовый контур и нестрогие контракты между слоями.

Если после CD привести в порядок customer journey, auth/access, Ollama-first path и contract tests, текущую архитектуру можно продолжать. Переписывать всё с нуля не требуется.
