"""Query latency scenario.

Stresses ``POST /api/v1/rag/query`` to measure p50/p95/p99 latency under
concurrent load.  The dataset MUST be pre-seeded (see ``seed_dataset.py``)
because cold-cache embeds would dominate the measurement.

Required env:

* ``RAGP_BENCH_BASE_URL``     — e.g. ``https://api.lekottt.ru``
* ``RAGP_BENCH_API_KEY``      — public API key (``rgp_...``).
* ``RAGP_BENCH_DATASET_ID``   — UUID of the seeded dataset.

Optional:

* ``RAGP_BENCH_PIPELINE_ID``  — if set, queries go through a specific
  pipeline; otherwise the default RAG path is used.
* ``RAGP_BENCH_QUERY_FILE``   — path to a newline-delimited file of queries.
  When unset, the built-in mix from ``_common.DEFAULT_QUERY_MIX`` is used.

Run example (10 concurrent users for 5 minutes)::

    locust -f scripts/bench/locustfile_query.py \\
           --users 10 --spawn-rate 1 --run-time 5m \\
           --host "$RAGP_BENCH_BASE_URL" \\
           --csv=results/query-c10 --headless

For p50/p95/p99 sweep, run separately with ``--users 1 / 5 / 10 / 50``.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from locust import HttpUser, between, events, task

from scripts.bench._common import (
    DEFAULT_QUERY_MIX,
    api_key_headers,
    env_optional,
    env_required,
    random_top_k,
)


_BASE_URL = env_required("RAGP_BENCH_BASE_URL")
_API_KEY = env_required("RAGP_BENCH_API_KEY")
_DATASET_ID = env_required("RAGP_BENCH_DATASET_ID")
_PIPELINE_ID = env_optional("RAGP_BENCH_PIPELINE_ID", "")
_QUERY_FILE = env_optional("RAGP_BENCH_QUERY_FILE", "")


def _load_queries() -> tuple[str, ...]:
    if _QUERY_FILE:
        path = Path(_QUERY_FILE)
        if not path.exists():
            raise RuntimeError(f"RAGP_BENCH_QUERY_FILE not found: {path}")
        lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
        return tuple(line for line in lines if line)
    return DEFAULT_QUERY_MIX


_QUERIES = _load_queries()


@events.init_command_line_parser.add_listener
def _on_parser(parser: Any) -> None:
    parser.add_argument(
        "--bench-note",
        default="query",
        help="Free-form tag persisted to the locust CSV name (informational).",
    )


class QueryUser(HttpUser):
    """One virtual user issuing /rag/query in a tight loop."""

    # Realistic think-time: 0.5–2 s between requests so bursts don't queue
    # synthetically.  Use ``--users`` to control concurrency, not wait_time.
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        self._rng = random.Random()
        self.client.headers.update(api_key_headers(_API_KEY))

    @task
    def rag_query(self) -> None:
        body: dict[str, Any] = {
            "dataset_id": _DATASET_ID,
            "query": self._rng.choice(_QUERIES),
            "top_k": random_top_k(self._rng),
        }
        if _PIPELINE_ID:
            body["pipeline_id"] = _PIPELINE_ID

        with self.client.post(
            "/api/v1/rag/query",
            json=body,
            name="POST /rag/query",
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                # Optional sanity: the body must parse and contain non-empty answer.
                try:
                    payload = response.json()
                except ValueError:
                    response.failure("non-JSON 200 response")
                    return
                if not payload.get("answer"):
                    response.failure("200 with empty answer field")
                else:
                    response.success()
            elif response.status_code == 429:
                response.failure(
                    "429 rate-limited — increase plan limit or reduce --users"
                )
            elif response.status_code == 402:
                response.failure(
                    "402 Payment Required — bench account out of quota"
                )
            elif response.status_code == 401:
                response.failure(
                    "401 Unauthorized — RAGP_BENCH_API_KEY is invalid"
                )
            else:
                response.failure(
                    f"unexpected status {response.status_code}: {response.text[:200]}"
                )
