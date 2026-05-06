# Postgres backup runbook

## Why

The Compose-prod Postgres lives on a single host volume (`postgres_data`).
Without an off-host backup we cannot recover from disk loss, accidental
`DROP TABLE`, or a botched migration.

Targets:

- RPO: **24 hours** (one daily dump).
- RTO: **~30 minutes** for a manual restore into a side database.
- Off-host storage: a dedicated **Selectel S3 bucket**, separate from the
  application's document bucket so backup credentials can be rotated
  independently.

## How it works

A dedicated `postgres-backup` Compose service runs alongside the stack:

- Image: `postgres:16-alpine` + `aws-cli` + `jq` (built from
  `deploy/compose/postgres-backup/Dockerfile`).
- Loops in-container: sleep until `RAGP_PGBACKUP_HOUR_UTC:RAGP_PGBACKUP_MINUTE`
  (default `02:15` UTC), run `pg_dump | gzip`, upload to S3.
- On startup and before every scheduled sleep, checks the latest S3 object.
  If it is older than `RAGP_PGBACKUP_INTERVAL_HOURS` plus
  `RAGP_PGBACKUP_CATCHUP_GRACE_MINUTES` (default 60), or the prefix is empty,
  it runs an immediate catch-up backup so host downtime does not silently skip
  the RPO window.
- Object naming: `s3://$RAGP_PGBACKUP_S3_BUCKET/$RAGP_PGBACKUP_PREFIX/postgres-YYYYMMDDTHHMMSSZ.sql.gz`.
- Retention: after each upload, objects older than
  `RAGP_PGBACKUP_RETENTION_DAYS` (default 7) are deleted via
  `aws s3api list-objects-v2` + `aws s3 rm`. An empty bucket is
  treated as a normal initial state and is not an error.
- Healthcheck: `aws s3 ls s3://$bucket` runs every 5 minutes; if S3
  credentials or endpoint break, `docker compose ps` shows the service
  as unhealthy.

Failure semantics:

- A failing `pg_dump` upload **does not** trigger pruning, so the
  previous good backup is preserved.
- A failed cycle is logged and the loop continues; the container does
  not exit, so `restart: unless-stopped` does not mask the problem
  with rapid restarts.

## Setup

Configure these in `/opt/rag-p/.env` (see `deploy/compose/env.example`):

| Var | Default | Notes |
| --- | --- | --- |
| `RAGP_PGBACKUP_S3_ENDPOINT_URL` | `https://s3.ru-1.storage.selcloud.ru` | Selectel S3 endpoint. |
| `RAGP_PGBACKUP_S3_REGION` | `ru-1` | |
| `RAGP_PGBACKUP_S3_BUCKET` | `rag-p-pg-backups` | Dedicated bucket. |
| `RAGP_PGBACKUP_S3_ACCESS_KEY_ID` | _(secret)_ | Backup-only access key. |
| `RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY` | _(secret)_ | |
| `RAGP_PGBACKUP_PREFIX` | `pg-backups/` | Object key prefix inside the bucket. |
| `RAGP_PGBACKUP_HOUR_UTC` | `2` | Daily slot, hour. |
| `RAGP_PGBACKUP_MINUTE` | `15` | Daily slot, minute. |
| `RAGP_PGBACKUP_INTERVAL_HOURS` | `24` | Lower for more frequent runs. |
| `RAGP_PGBACKUP_CATCHUP_GRACE_MINUTES` | `60` | Startup/loop catch-up threshold grace after the interval. |
| `RAGP_PGBACKUP_RETENTION_DAYS` | `7` | Older objects are pruned. |

The Postgres credentials (`POSTGRES_HOST=postgres`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_DB`) are wired through the same `.env`
that the rest of the stack already uses.

After editing `.env`:

```bash
docker compose -f /opt/rag-p/compose.prod.yml --env-file /opt/rag-p/.env \
    up -d --build postgres-backup
```

## Ad-hoc backup

Take a backup right now without disturbing the loop:

```bash
docker compose -f /opt/rag-p/compose.prod.yml --env-file /opt/rag-p/.env \
    run --rm postgres-backup bash /usr/local/bin/backup.sh once
```

The command exits non-zero if the dump or upload fails; check the logs
above the exit line.

## Restore

The runbook intentionally restores into a **side database**, not into the
live `ragp` database. After verification you swap by application config
or by `pg_dump`/`pg_restore`-ing the tables you need.

1. List candidates:

   ```bash
   docker compose -f /opt/rag-p/compose.prod.yml --env-file /opt/rag-p/.env \
       run --rm --entrypoint bash postgres-backup -lc \
       'export AWS_ACCESS_KEY_ID="$RAGP_PGBACKUP_S3_ACCESS_KEY_ID"
        export AWS_SECRET_ACCESS_KEY="$RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY"
        export AWS_DEFAULT_REGION="${RAGP_PGBACKUP_S3_REGION:-ru-1}"
        export AWS_REGION="$AWS_DEFAULT_REGION"
        aws --endpoint-url "$RAGP_PGBACKUP_S3_ENDPOINT_URL" s3 ls \
        s3://$RAGP_PGBACKUP_S3_BUCKET/$RAGP_PGBACKUP_PREFIX'
   ```

2. Create an empty target DB on the live Postgres:

   ```bash
   docker compose -f /opt/rag-p/compose.prod.yml exec postgres \
       psql -U "$POSTGRES_USER" -d postgres \
       -c 'CREATE DATABASE ragp_restore;'
   ```

3. Stream the chosen dump back:

   ```bash
   docker compose -f /opt/rag-p/compose.prod.yml --env-file /opt/rag-p/.env \
       run --rm --entrypoint bash postgres-backup -lc \
       'export AWS_ACCESS_KEY_ID="$RAGP_PGBACKUP_S3_ACCESS_KEY_ID"
        export AWS_SECRET_ACCESS_KEY="$RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY"
        export AWS_DEFAULT_REGION="${RAGP_PGBACKUP_S3_REGION:-ru-1}"
        export AWS_REGION="$AWS_DEFAULT_REGION"
       /usr/local/bin/restore.sh \
       s3://rag-p-pg-backups/pg-backups/postgres-20260430T021500Z.sql.gz \
       ragp_restore'
   ```

4. Verify table counts in `ragp_restore` and either:
   - Promote: stop the API/worker, drop and rename databases, restart.
   - Cherry-pick: dump specific tables out of `ragp_restore` and load
     them into the live DB.

## Monitoring

- `docker compose -f /opt/rag-p/compose.prod.yml logs -f postgres-backup` —
  every cycle logs the timestamp, dump size, S3 key, and prune count.
- `docker compose -f /opt/rag-p/compose.prod.yml ps postgres-backup` —
  `unhealthy` means the S3 ls probe is failing (bad creds, wrong bucket,
  or Selectel outage).
- Selectel console — watch bucket size; with 7-day retention and a
  ~50 MB compressed dump the steady state is ~350 MB.

## Rotating S3 access keys

1. Create a new access key pair in Selectel for the backup service-user.
2. Update `RAGP_PGBACKUP_S3_ACCESS_KEY_ID` and
   `RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY` in `/opt/rag-p/.env`.
3. `docker compose -f /opt/rag-p/compose.prod.yml up -d postgres-backup`
   to recreate the container with new credentials.
4. Confirm the next cycle's log line shows a successful upload, then
   revoke the old key in Selectel.
