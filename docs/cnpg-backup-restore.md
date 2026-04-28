# CNPG Backup & Disaster Recovery (Selectel S3)

## Обзор

Резервное копирование PostgreSQL-кластера реализовано через [barman](https://pgbarman.org/) object store CNPG.  
WAL-архивирование и base-backup складываются в Selectel S3 (совместимый с AWS S3 API).  
Ежедневный `ScheduledBackup` запускается в **02:00 UTC**.

---

## 1. Создать bucket в Selectel Object Storage

1. Панель управления Selectel → **Облачная платформа** → **Хранилище объектов**.
2. Нажать **Создать контейнер**.
3. Имя: `rag-p-backups-staging` (или значение `postgres.cnpg.backup.bucketName` из values).
4. Тип доступа: **Приватный**.
5. Регион — тот же, что указан в `endpointURL` (по умолчанию `ru-1`).

> Создание bucket выполняется вручную и не входит в scope Helm-чарта.

---

## 2. Создать k8s secret с кредами S3

```bash
kubectl create secret generic cnpg-s3-credentials \
  -n rag-p \
  --from-literal=ACCESS_KEY_ID=<ваш-access-key> \
  --from-literal=ACCESS_SECRET_KEY=<ваш-secret-key>
```

Secret создаётся **вручную** до первого `helm install/upgrade` и не управляется Helm (чтобы не потерять при `helm uninstall`).

Получить ключи: Панель Selectel → **Профиль** → **Сервисные пользователи** → создать пользователя с доступом к нужному контейнеру.

---

## 3. Включить backup в values

**values.staging.yaml** (уже включено в репо):
```yaml
postgres:
  cnpg:
    backup:
      enabled: true
      bucketName: "rag-p-backups-staging"
      # endpointURL: "https://s3.ru-1.storage.selcloud.ru"  # переопределить при смене региона
```

После `helm upgrade`:
```bash
helm upgrade rag-p charts/rag-p -n rag-p -f charts/rag-p/values.staging.yaml
```

---

## 4. Проверить, что backup работает

```bash
# Список всех backup-объектов в namespace
kubectl get backups -n rag-p

# Статус расписания
kubectl describe scheduledbackup rag-p-postgres-daily -n rag-p

# Запустить внеплановый backup вручную
kubectl cnpg backup rag-p-postgres -n rag-p

# Просмотреть WAL-архив в barman
kubectl exec -n rag-p rag-p-postgres-1 -- \
  barman-cloud-wal-list \
  --cloud-provider aws-s3 \
  --endpoint-url https://s3.ru-1.storage.selcloud.ru \
  s3://rag-p-backups-staging/cnpg rag-p-postgres
```

---

## 5. Runbook: восстановление из backup (Disaster Recovery)

### 5.1 Полное восстановление (новый кластер из backup)

Создать файл `postgres-recovery.yaml`:

```yaml
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: rag-p-postgres-recovery
  namespace: rag-p
spec:
  instances: 1
  imageName: ghcr.io/cloudnative-pg/postgresql:16.4

  bootstrap:
    recovery:
      source: rag-p-postgres
      # Для PITR — раскомментировать и указать целевое время:
      # recoveryTarget:
      #   targetTime: "2026-04-28 03:00:00"

  externalClusters:
    - name: rag-p-postgres
      barmanObjectStore:
        destinationPath: s3://rag-p-backups-staging/cnpg
        endpointURL: https://s3.ru-1.storage.selcloud.ru
        s3Credentials:
          accessKeyId:
            name: cnpg-s3-credentials
            key: ACCESS_KEY_ID
          secretAccessKey:
            name: cnpg-s3-credentials
            key: ACCESS_SECRET_KEY
        wal:
          maxParallel: 8

  storage:
    size: 10Gi
    storageClass: fast.ru-3b
```

Применить:
```bash
kubectl apply -f postgres-recovery.yaml
```

Следить за статусом:
```bash
kubectl get cluster rag-p-postgres-recovery -n rag-p -w
```

### 5.2 Переключить приложение на восстановленный кластер

После того как кластер перешёл в `Healthy`:

```bash
# Обновить секрет (или пересоздать его с новым именем хоста)
kubectl patch secret rag-p-postgres-app -n rag-p \
  -p '{"stringData":{"host":"rag-p-postgres-recovery-rw"}}'

# Перекатить деплойменты
kubectl rollout restart deployment -n rag-p
```

### 5.3 Удалить временный recovery-кластер

После успешного переключения:
```bash
kubectl delete cluster rag-p-postgres-recovery -n rag-p
```

---

## Параметры values (справочник)

| Параметр | Default | Описание |
|---|---|---|
| `postgres.cnpg.backup.enabled` | `false` | Включить backup |
| `postgres.cnpg.backup.bucketName` | `""` | Имя S3-bucket |
| `postgres.cnpg.backup.endpointURL` | `https://s3.ru-1.storage.selcloud.ru` | S3-endpoint (зависит от региона) |
| `postgres.cnpg.backup.retentionPolicy` | `30d` | Политика хранения |
| `postgres.cnpg.backup.schedule` | `0 2 * * *` | Cron-расписание (UTC) |
