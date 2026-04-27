# Staging runbook

Selectel managed k8s cluster `rosalinda` (1 node, 2 vCPU / 8 GB / 40 GB), Cilium CNI, Traefik LB at `139.100.200.55`. Domain `lekottt.ru`.

## Daily ops

Set kubeconfig once per shell:
```
export KUBECONFIG=$PWD/infra/.kube/staging.config
```
(or merge with `$HOME/.kube/config` via `kubectl config view --flatten`)

### Health
```
kubectl -n rag-p get pods
kubectl -n rag-p get svc,ingress
curl https://api.lekottt.ru/healthz
curl https://lekottt.ru/
```

### Tail logs
```
kubectl -n rag-p logs -l app.kubernetes.io/component=api --tail=100 -f
kubectl -n rag-p logs -l app.kubernetes.io/component=web --tail=100 -f
```

### Scale node group to zero (save money overnight)
Selectel UI → Managed k8s → cluster `rosalinda` → node group → set count to 0. PVC survive (postgres data, minio blobs). Restore by setting count to 1 — pods come back in ~3 minutes.

## Releases

Tagging a `v*.*.*` triggers `Docker build and push` workflow → ghcr.io/lekot/rag-p-{api,web}:{X.Y.Z}.

```
git tag -a v0.1.x -m "..."
git push origin v0.1.x
gh run watch <run_id> --repo lekot/rag-p
```

Then upgrade chart:
```
# bump charts/rag-p/values.staging.yaml api.image.tag and web.image.tag to "0.1.x"
helm upgrade rag-p ./charts/rag-p -n rag-p \
  -f charts/rag-p/values.staging.yaml --wait --timeout 4m
```

### Re-run migrations only (after schema change)
Migrations run as Helm post-install/post-upgrade hook. Force re-run:
```
kubectl -n rag-p delete job rag-p-migrate
helm upgrade rag-p ./charts/rag-p -n rag-p -f charts/rag-p/values.staging.yaml
```

## Cluster-wide operators (manual install, one-time)

Already installed:
- CloudNativePG operator (`cnpg-system` ns)
- Traefik (`traefik` ns) with `LoadBalancer` Service → Octavia LB
- cert-manager (`cert-manager` ns)

Reinstall after cluster recreate:
```
helm repo add cnpg https://cloudnative-pg.github.io/charts
helm repo add traefik https://traefik.github.io/charts
helm repo add jetstack https://charts.jetstack.io
helm repo update

helm upgrade --install cnpg cnpg/cloudnative-pg -n cnpg-system --create-namespace --wait
helm upgrade --install traefik traefik/traefik -n traefik --create-namespace \
  --set service.type=LoadBalancer \
  --set ingressClass.enabled=true --set ingressClass.isDefaultClass=true \
  --set ingressClass.name=traefik --wait
helm upgrade --install cert-manager jetstack/cert-manager -n cert-manager --create-namespace \
  --set crds.enabled=true --wait
```

## Secrets

```
kubectl -n rag-p create secret docker-registry ghcr-pull \
  --docker-server=ghcr.io --docker-username=lekot \
  --docker-password=$(gh auth token) --docker-email=papanifontov@gmail.com
```

LLM keys (when ready):
```
kubectl -n rag-p create secret generic llm-keys \
  --from-literal=OPENAI_API_KEY=sk-... \
  --from-literal=ANTHROPIC_API_KEY=sk-ant-... \
  --from-literal=COHERE_API_KEY=...
# then add envFrom: secretRef: name: llm-keys to api/worker deployments
```

## Postgres access

```
kubectl -n rag-p exec -it rag-p-postgres-1 -c postgres -- psql -U postgres ragp
# or via app user
kubectl -n rag-p get secret rag-p-postgres-app -o jsonpath='{.data.password}' | base64 -d
```

## TODO

- **Vault / External Secrets Operator.** Currently k8s secrets are created via `kubectl create secret` (one-shot, not in version control, vulnerable to typos and rotation drift). When the cluster gets a second human or a real prod tenant, deploy:
  - HashiCorp Vault (helm chart `hashicorp/vault`, dev mode for staging, full HA for prod) OR Bitwarden-secrets-manager
  - external-secrets-operator (already toggleable in chart via `externalSecrets.enabled`)
  - migrate `ghcr-pull` and `llm-keys` to ExternalSecret CRDs with auto-rotation
- **Backups.** CNPG supports `Backup` CRD pushing to S3-compatible storage. Selectel S3 is available — wire in when `langfuse` and real datasets land.
- **Cilium L7 NetworkPolicy.** Templates ready (`networkPolicy.cilium.enabled=true`), but staging runs without isolation while we iterate on routes. Enable before first external tenant.
- **HPA + node autoscaling.** Currently 1 fixed node. When 2+ tenants, enable `api.autoscaling.enabled` and Selectel cluster autoscaler.

## Disaster recovery

PVCs (postgres `pg-data`, minio data) live on Selectel Block Storage, survive node restart. CNPG `Backup` CRD can push to S3 — not configured on staging.

If chart breaks:
```
helm rollback rag-p -n rag-p   # to previous revision
# or
helm uninstall rag-p -n rag-p && helm install ...
# PVCs persist; reuse postgres data automatically.
```

## Cost (current)

- Cluster control plane + 1 node: ~9150 RUB/month (305 RUB/day)
- Octavia LB: ~5000 RUB/month
- PVCs (~25 GB total): ~125 RUB/month
- Total: ~14000 RUB/month at full uptime

Scale node group to zero overnight to halve costs.
