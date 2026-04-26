# ADR 0002 — Авторизация через Permify (Zanzibar-like), internal deployment

**Статус:** Принято  
**Дата:** 2026-04-27

---

## Контекст

Продукт — multi-tenant с первого дня (см. ADR 0003). Нужен fine-grained RBAC: пользователь tenant A не может видеть pipeline tenant B; внутри одного тенанта — роли viewer/editor/admin с разными правами на разные объекты (pipeline, dataset, run, document).

Стандартного Postgres-based middleware недостаточно: проверки типа "может ли user X выполнить action Y на resource Z" требуют relationship graph, а не только столбца `role`.

---

## Рассмотренные варианты

### 1. Postgres RLS

Row-Level Security на уровне базы данных. Изолирует строки по `organization_id` автоматически. Просто для изоляции тенантов, но не покрывает роле-объектные проверки ("editor может конфигурировать pipeline, но не управлять членами организации"). Логика прав рассыпается по миграциям и SQL-политикам — сложно тестировать.

**Отклонено** — недостаточно для fine-grained проверок.

### 2. OpenFGA

Zanzibar-совместимый open-source движок от Okta. Хороший API, активное сообщество. На момент принятия решения Permify имеет более чистый Go SDK и более удобный DSL для описания модели.

**Отклонено** — Permify предпочтительнее по API и DSL на момент выбора. Решение пересматривается, если OpenFGA значительно опередит по фичам.

### 3. Cerbos

Policy-based движок (YAML-политики). Хорош для attribute-based access control. Не relationship-based: отношения между объектами (pipeline принадлежит organization) выражаются в политиках явно, нет graph traversal. Для нашей модели сложнее, чем Zanzibar-подход.

**Отклонено** — policy-based, не relationship-based.

### 4. Permify (выбрано)

Zanzibar-like relationship-based authorization engine. Модель описывается в DSL, хранится в Permify. API: `check(subject, action, object)`. Поднимается как отдельный pod в кластере; UI Permify наружу не торчит (internal service).

---

## Решение

Принять вариант 4. Permify деплоится как `ClusterIP` service в том же namespace, что и API. Модель прав:

- **Entities:** `organization`, `pipeline`, `dataset`, `run`, `document`
- **Subjects:** `user`
- **Roles в organization:** `viewer` (только запускать), `editor` (конфигурировать + запускать), `admin` (управлять членами)
- **Relations:** `organization#member`, `pipeline#owner`, `dataset#owner`

API вызывает `permify.check(user_id, action, resource_id)` перед каждой мутацией. Массовые операции используют `permify.bulk_check`.

---

## Последствия

**Плюсы:**
- Стандартная Zanzibar-модель — легко понять контрибьюторам.
- Централизованные права — не разбросаны по коду.
- Легко добавить новые объекты в модель без изменений API-кода.

**Минусы:**
- Ещё один сервис в кластере (~50 MB RAM, один pod).
- Latency на каждую проверку прав (~1-5 ms при локальном деплое); нужно кэшировать решения на горячих путях.

**Риск:** при отказе Permify-pod все write-операции блокируются (fail-closed). Нужен PodDisruptionBudget и readiness probe на API.
