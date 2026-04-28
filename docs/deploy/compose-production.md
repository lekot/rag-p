# Compose production pilot

## Decision

For the pilot stage, production runs on one Docker Compose host instead of the
managed Kubernetes staging cluster. Kubernetes manifests and Helm charts stay in
the repository as the future scale/HA path, but automatic deploy is gated by the
`DEPLOY_TARGET` repository variable.

This is a cost and delivery-speed decision: the current Kubernetes setup is
single-node in practice, so it does not buy real HA, while Helm/CRD/PVC/operator
complexity already slows production rollout.

## Runtime

The Compose target is `deploy/compose/compose.prod.yml`.

Services:

- `caddy`: public TLS reverse proxy for `lekottt.ru` and `api.lekottt.ru`.
- `web`: Next.js standalone image.
- `api`: FastAPI image.
- `worker`: ARQ worker using the API image.
- `migrate`: one-shot Alembic service used by CI/CD.
- `postgres`: `pgvector/pgvector:pg16` with local volume.
- `redis`: queue/cache, no persistence for pilot.
- `ollama`: local model runtime with local model volume.

Persistent volumes:

- `postgres_data`: database.
- `ollama_models`: downloaded Ollama models.
- `caddy_data`, `caddy_config`: ACME certificates and Caddy state.

## GitHub settings

Repository variable:

- `DEPLOY_TARGET=compose` enables automatic Compose deploy after CI on `main`.
- `DEPLOY_TARGET=kubernetes` enables the legacy Helm staging workflow.
- Any other value disables automatic deploys; manual workflow dispatch remains.

Production environment secrets:

- `COMPOSE_HOST`: server IP or hostname.
- `COMPOSE_USER`: SSH user.
- `COMPOSE_SSH_PRIVATE_KEY`: private key for that user.
- `COMPOSE_POSTGRES_PASSWORD`: database password. Use a URL-safe generated
  value because the app DSN is assembled from Compose variables.
- `GHCR_READ_TOKEN`: GitHub token with `read:packages` for pulling GHCR images.
- `RAGP_SESSION_SECRET`: session signing secret.
- `RAGP_SECRET_KEY`: application secret.
- `RAGP_YOOKASSA_SHOP_ID`: YooKassa shop id.
- `RAGP_YOOKASSA_SECRET_KEY`: YooKassa secret key.
- `RAGP_YOOKASSA_WEBHOOK_SECRET`: YooKassa webhook secret.
- `RAGP_YOOKASSA_INN`: receipt INN.
- `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `COHERE_API_KEY`: optional provider keys.

Optional repository variable:

- `COMPOSE_SSH_PORT`: SSH port, default `22`.

## Cutover

Assumption: there is no valuable production data to migrate. The only valuable
business state is YooKassa account configuration, kept in GitHub secrets.

1. Stop or delete the Kubernetes manager/control-plane so the worker node becomes
   the single Compose host.
2. Install Docker Engine with the Compose plugin on the host.
3. Make sure ports `80` and `443` are free.
4. Add the GitHub secrets and set `DEPLOY_TARGET=compose`.
5. Run `Deploy to Compose production` manually once, or push to `main` after CI.
6. Verify:
   - `https://api.lekottt.ru/healthz` returns `{"status":"ok"}`.
   - `https://lekottt.ru/signup` loads with a non-empty Next CSS asset.
   - Registration and login work.
   - YooKassa checkout still uses the moderator-approved shop settings.

The IP does not change, so DNS cutover is not required.

## Rollback

Rollback is image-tag based:

1. Open the last successful `Deploy to Compose production` workflow.
2. Re-run it for the previous commit, or manually set `RAGP_API_IMAGE` and
   `RAGP_WEB_IMAGE` in `/opt/rag-p/.env` to previous `sha-*` tags.
3. Run `docker compose -f /opt/rag-p/compose.prod.yml --env-file /opt/rag-p/.env up -d`.

Database downgrade is not automated. For the pilot phase, migrations should be
treated as forward-only unless a specific manual rollback is written.

## Known limits

- This is not HA: one host, one Postgres, one worker pool.
- Backups are not yet automated in this bundle.
- Resource isolation is container-level only, not namespace/cluster-level.
- Experiments still need product-level work: tenant isolation, billing,
  durable runs, prioritised queues, cancellation, retries, and observability.
