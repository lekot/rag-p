# ADR 0004 — Kubernetes-only стек (kind + Tilt для dev, k3s + Helm для prod)

**Статус:** Принято  
**Дата:** 2026-04-27

---

## Контекст

Продукт поставляется одним Helm chart. Пользователь явно подтвердил: "k8s only — ok". Нужен dev-стек, который максимально близок к production, чтобы избежать класса ошибок "работает в compose, падает в k8s".

---

## Рассмотренные варианты

### 1. docker-compose для dev, Helm для prod

Классическое разделение. Compose быстро поднимается, понятен большинству разработчиков. Но: divergence между compose и Helm неизбежен — разные переменные окружения, разные имена сервисов, разные network policies. Ошибки обнаруживаются только в staging.

**Отклонено** — divergence prod/dev.

### 2. Coolify / Caprover (PaaS над Docker)

Упрощает деплой, нет необходимости знать Kubernetes. Но: vendor lock на платформу, сложно кастомизировать network policies и secrets management, не соответствует заявленному Helm-first подходу.

**Отклонено** — vendor lock.

### 3. kind + Tilt для dev, k3s + Helm для prod (выбрано)

- **Dev:** `kind` (Kubernetes in Docker) создаёт локальный кластер на 1-3 ноды. `Tilt` оркестрирует hot-reload: при изменении исходников пересобирает образ и делает `kubectl rollout restart` автоматически.
- **Staging/Prod:** `k3s` на Hetzner, GitOps через ArgoCD (push в main → деплой в staging-namespace).
- Один и тот же Helm chart используется во всех окружениях; различия — только `values.yaml`.

---

## Решение

Принять вариант 3. Никакого `docker-compose.yml` в репозитории — чтобы не возникало соблазна использовать его и создавать drift.

Минимальный вход для разработчика: Docker Desktop (или Docker Engine + kind), Tilt, kubectl, helm. Команда `tilt up` поднимает полный стек локально.

---

## Последствия

**Плюсы:**
- Одинаковый стек dev/staging/prod — класс "работает только в compose" исключён.
- Helm chart тестируется с первого дня разработки.
- Tilt обеспечивает быстрый inner loop без потери k8s-окружения.

**Минусы:**
- Выше порог входа для нового контрибьютора: нужен Docker Desktop или эквивалент, kind, Tilt.
- Cold start кластера kind на слабых машинах — 2-3 минуты.

**Риск:** Windows-разработчики без Docker Desktop могут столкнуться с проблемами WSL2 + kind. Документировать в CONTRIBUTING.md как known issue.
