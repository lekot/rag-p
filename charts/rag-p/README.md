# rag-p Helm Chart

RAG Platform umbrella chart. Deploys API, Web, Worker, PostgreSQL (CNPG), Redis, Langfuse, Permify, MinIO, LiteLLM.

## Prerequisites

### Cluster-wide operators (manual install required)

Install once per cluster before deploying this chart:

```bash
# CloudNativePG operator
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.23/releases/cnpg-1.23.0.yaml

# cert-manager (for TLS in staging/prod)
kubectl apply -f \
  https://github.com/cert-manager/cert-manager/releases/download/v1.15.0/cert-manager.yaml

# External Secrets Operator (if externalSecrets.enabled=true)
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets -n external-secrets --create-namespace
```

cert-manager ClusterIssuer example for Let's Encrypt:
```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: your@email.com
    privateKeySecretRef:
      name: letsencrypt-prod
    solvers:
      - http01:
          ingress:
            class: traefik
```

## Installation

```bash
# Add Bitnami repo for dependencies
helm repo add bitnami https://charts.bitnami.com/bitnami
helm repo update

# Fetch dependencies
helm dep update charts/rag-p

# Install (dev)
helm install rag-p charts/rag-p \
  -f charts/rag-p/values.dev.yaml \
  --namespace rag-p --create-namespace

# Install (staging)
helm install rag-p charts/rag-p \
  -f charts/rag-p/values.staging.yaml \
  --namespace rag-p --create-namespace

# Upgrade
helm upgrade rag-p charts/rag-p \
  -f charts/rag-p/values.staging.yaml \
  --namespace rag-p
```

## Key environment variables

| Variable | Source | Description |
|---|---|---|
| `DATABASE_URL` | CNPG secret + template | PostgreSQL connection string |
| `REDIS_URL` | Redis secret + template | Redis connection string |
| `MINIO_ENDPOINT` | Chart value | MinIO S3-compatible endpoint |
| `LITELLM_MASTER_KEY` | values / external-secret | LiteLLM auth key |
| `NEXTAUTH_SECRET` | Langfuse values | Langfuse NextAuth secret |

## Secrets in production

Set `externalSecrets.enabled=true` and configure a `ClusterSecretStore` named `vault-backend` (or override `externalSecrets.secretStoreRef`).

Required secret paths in your secret store:
- `rag-p/postgres` — keys: `username`, `password`
- `rag-p/redis` — key: `password`
- `rag-p/minio` — keys: `rootUser`, `rootPassword`

## Helm test

```bash
helm test rag-p -n rag-p
```

## Troubleshooting

**CNPG cluster stuck in Creating**: ensure CloudNativePG operator is installed and the CRD `clusters.postgresql.cnpg.io` exists.

**Redis auth errors**: if upgrading from auth-disabled to auth-enabled, delete the Redis StatefulSet manually and let Helm recreate it.

**Langfuse DATABASE_URL**: Langfuse expects PostgreSQL 14+. CNPG default is 16 — compatible.

**pgvector extension missing**: ensure you used a PostgreSQL image with pgvector. The CNPG Cluster bootstrap `postInitSQL` runs `CREATE EXTENSION IF NOT EXISTS vector` — this requires the extension binary to be present in the image. Use `ghcr.io/cloudnative-pg/postgresql:16-vectors` or a custom image.
