# Tech debt audit: Compose production coherence

Date: 2026-05-06

Scope: production runtime and deployment documentation for the Docker Compose
target in `/opt/rag-p`.

## Findings

| ID | Area | Finding | Status | Resolution |
| --- | --- | --- | --- | --- |
| RPO-001 | `postgres-backup` runtime | Backup loop slept until the next scheduled slot on container start. Host downtime after a missed slot could silently extend RPO beyond `RAGP_PGBACKUP_INTERVAL_HOURS`. | Fixed | `backup.sh` now checks latest S3 object freshness on startup and before each loop sleep. Empty prefix or age greater than interval plus `RAGP_PGBACKUP_CATCHUP_GRACE_MINUTES` triggers an immediate catch-up backup. |
| DOC-001 | Postgres backup runbook | `aws s3 ls` and restore examples bypassed the backup entrypoint with `--entrypoint bash`, so AWS credentials were not exported from `RAGP_PGBACKUP_*`. | Fixed | Runbook commands now export `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION`, and `AWS_REGION` from `RAGP_PGBACKUP_*` before invoking AWS CLI / `restore.sh`. |
| CD-001 | `deploy-compose` workflow | `workflow_run` deployed after any successful `CI` run on `main`, even when `DEPLOY_TARGET` was not `compose`. | Fixed | Job condition now gates automatic `workflow_run` deploys on `vars.DEPLOY_TARGET == 'compose'`. Manual `workflow_dispatch` remains available regardless of target. |
| SMTP-001 | Compose SMTP healthcheck | `nc -z localhost 587` opened and reset TCP every 30 seconds, causing noisy maddy reset logs. | Fixed | Healthcheck now performs a tiny SMTP dialogue (`EHLO`, `QUIT`) and verifies the `220` banner, closing gracefully. |

## Deferred

| ID | Area | Reason |
| --- | --- | --- |
| E2E-001 | Local Docker validation | Docker may be unavailable on developer workstations. Compose syntax and shell syntax are validated locally when tooling exists; production smoke remains the deployment workflow's responsibility. |
