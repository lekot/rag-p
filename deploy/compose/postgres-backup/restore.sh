#!/usr/bin/env bash
# Restore a pg_dump backup from S3 into a target database.
#
# Usage:
#   restore.sh <s3-uri> <target-db>
#
# Example:
#   restore.sh s3://rag-p-pg-backups/pg-backups/postgres-20260430T021500Z.sql.gz ragp_restore
#
# Required env:
#   POSTGRES_HOST, POSTGRES_USER, POSTGRES_PASSWORD
#   RAGP_PGBACKUP_S3_ENDPOINT_URL
#   RAGP_PGBACKUP_S3_ACCESS_KEY_ID
#   RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY
#
# Notes:
#   - The target DB must already exist; this script does NOT create or drop it.
#     Create it manually first:
#       psql -h $POSTGRES_HOST -U $POSTGRES_USER -d postgres \
#            -c "CREATE DATABASE ragp_restore;"
#   - Restoring into a non-empty DB will overlay objects; for a clean restore
#     drop+recreate the DB first.

set -euo pipefail

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

err() {
    log "ERROR: $*" >&2
}

if [[ $# -ne 2 ]]; then
    err "usage: $0 <s3-uri> <target-db>"
    exit 2
fi

S3_URI="$1"
TARGET_DB="$2"

if [[ "$S3_URI" != s3://* ]]; then
    err "expected s3:// URI, got: $S3_URI"
    exit 2
fi

require_env() {
    local name="$1"
    local value="${!name:-}"
    if [[ -z "$value" ]]; then
        err "missing required env $name"
        exit 2
    fi
}

require_env POSTGRES_HOST
require_env POSTGRES_USER
require_env POSTGRES_PASSWORD
require_env RAGP_PGBACKUP_S3_ENDPOINT_URL
require_env RAGP_PGBACKUP_S3_ACCESS_KEY_ID
require_env RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY

S3_REGION="${RAGP_PGBACKUP_S3_REGION:-ru-1}"
ENDPOINT="$RAGP_PGBACKUP_S3_ENDPOINT_URL"

export AWS_ACCESS_KEY_ID="$RAGP_PGBACKUP_S3_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="$S3_REGION"
export AWS_REGION="$S3_REGION"
export PGPASSWORD="$POSTGRES_PASSWORD"

log "restoring ${S3_URI} → ${POSTGRES_HOST}/${TARGET_DB}"

# Stream: aws s3 cp to stdout → gunzip → psql.
# `psql -v ON_ERROR_STOP=1` aborts on the first SQL error so failures bubble up.
if ! aws --endpoint-url "$ENDPOINT" --no-progress s3 cp "$S3_URI" - \
    | gunzip \
    | psql \
        --host="$POSTGRES_HOST" \
        --username="$POSTGRES_USER" \
        --dbname="$TARGET_DB" \
        --set=ON_ERROR_STOP=1 \
        --quiet
then
    err "restore failed"
    exit 1
fi

log "restore complete: ${TARGET_DB}"
