"""Summarise locust CSV output into a markdown-friendly report.

Locust's ``--csv=PREFIX`` flag emits four files:

* ``PREFIX_stats.csv``           — per-endpoint counts, RPS, latency averages.
* ``PREFIX_stats_history.csv``   — time-series sampled every 10 s.
* ``PREFIX_failures.csv``        — failure types and counts.
* ``PREFIX_exceptions.csv``      — Python exceptions, if any.

This tool consumes the *_stats.csv files and prints a compact summary suitable
for pasting into ``docs/economics-benchmark-template.md``.

Usage::

    python scripts/bench/analyze_results.py results/query-c10_stats.csv
    python scripts/bench/analyze_results.py results/*.csv

When multiple files are given, one section per file is emitted.

This script uses only stdlib so it can run from any Python 3.11 env without
``locust`` installed.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path
from typing import Any


# Locust 2.x stats.csv columns.  We keep the names hard-coded so a column
# rename surfaces a clean KeyError instead of silent zeroes.
EXPECTED_COLS = {
    "Type",
    "Name",
    "Request Count",
    "Failure Count",
    "Median Response Time",
    "Average Response Time",
    "Min Response Time",
    "Max Response Time",
    "Average Content Size",
    "Requests/s",
    "Failures/s",
    "50%",
    "75%",
    "90%",
    "95%",
    "99%",
}


def _parse_int(value: str) -> int:
    try:
        return int(float(value))
    except ValueError:
        return 0


def _parse_float(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _summarise_file(path: Path) -> str:
    if not path.exists():
        return f"## {path}\n\n_missing file_\n"

    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        cols = set(reader.fieldnames or [])
        missing = EXPECTED_COLS - cols
        if missing:
            return (
                f"## {path}\n\n"
                f"_unexpected schema, missing columns: {sorted(missing)}_\n"
            )
        rows = list(reader)

    lines: list[str] = []
    lines.append(f"## {path}")
    lines.append("")
    lines.append(
        "| Endpoint | N | Fail | RPS | p50 ms | p95 ms | p99 ms | mean ms |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")

    aggregate_row: dict[str, Any] | None = None
    for row in rows:
        if row.get("Name") == "Aggregated":
            aggregate_row = row
            continue
        lines.append(_format_row(row))

    if aggregate_row is not None:
        lines.append("")
        lines.append("**Aggregated:**")
        lines.append(_format_row(aggregate_row))

    # Throughput / error-rate at-a-glance section
    if aggregate_row is not None:
        n = _parse_int(aggregate_row["Request Count"])
        fails = _parse_int(aggregate_row["Failure Count"])
        rps = _parse_float(aggregate_row["Requests/s"])
        err_pct = (fails / n * 100.0) if n else 0.0
        lines.append("")
        lines.append("**Headline:**")
        lines.append(f"- total requests: {n}")
        lines.append(f"- error rate: {err_pct:.2f}%")
        lines.append(f"- avg RPS: {rps:.2f}")
        lines.append(f"- p50: {_parse_float(aggregate_row['50%']):.0f} ms")
        lines.append(f"- p95: {_parse_float(aggregate_row['95%']):.0f} ms")
        lines.append(f"- p99: {_parse_float(aggregate_row['99%']):.0f} ms")
    lines.append("")
    return "\n".join(lines)


def _format_row(row: dict[str, str]) -> str:
    name = row.get("Name", "")
    n = _parse_int(row["Request Count"])
    fails = _parse_int(row["Failure Count"])
    rps = _parse_float(row["Requests/s"])
    p50 = _parse_float(row["50%"])
    p95 = _parse_float(row["95%"])
    p99 = _parse_float(row["99%"])
    mean = _parse_float(row["Average Response Time"])
    return (
        f"| `{name}` | {n} | {fails} | {rps:.2f} "
        f"| {p50:.0f} | {p95:.0f} | {p99:.0f} | {mean:.0f} |"
    )


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    paths = [Path(arg) for arg in argv[1:]]
    out: list[str] = []
    for path in paths:
        out.append(_summarise_file(path))
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
