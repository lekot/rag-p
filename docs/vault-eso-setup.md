# Vault + ESO Setup Runbook

HashiCorp Vault развёрнут как sub-chart внутри `charts/rag-p/`.  
External Secrets Operator (ESO) — cluster-wide operator, устанавливается отдельно.

**Важно**: пока `vault.enabled: false` (дефолт), всё работает как прежде — секреты создаются вручную через `kubectl create secret`. Переход на ESO постепенный и не является deploy-blocker.

---

## Шаг 0. Установить ESO в кластер (один раз)

ESO — cluster-scoped operator. Устанавливается один раз, живёт в своём namespace.

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

helm install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace \
  --set installCRDs=true
```

Проверка:
```bash
kubectl -n external-secrets get pods
```

---

## Шаг 1. Включить Vault в чарт и задеплоить

В `values.staging.yaml` установить:
```yaml
vault:
  enabled: true
```

Обновить dependencies и задеплоить:
```bash
helm dependency build charts/rag-p
helm upgrade --install rag-p charts/rag-p \
  -n rag-p \
  -f charts/rag-p/values.staging.yaml
```

После деплоя Vault pod поднимется, но будет в состоянии `sealed` (не инициализирован).

---

## Шаг 2. Инициализация Vault (один раз, ручная)

```bash
kubectl exec -n rag-p rag-p-vault-0 -- vault operator init \
  -key-shares=1 -key-threshold=1 \
  -format=json
```

Команда вернёт JSON с `unseal_keys_b64` и `root_token`. **Сохранить в защищённом месте** (1Password, менеджер паролей).

Unseal:
```bash
kubectl exec -n rag-p rag-p-vault-0 -- vault operator unseal <unseal_key>
```

---

## Шаг 3. Настройка Kubernetes auth method

```bash
# Войти как root (используем exec + env)
kubectl exec -n rag-p rag-p-vault-0 -- \
  env VAULT_TOKEN=<root_token> vault auth enable kubernetes

kubectl exec -n rag-p rag-p-vault-0 -- \
  env VAULT_TOKEN=<root_token> vault write auth/kubernetes/config \
    kubernetes_host="https://kubernetes.default.svc"

# Создать policy
kubectl exec -n rag-p rag-p-vault-0 -- \
  env VAULT_TOKEN=<root_token> vault policy write rag-p-secrets-policy - <<EOF
path "secret/data/rag-p/*" {
  capabilities = ["read"]
}
EOF

# Создать роль, привязанную к ESO ServiceAccount
kubectl exec -n rag-p rag-p-vault-0 -- \
  env VAULT_TOKEN=<root_token> vault write auth/kubernetes/role/rag-p-secrets \
    bound_service_account_names=rag-p-eso-sa \
    bound_service_account_namespaces=rag-p \
    policies=rag-p-secrets-policy \
    ttl=1h
```

Имя ServiceAccount `rag-p-eso-sa` совпадает с тем, что создаётся в `vault-eso-serviceaccount.yaml`.

---

## Шаг 4. Включить KV v2 и загрузить секреты

```bash
# Включить KV v2 (если не включён)
kubectl exec -n rag-p rag-p-vault-0 -- \
  env VAULT_TOKEN=<root_token> vault secrets enable -path=secret kv-v2

# LLM API ключи
kubectl exec -n rag-p rag-p-vault-0 -- \
  env VAULT_TOKEN=<root_token> vault kv put secret/rag-p/llm \
    deepseek_api_key=sk-xxx \
    openai_api_key=sk-xxx \
    anthropic_api_key=sk-ant-xxx \
    cohere_api_key=xxx \
    minimax_api_key=xxx

# S3 credentials для CNPG backup
kubectl exec -n rag-p rag-p-vault-0 -- \
  env VAULT_TOKEN=<root_token> vault kv put secret/rag-p/s3 \
    access_key=xxx \
    secret_key=xxx

# Session secret для API
kubectl exec -n rag-p rag-p-vault-0 -- \
  env VAULT_TOKEN=<root_token> vault kv put secret/rag-p/session \
    secret=$(python -c 'import secrets; print(secrets.token_urlsafe(48))')
```

---

## Шаг 5. Включить ExternalSecret-ы

После того как секреты загружены в Vault, включать ExternalSecret-ы по одному:

```yaml
# values.staging.yaml
vault:
  enabled: true
  externalSecrets:
    llmKeys: true    # заменяет ручной kubectl create secret для llm-keys
    s3: true         # заменяет ручной kubectl create secret для cnpg-s3-credentials
    session: true    # заменяет ручной kubectl create secret для <release>-api-secrets
```

```bash
helm upgrade rag-p charts/rag-p \
  -n rag-p \
  -f charts/rag-p/values.staging.yaml
```

**ESO автоматически перезапишет существующие секреты** с тем же именем (`creationPolicy: Owner`). API, worker, CNPG не перезапустятся — секреты обновляются прозрачно.

---

## Migration plan

| Секрет | Текущий способ | После включения ESO |
|--------|---------------|---------------------|
| `llm-keys` (llmKeysSecret) | `kubectl create secret` вручную | `vault.externalSecrets.llmKeys: true` |
| `cnpg-s3-credentials` | `kubectl create secret` вручную | `vault.externalSecrets.s3: true` |
| `<release>-api-secrets` (sessionSecret) | `kubectl create secret` вручную | `vault.externalSecrets.session: true` |
| postgres app secret | создаёт CNPG operator | остаётся за оператором (ESO не трогает) |
| redis password | создаёт bitnami chart | остаётся за чартом (auth.enabled: false в staging) |

Переход не ломает существующий деплой: пока флаги отключены, чарт не создаёт ExternalSecret-ы.

---

## После перезапуска ноды / pod-а Vault

Vault `sealed` при каждом перезапуске. После рестарта pod-а нужно повторно unseal:

```bash
kubectl exec -n rag-p rag-p-vault-0 -- vault operator unseal <unseal_key>
```

Для production-нагрузки рекомендуется настроить [auto-unseal через Transit](https://developer.hashicorp.com/vault/docs/configuration/seal/transit) или Cloud KMS.
