#!/usr/bin/env bash
# snapshot_resources.sh — sample docker compose stats + Postgres pg_stat_activity
#
# Usage:
#   RAGP_BENCH_HOST=user@gemcraft \
#   RAGP_BENCH_INTERVAL=10 \
#   RAGP_BENCH_DURATION=600 \
#   RAGP_BENCH_OUT=results/resources \
#   bash scripts/bench/snapshot_resources.sh
#
# The script:
#   * SSHes into the host (assumes the gemcraft-claude key is loaded into
#     ssh-agent, or use ~/.ssh/config aliasing);
#   * captures `docker stats --no-stream` and `pg_stat_activity` once per
#     interval, appended to CSV files under $RAGP_BENCH_OUT;
#   * stops automatically after $RAGP_BENCH_DURATION seconds.
#
# It is intentionally append-only and never restarts services.  Run it in a
# tmux pane in parallel with `locust --headless`.

set -euo pipefail

HOST="${RAGP_BENCH_HOST:?RAGP_BENCH_HOST not set, e.g. user@gemcraft}"
INTERVAL="${RAGP_BENCH_INTERVAL:-10}"
DURATION="${RAGP_BENCH_DURATION:-600}"
OUTDIR="${RAGP_BENCH_OUT:-results/resources}"
COMPOSE_DIR="${RAGP_BENCH_COMPOSE_DIR:-/opt/rag-p/deploy/compose}"
COMPOSE_FILE="${RAGP_BENCH_COMPOSE_FILE:-compose.prod.yml}"
PG_CONTAINER="${RAGP_BENCH_PG_CONTAINER:-postgres}"
PG_USER="${RAGP_BENCH_PG_USER:-ragp}"
PG_DB="${RAGP_BENCH_PG_DB:-ragp}"

mkdir -p "$OUTDIR"

DOCKER_CSV="$OUTDIR/docker_stats.csv"
PG_CSV="$OUTDIR/pg_stat_activity.csv"

if [[ ! -f "$DOCKER_CSV" ]]; then
    printf 'ts,name,cpu_pct,mem_usage,mem_pct,net_io,block_io,pids\n' > "$DOCKER_CSV"
fi
if [[ ! -f "$PG_CSV" ]]; then
    printf 'ts,active,idle,idle_in_tx,waiting\n' > "$PG_CSV"
fi

# shellcheck disable=SC2029  -- we want $COMPOSE_FILE expanded locally for clarity
remote_docker_stats() {
    ssh -o BatchMode=yes "$HOST" \
        "cd '$COMPOSE_DIR' && docker compose -f '$COMPOSE_FILE' ps --format '{{.Service}}' | xargs -I {} docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemUsage}},{{.MemPerc}},{{.NetIO}},{{.BlockIO}},{{.PIDs}}' {} 2>/dev/null"
}

remote_pg_stats() {
    # Returns one CSV line: active,idle,idle_in_tx,waiting
    ssh -o BatchMode=yes "$HOST" \
        "docker exec $PG_CONTAINER psql -U '$PG_USER' -d '$PG_DB' -tAc \"SELECT count(*) FILTER (WHERE state='active'), count(*) FILTER (WHERE state='idle'), count(*) FILTER (WHERE state='idle in transaction'), count(*) FILTER (WHERE wait_event IS NOT NULL) FROM pg_stat_activity WHERE datname='$PG_DB';\" | tr '|' ','"
}

start_ts=$(date +%s)
end_ts=$((start_ts + DURATION))

echo "[snapshot] host=$HOST interval=${INTERVAL}s duration=${DURATION}s out=$OUTDIR"

while [[ $(date +%s) -lt $end_ts ]]; do
    ts=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    if docker_lines=$(remote_docker_stats); then
        while IFS= read -r line; do
            [[ -z "$line" ]] && continue
            # Quote fields that contain commas (mem_usage="5.2MiB / 1.0GiB").
            # We let the line have commas inside the original docker columns:
            # docker --format already separates them with commas, so we wrap
            # the whole line behind ts into quotes per CSV friendly.
            printf '%s,"%s"\n' "$ts" "$line" >> "$DOCKER_CSV"
        done <<< "$docker_lines"
    else
        echo "[snapshot] WARN docker stats failed at $ts" >&2
    fi

    if pg_line=$(remote_pg_stats); then
        pg_line=$(echo "$pg_line" | tr -d ' ')
        printf '%s,%s\n' "$ts" "$pg_line" >> "$PG_CSV"
    else
        echo "[snapshot] WARN pg_stat_activity failed at $ts" >&2
    fi

    sleep "$INTERVAL"
done

echo "[snapshot] done.  CSVs:"
echo "  $DOCKER_CSV"
echo "  $PG_CSV"
