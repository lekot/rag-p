#!/usr/bin/env bash
# Daily pg_dump → S3 (Selectel) backup runner.
#
# Modes:
#   backup.sh          — same as `loop` (Dockerfile CMD default).
#   backup.sh loop     — sleep until next scheduled slot, take backup, repeat.
#   backup.sh once     — take a single backup and exit (used for ad-hoc runs).
#
# Required env:
#   POSTGRES_HOST, POSTGRES_USER, POSTGRES_DB, POSTGRES_PASSWORD
#   RAGP_PGBACKUP_S3_ENDPOINT_URL
#   RAGP_PGBACKUP_S3_BUCKET
#   RAGP_PGBACKUP_S3_ACCESS_KEY_ID
#   RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY
#
# Optional env (with defaults):
#   RAGP_PGBACKUP_PREFIX=pg-backups/
#   RAGP_PGBACKUP_HOUR_UTC=2
#   RAGP_PGBACKUP_MINUTE=15
#   RAGP_PGBACKUP_INTERVAL_HOURS=24
#   RAGP_PGBACKUP_CATCHUP_GRACE_MINUTES=60
#   RAGP_PGBACKUP_RETENTION_DAYS=7
#   RAGP_PGBACKUP_S3_REGION=ru-1

set -euo pipefail

MODE="${1:-loop}"

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"
}

err() {
    log "ERROR: $*" >&2
}

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
require_env POSTGRES_DB
require_env POSTGRES_PASSWORD

# S3 destination is optional in `loop` mode: if any required S3 env is missing
# we don't crash-loop the container — just warn and sleep forever.  This keeps
# `docker compose up` healthy when the operator hasn't yet provisioned a
# backup bucket (still a `pending manual step` in docs/backlog.md).  In `once`
# mode we keep the strict behaviour so CI / manual runs surface the gap.
S3_OPTIONAL_VARS=(
    RAGP_PGBACKUP_S3_ENDPOINT_URL
    RAGP_PGBACKUP_S3_BUCKET
    RAGP_PGBACKUP_S3_ACCESS_KEY_ID
    RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY
)
S3_DISABLED=0
for v in "${S3_OPTIONAL_VARS[@]}"; do
    if [[ -z "${!v:-}" ]]; then
        S3_DISABLED=1
        break
    fi
done

if [[ "$S3_DISABLED" == "1" ]]; then
    if [[ "$MODE" == "once" ]]; then
        # In once mode keep strict behaviour so CI / ad-hoc runs surface the gap.
        for v in "${S3_OPTIONAL_VARS[@]}"; do
            require_env "$v"
        done
    else
        log "WARNING: S3 destination not fully configured — backup loop disabled."
        log "         set RAGP_PGBACKUP_S3_{ENDPOINT_URL,BUCKET,ACCESS_KEY_ID,SECRET_ACCESS_KEY}"
        log "         on the compose host to enable scheduled backups."
        # Sleep in a tight wakeup-able loop so docker stop is responsive.
        while true; do
            sleep 3600
        done
    fi
fi

PREFIX="${RAGP_PGBACKUP_PREFIX:-pg-backups/}"
# Normalise: strip leading slash, ensure trailing slash so concat is predictable.
PREFIX="${PREFIX#/}"
case "$PREFIX" in
    */) : ;;
    "") PREFIX="" ;;
    *)  PREFIX="${PREFIX}/" ;;
esac

HOUR_UTC="${RAGP_PGBACKUP_HOUR_UTC:-2}"
MINUTE="${RAGP_PGBACKUP_MINUTE:-15}"
INTERVAL_HOURS="${RAGP_PGBACKUP_INTERVAL_HOURS:-24}"
CATCHUP_GRACE_MINUTES="${RAGP_PGBACKUP_CATCHUP_GRACE_MINUTES:-60}"
RETENTION_DAYS="${RAGP_PGBACKUP_RETENTION_DAYS:-7}"
S3_REGION="${RAGP_PGBACKUP_S3_REGION:-ru-1}"

