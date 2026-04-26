# Infrastructure

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Docker Desktop | >= 4.x | https://docs.docker.com/get-docker/ |
| kubectl | >= 1.28 | https://kubernetes.io/docs/tasks/tools/ |
| helm | >= 3.14 | https://helm.sh/docs/intro/install/ |
| kind | >= 0.23 | https://kind.sigs.k8s.io/ (or auto-installed by bootstrap.sh) |
| tilt | >= 0.33 | https://docs.tilt.dev/install.html |

## Local dev (one command)

```bash
chmod +x infra/kind/bootstrap.sh infra/scripts/teardown.sh infra/scripts/seed-dev-data.sh
./infra/kind/bootstrap.sh && tilt up
```

See `infra/kind/README.md` for details.

## Directory layout

```
infra/
  kind/
    kind-config.yaml      kind cluster definition (1 control-plane + 2 workers)
    Tiltfile              hot-reload orchestration
    bootstrap.sh          idempotent cluster setup
    README.md
  scripts/
    teardown.sh           delete the kind cluster
    seed-dev-data.sh      insert stub org + user into postgres
  README.md               this file
```

## Helm chart

The chart lives in `charts/rag-p/`. See `charts/rag-p/README.md` for installation, env vars, and troubleshooting.

## Cluster-wide components (not in chart)

The following must be installed once per cluster manually:

- **CloudNativePG operator** — manages PostgreSQL Cluster CRD
- **cert-manager** — TLS certificates (staging/prod only; not needed in dev)
- **External Secrets Operator** — if `externalSecrets.enabled=true`

bootstrap.sh installs CNPG and ingress-nginx automatically for dev.
