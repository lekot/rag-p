# Operations runbook

Day-to-day operations of the production deployment on lekottt.ru. This runbook is consumed by Strazh and by Maks during outages.

## Healthchecks

- `https://api.lekottt.ru/health` — liveness, returns 200 with `{"status": "ok"}` when FastAPI process is alive.
- `https://api.lekottt.ru/ready` — readiness, returns 200 only when DB and Redis are reachable.
- `https://lekottt.ru` — Next.js frontend, returns the marketing landing.

If `/health` returns 5xx, restart the API container. If `/ready` is red while `/health` is green, look at `docker logs postgres` and `docker logs redis`.

## Common tasks

### Tail logs

```
ssh gemcraft-claude
cd /opt/rag-p/deploy/compose
docker compose logs -f api worker
```

Use `--since=10m` to limit history. Logs are JSON-formatted; pipe through `jq` for readability.

### Restart a service

```
docker compose restart api
```

This is safe under load — uvicorn's graceful shutdown drains in-flight requests before exiting. Ingest jobs that are already started complete; queued jobs are picked up by the new process.

### Apply migrations

Migrations are NOT auto-applied on container start. Run them explicitly:

```
docker compose run --rm api alembic upgrade head
```

If a migration fails, inspect with:

```
docker compose run --rm api alembic current
docker compose run --rm api alembic history --verbose
```

### Roll back a release

The convention is one tag per release, semantic version. Roll back by re-pulling the previous tag:

```
docker compose pull api worker
docker compose up -d api worker
```

If migrations changed schema, you must also revert with `alembic downgrade` BEFORE swapping containers.

### Drain a worker

ARQ workers have a graceful-shutdown signal (`SIGTERM`). Send via:

```
docker compose stop --timeout 60 worker
```

In-flight experiments mark themselves as `failed` with `error=worker_shutdown`. Re-queue them manually if they are critical.

## Postgres maintenance

### Backup

CNPG (CloudNative-PG) handles continuous WAL archiving to S3. Restore drills documented in `docs/cnpg-backup-restore.md`.

### Vacuum

Auto-vacuum is on with default thresholds. For the `chunks` table on a large bench dataset, manual vacuum once a week is a good idea:

```
docker exec -it postgres psql -U ragp -d ragp -c "VACUUM ANALYZE chunks;"
```

### Index rebuild

If pgvector recall drops after large deletions, rebuild the IVFFLAT index:

```
docker exec -it postgres psql -U ragp -d ragp -c "REINDEX INDEX chunks_embedding_idx;"
```

For HNSW indexes, rebuild is rarely needed — the algorithm tolerates updates well.

## Redis

### Inspect queue depth

```
docker exec -it redis redis-cli LLEN arq:queue
```

If depth grows monotonically and workers are alive, you have a poison message — `LPOP` it manually:

```
docker exec -it redis redis-cli LPOP arq:queue
```

### Clear rate-limit buckets

Useful after testing or to apologise to a user whose limit was hit unfairly:

```
docker exec -it redis redis-cli --scan --pattern "ratelimit:*" | xargs -L 100 docker exec -i redis redis-cli DEL
```

## YooKassa

### Check pending payments

YooKassa webhooks land at `/api/v1/billing/webhook/yookassa`. If a payment is stuck pending for >10 minutes, log in to the YooKassa dashboard, find the payment, and either cancel or capture manually.

### Re-trigger a webhook

YooKassa retries failed webhooks automatically with exponential backoff for up to 24 hours. If you lost the original webhook (e.g. nginx was down), you can replay manually:

```
curl -X POST -H "Content-Type: application/json" \
     -d '{"event":"payment.succeeded","object":{"id":"...","status":"succeeded","metadata":{"org_id":"...","plan_id":"..."}}}' \
     https://api.lekottt.ru/api/v1/billing/webhook/yookassa
```

## Common alerts

### High API latency

- Check `docker stats` for CPU saturation on api/worker.
- Check Postgres slow query log: `SET log_min_duration_statement = 500;`.
- Check Redis: `INFO stats` and look at `instantaneous_ops_per_sec`.

### High error rate

- 5xx → look at API logs first.
- 402 spike → check whether a plan expired silently; subscriptions table has `period_end` column.
- 429 spike → check rate-limiter config; might be a misconfigured limit after a plan upgrade.
- 401 spike → likely a session-cookie outage in the frontend.

### Disk fill

The biggest consumers are:
1. Postgres data dir (chunks + embeddings).
2. Object storage (raw documents).
3. Docker logs (rotate via `daemon.json` `log-opts`).

Run:

```
df -h /var/lib/docker
docker system df -v
```

If S3 is the issue, run the orphan-cleanup script:

```
python apps/api/scripts/cleanup_orphan_objects.py --dry-run
```

(The script is not yet committed — TODO.)

## Smoke tests after deploy

1. Hit `/health` and `/ready`.
2. Hit `/api/v1/auth/me` with a known session — should return user+org.
3. Open the dashboard in a browser, ensure the dataset list loads.
4. Run a quick `rag/query` against a known dataset and a known API key — answer should be non-empty.
5. Check `docker logs api` for any new ERROR entries.