BUCKET="$RAGP_PGBACKUP_S3_BUCKET"
ENDPOINT="$RAGP_PGBACKUP_S3_ENDPOINT_URL"

# Export so child aws/pg_dump processes inherit credentials.
export AWS_ACCESS_KEY_ID="$RAGP_PGBACKUP_S3_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$RAGP_PGBACKUP_S3_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="$S3_REGION"
export AWS_REGION="$S3_REGION"
export PGPASSWORD="$POSTGRES_PASSWORD"

aws_s3() {
    aws --endpoint-url "$ENDPOINT" --no-progress "$@"
}

aws_s3api() {
    aws --endpoint-url "$ENDPOINT" s3api "$@"
}

run_backup() {
    local stamp object key tmp size
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"
    object="postgres-${stamp}.sql.gz"
    key="${PREFIX}${object}"
    tmp="$(mktemp -t pg_dump.XXXXXX.sql.gz)"
    # shellcheck disable=SC2064
    trap "rm -f '$tmp'" RETURN

    log "starting pg_dump host=$POSTGRES_HOST db=$POSTGRES_DB → s3://$BUCKET/$key"

    # pg_dump → gzip into a temp file first; uploading from a regular file
    # gives us an exact size for logging and avoids streaming-failure modes
    # where partial uploads silently win.
    if ! pg_dump \
            --host="$POSTGRES_HOST" \
            --username="$POSTGRES_USER" \
            --dbname="$POSTGRES_DB" \
            --format=plain \
            --no-owner \
            --no-privileges \
        | gzip -9 > "$tmp"
    then
        err "pg_dump failed"
        return 1
    fi

    size="$(stat -c %s "$tmp" 2>/dev/null || wc -c < "$tmp")"
    log "pg_dump produced ${size} bytes (gzipped)"

    if ! aws_s3 s3 cp "$tmp" "s3://${BUCKET}/${key}"; then
        err "aws s3 cp failed"
        return 1
    fi

    log "uploaded s3://${BUCKET}/${key} (${size} bytes)"
    return 0
}

prune_old_backups() {
    local cutoff list keys deleted=0
    # ISO-8601 cutoff in UTC. aws s3api compares LastModified as ISO strings.
    cutoff="$(date -u -d "${RETENTION_DAYS} days ago" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null \
        || date -u -v-"${RETENTION_DAYS}"d +%Y-%m-%dT%H:%M:%SZ)"

    log "pruning objects under s3://${BUCKET}/${PREFIX} older than ${cutoff}"

    if ! list="$(aws_s3api list-objects-v2 \
            --bucket "$BUCKET" \
            --prefix "$PREFIX" \
            --output json 2>/dev/null)"
    then
        err "list-objects-v2 failed; skipping prune (will retry next cycle)"
        return 0
    fi

    # Empty bucket / prefix → nothing to do, NOT an error (initial state).
    if [[ -z "$list" ]] || [[ "$(echo "$list" | jq -r '.Contents // [] | length')" == "0" ]]; then
        log "no objects under prefix; nothing to prune"
        return 0
    fi

    keys="$(echo "$list" \
        | jq -r --arg cutoff "$cutoff" \
            '.Contents[] | select(.LastModified < $cutoff) | .Key')"

    if [[ -z "$keys" ]]; then
        log "no objects older than retention window"
        return 0
    fi

    while IFS= read -r key; do
        [[ -z "$key" ]] && continue
        if aws_s3 s3 rm "s3://${BUCKET}/${key}"; then
            log "deleted s3://${BUCKET}/${key}"
            deleted=$((deleted + 1))
        else
            err "failed to delete s3://${BUCKET}/${key}"
        fi
    done <<< "$keys"

    log "pruned ${deleted} object(s)"
}

iso_to_epoch() {
    local iso="$1"
    date -u -d "$iso" +%s 2>/dev/null \
        || date -u -j -f "%Y-%m-%dT%H:%M:%SZ" "${iso%+00:00}Z" +%s
}

