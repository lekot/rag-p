# Пользовательский путь RAG-Platform

Эта инструкция описывает основной путь пользователя без кода: создать dataset, загрузить документы, сгенерировать golden Q&A, запустить experiment, промотировать победителя в pipeline, задавать вопросы через pipeline и смотреть ответы в runs.

## 0. Перед стартом

Для операций, которые тратят вычислительную квоту, нужен активный план: создание dataset, загрузка документов, генерация golden Q&A, запуск experiments и pipeline runs.

Если UI или API возвращает `402 Payment Required`, откройте `Pricing` или `Account -> Billing` и активируйте план либо пополните квоту.

## 1. Создать dataset и загрузить документы

1. Откройте `Datasets`.
2. Нажмите `Upload / Create`.
3. Введите имя dataset.
4. Выберите файл и нажмите `Upload`.
5. После загрузки откройте страницу dataset.

Поддерживаются текстовые и документные форматы: `txt`, `md`, `markdown`, `json`, `jsonl`, `ndjson`, `csv`, `tsv`, `yaml`, `yml`, `xml`, `html`, `htm`, `rst`, `org`, `log`, `pdf`, `docx`. Максимальный размер одного файла: 10 MB.

После upload документ уходит на chunking и embedding в фоне. На странице dataset проверьте, что появились documents и chunks. Если документов несколько, используйте `Upload more`.

## 2. Сгенерировать golden Q&A

1. На странице dataset откройте блок `Golden Q&A`.
2. Нажмите `Generate Golden Q&A`.
3. Выберите sample size от 5 до 50 chunks.
4. Подтвердите генерацию.

Система генерирует один benchmark question и expected answer на каждый выбранный chunk. Эти пары становятся базой для объективного сравнения pipeline-конфигураций в experiment.

Если golden Q&A не создаётся, проверьте:

- в dataset уже есть chunks;
- подписка активна и квота не закончилась;
- провайдер генерации доступен.

## 3. Запустить experiment

1. Откройте `Experiments`.
2. Нажмите `New Experiment`.
3. Задайте имя experiment.
4. Выберите dataset с готовыми golden Q&A.
5. Выберите варианты плагинов для обязательных стадий.
6. Нажмите `Run experiment`.

Experiment перебирает выбранную матрицу plugin-конфигураций по golden Q&A и собирает leaderboard. Квота списывается на реальные embedder/generator вызовы по каждой комбинации и каждому golden item.

## 4. Выбрать победителя и промотировать в pipeline

1. Откройте страницу experiment.
2. Посмотрите leaderboard: score, per-question retrieval, generated answers и дополнительные метрики.
3. На лучшей комбинации нажмите `Promote`.
4. Введите `Pipeline name`.
5. Нажмите `Create pipeline`.

После промоутa создаётся pipeline с опубликованной версией конфигурации. Это и есть production-кандидат, через который пользователь будет задавать вопросы.

## 5. Задавать вопросы через pipeline

Вариант через UI:

1. Откройте `Pipelines`.
2. Выберите нужный pipeline.
3. В блоке `Run a query` введите вопрос.
4. Нажмите `Run`.

Вариант со страницы dataset:

1. Откройте dataset.
2. В блоке `Ask` выберите pipeline.
3. Введите вопрос и отправьте запрос.

Вариант через API:

1. Создайте API key в `Account`.
2. Вызовите `POST /api/v1/rag/query`.
3. Передайте `dataset_id`, `query`, `top_k` и, если нужен конкретный production pipeline, `pipeline_id`.

## 6. Смотреть ответы и аудит в runs

1. Откройте `Runs`.
2. Найдите созданный run.
3. Откройте detail page.

Run показывает:

- исходный query;
- status;
- answer;
- retrieved chunks;
- reranked chunks, если стадия reranker включена;
- token usage;
- duration;
- RAGAS metrics, если они рассчитаны.

Runs — это журнал фактического поведения pipeline. Если ответ выглядит неправильно, начинать диагностику нужно именно с run detail: какие chunks были найдены, как они были переранжированы, сколько токенов ушло и какой ответ сгенерирован.

## Приёмочный чеклист

- Dataset содержит хотя бы один документ.
- У dataset есть chunks.
- Golden Q&A содержит вопросы и ответы, связанные с source chunks.
- Experiment завершился и leaderboard содержит scored rows.
- Лучшая комбинация promoted в pipeline.
- Pipeline query создаёт completed run.
- Run detail показывает answer и supporting chunks.

## Частые сбои

| Симптом | Что проверить |
|---|---|
| `402 Payment Required` при upload, golden generation, experiment или run | Активен ли план и осталась ли квота |
| Golden Q&A создаёт 0 items | Есть ли chunks у dataset |
| Experiment пустой или весь failed | Есть ли golden Q&A и доступны ли выбранные провайдеры |
| Pipeline не запускается | Есть ли опубликованная версия pipeline после promote |
| Ответ не похож на ожидаемый | Откройте run detail и проверьте retrieved/reranked chunks |

