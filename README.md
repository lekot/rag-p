# RAG-Platform

RAG-Platform is an open-core, self-hostable Pipeline-as-a-Service for documents. It provides a laboratory UI where analysts — without writing code — can combine chunkers, embedding models, rerankers, and LLMs, run experiments against a QA dataset, and compare strategies side-by-side with a fixed composite score per option.

The system ships as a single Helm chart that works identically in local development (kind + Tilt), staging, and production. Multi-tenancy, fine-grained RBAC, eval-loop, and observability are built in from day one — not added later. See [opportunity.md](opportunity.md) for the full product thesis and competitive landscape analysis.

Plugin interfaces (`Chunker / Embedder / Retriever / Reranker / Generator`) each expose a `params_schema` (JSON Schema), which drives the form-based pipeline editor in the UI automatically. Every experiment is the Cartesian product of valid plugin configurations run against a user dataset; results land in a leaderboard with per-combination scores. See [docs/architecture.md](docs/architecture.md) for a component overview and [docs/adr/](docs/adr/) for architectural decisions.

## Quick start

### Development (kind + Tilt)

```bash
# Prerequisites: Docker Desktop, kind, Tilt, kubectl, helm
git clone https://github.com/lekot/rag-p.git
cd rag-p
tilt up
# UI at http://localhost:3000, API at http://localhost:8000
```

### Production (Helm)

```bash
helm repo add rag-p https://lekot.github.io/rag-p
helm install rag-p rag-p/rag-p \
  --namespace rag-p --create-namespace \
  --values your-values.yaml
```

See `charts/rag-p/values.yaml` for the full configuration reference.

## Monorepo structure

```
rag-p/
  apps/
    api/          # FastAPI backend — pipeline runner, plugin registry, eval-loop
    web/          # Next.js + tRPC + shadcn/ui — analyst UI
  charts/
    rag-p/        # Helm chart for the entire platform
  infra/
    tiltfile      # Local dev orchestration
    kind/         # kind cluster config
  docs/
    adr/          # Architectural Decision Records (MADR format)
    architecture.md
  Makefile        # Dev shortcuts: make dev, make lint, make test
```

## ADR index

| # | Decision |
|---|---|
| [0001](docs/adr/0001-plugin-architecture.md) | Plugin architecture via entrypoints and params_schema |
| [0002](docs/adr/0002-authz-permify-internal.md) | Authorization via Permify (Zanzibar-like) |
| [0003](docs/adr/0003-multi-tenant-from-mvp.md) | Multi-tenancy from day one via organization_id |
| [0004](docs/adr/0004-k8s-only-no-compose.md) | Kubernetes-only stack (kind + Tilt for dev) |
| [0005](docs/adr/0005-pipeline-as-a-service-fixed-score.md) | Experiment model with fixed composite score |

## License

AGPL-3.0. See [LICENSE](LICENSE).