latest_backup_epoch() {
    local list latest_iso
    if ! list="$(aws_s3api list-objects-v2 \
            --bucket "$BUCKET" \
            --prefix "$PREFIX" \
            --output json 2>/dev/null)"
    then
        err "list-objects-v2 failed; skipping catch-up freshness check"
        return 1
    fi

    if ! latest_iso="$(echo "$list" \
        | jq -r '(.Contents // []) | if length == 0 then empty else max_by(.LastModified).LastModified end')"
    then
        err "failed to parse list-objects-v2 response; skipping catch-up freshness check"
        return 1
    fi

    if [[ -z "$latest_iso" ]]; then
        echo 0
        return 0
    fi

    iso_to_epoch "$latest_iso"
}

backup_is_stale() {
    local latest_epoch now_epoch max_age_seconds age_seconds
    if ! latest_epoch="$(latest_backup_epoch)"; then
        return 2
    fi

    now_epoch="$(date -u +%s)"
    max_age_seconds=$(( INTERVAL_HOURS * 3600 + CATCHUP_GRACE_MINUTES * 60 ))

    if (( latest_epoch == 0 )); then
        log "no backup objects found under s3://${BUCKET}/${PREFIX}; catch-up backup is due"
        return 0
    fi

    age_seconds=$(( now_epoch - latest_epoch ))
    if (( age_seconds > max_age_seconds )); then
        log "latest backup is ${age_seconds}s old (threshold ${max_age_seconds}s); catch-up backup is due"
        return 0
    fi

    log "latest backup age ${age_seconds}s is within threshold ${max_age_seconds}s"
    return 1
}

run_catchup_if_needed() {
    local stale_status
    set +e
    backup_is_stale
    stale_status=$?
    set -e

    case "$stale_status" in
        0)
            log "running catch-up backup before scheduled sleep"
            if ! run_once; then
                err "catch-up backup failed; continuing loop"
            fi
            ;;
        1)
            log "catch-up backup not needed"
            ;;
        *)
            err "catch-up freshness check failed; continuing to scheduled sleep"
            ;;
    esac
}

# Compute seconds until the next HOUR_UTC:MINUTE slot, stepped by INTERVAL_HOURS.
seconds_until_next_run() {
    local now next_ts now_ts
    now="$(date -u +%s)"
    now_ts="$now"
    # Today's target time in UTC.
    next_ts="$(date -u -d "today ${HOUR_UTC}:${MINUTE}:00" +%s 2>/dev/null \
        || date -u -j -f "%Y-%m-%d %H:%M:%S" "$(date -u +%Y-%m-%d) ${HOUR_UTC}:${MINUTE}:00" +%s)"
    while (( next_ts <= now_ts )); do
        next_ts=$(( next_ts + INTERVAL_HOURS * 3600 ))
    done
    echo $(( next_ts - now_ts ))
}

run_once() {
    if run_backup; then
        prune_old_backups
        return 0
    else
        return 1
    fi
}

case "$MODE" in
    once)
        log "mode=once"
        run_once
        ;;
    loop)
        log "mode=loop hour_utc=${HOUR_UTC} minute=${MINUTE} interval_hours=${INTERVAL_HOURS} catchup_grace_minutes=${CATCHUP_GRACE_MINUTES} retention_days=${RETENTION_DAYS}"
        while true; do
            run_catchup_if_needed
            sleep_for="$(seconds_until_next_run)"
            log "sleeping ${sleep_for}s until next backup slot"
            sleep "$sleep_for"
            # Best effort: if a single cycle fails we log and continue;
            # the container's healthcheck handles longer-running degradation.
            if ! run_once; then
                err "backup cycle failed; continuing loop"
            fi
        done
        ;;
    *)
        err "unknown mode '$MODE' (expected 'loop' or 'once')"
        exit 2
        ;;
esac
