"""Experiment throughput scenario.

Measures end-to-end duration of an ``Experiment`` run for a configurable grid
size.  Each virtual user creates one experiment, polls until it completes,
records the duration, then starts a new one.

Locust's request-time histogram is therefore the *experiment* completion-time
distribution, not HTTP latency.  Throughput in the CSV equals "experiments
finished per second" multiplied by combinations-per-experiment to derive
combos/min.

Required env:

* ``RAGP_BENCH_BASE_URL``        — e.g. ``https://api.lekottt.ru``
* ``RAGP_BENCH_SESSION_COOKIE``  — session cookie (experiments are
  session-authenticated, not API-key).
* ``RAGP_BENCH_DATASET_ID``      — UUID of seeded dataset with golden Q&A.
* ``RAGP_BENCH_ORG_ID``          — organisation UUID owning the dataset.

Optional:

* ``RAGP_BENCH_GRID_SIZE``  — ``small`` (1×1×1=1 combo, default), ``medium``
  (2×2×1=4), or ``large`` (3×2×2=12).
* ``RAGP_BENCH_POLL_INTERVAL_SEC`` — poll cadence, default 5.
* ``RAGP_BENCH_POLL_TIMEOUT_SEC`` — abort if not done, default 1800 (30 min).

Run example (3 users, 1-hour soak, medium grid)::

    RAGP_BENCH_GRID_SIZE=medium \\
    locust -f scripts/bench/locustfile_experiment.py \\
           --users 3 --spawn-rate 1 --run-time 1h \\
           --host "$RAGP_BENCH_BASE_URL" \\
           --csv=results/exp-medium --headless
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from locust import HttpUser, between, events, task

from scripts.bench._common import (
    env_optional,
    env_required,
)


_BASE_URL = env_required("RAGP_BENCH_BASE_URL")
_SESSION_COOKIE = env_required("RAGP_BENCH_SESSION_COOKIE")
_DATASET_ID = env_required("RAGP_BENCH_DATASET_ID")
_ORG_ID = env_required("RAGP_BENCH_ORG_ID")
_GRID_SIZE = env_optional("RAGP_BENCH_GRID_SIZE", "small")
_POLL_INTERVAL = float(env_optional("RAGP_BENCH_POLL_INTERVAL_SEC", "5"))
_POLL_TIMEOUT = float(env_optional("RAGP_BENCH_POLL_TIMEOUT_SEC", "1800"))


# Grid presets.  Combinations are cartesian product of the slot lists.
# Keep these conservative — the goal is to measure throughput, not stress the
# scorer with novel models.

_GRIDS: dict[str, dict[str, list[dict[str, Any]]]] = {
    "small": {
        "chunkers": [
            {"plugin_kind": "chunker", "plugin_name": "recursive-character", "params": {}},
        ],
        "retrievers": [
            {"plugin_kind": "retriever", "plugin_name": "pgvector-hybrid", "params": {}},
        ],
        "generators": [
            {
                "plugin_kind": "generator",
                "plugin_name": "litellm-generator",
                "params": {"model": "openai/gpt-4o-mini"},
            },
        ],
    },
    "medium": {
        "chunkers": [
            {
                "plugin_kind": "chunker",
                "plugin_name": "recursive-character",
                "params": {"chunk_size": 512},
            },
            {
                "plugin_kind": "chunker",
                "plugin_name": "recursive-character",
                "params": {"chunk_size": 1024},
            },
        ],
        "retrievers": [
            {
                "plugin_kind": "retriever",
                "plugin_name": "pgvector-hybrid",
                "params": {"top_k": 5},
            },
            {
                "plugin_kind": "retriever",
                "plugin_name": "pgvector-hybrid",
                "params": {"top_k": 10},
            },
        ],
        "generators": [
            {
                "plugin_kind": "generator",
                "plugin_name": "litellm-generator",
                "params": {"model": "openai/gpt-4o-mini"},
            },
        ],
    },
    "large": {
        "chunkers": [
            {
                "plugin_kind": "chunker",
                "plugin_name": "recursive-character",
                "params": {"chunk_size": 256},
            },
            {
                "plugin_kind": "chunker",
                "plugin_name": "recursive-character",
                "params": {"chunk_size": 512},
            },
            {
                "plugin_kind": "chunker",
                "plugin_name": "recursive-character",
                "params": {"chunk_size": 1024},
            },
        ],
        "retrievers": [
            {
                "plugin_kind": "retriever",
                "plugin_name": "pgvector-hybrid",
                "params": {"top_k": 5},
            },
            {
                "plugin_kind": "retriever",
                "plugin_name": "pgvector-hybrid",
                "params": {"top_k": 10},
            },
        ],
        "generators": [
            {
                "plugin_kind": "generator",
                "plugin_name": "litellm-generator",
                "params": {"model": "openai/gpt-4o-mini"},
            },
            {
                "plugin_kind": "generator",
                "plugin_name": "litellm-generator",
                "params": {"model": "openai/gpt-4o"},
            },
        ],
    },
}

if _GRID_SIZE not in _GRIDS:
    raise RuntimeError(
        f"Unknown RAGP_BENCH_GRID_SIZE={_GRID_SIZE!r}. "
        f"Choose one of: {sorted(_GRIDS)}."
    )

_PLUGIN_GRID = _GRIDS[_GRID_SIZE]


def _combo_count(grid: dict[str, list[dict[str, Any]]]) -> int:
    n = 1
    for variants in grid.values():
        n *= len(variants)
    return n


_COMBO_COUNT = _combo_count(_PLUGIN_GRID)


@events.init_command_line_parser.add_listener
def _on_parser(parser: Any) -> None:
    parser.add_argument(
        "--bench-note",
        default=f"experiment-{_GRID_SIZE}",
        help="Free-form tag (informational).",
    )


class ExperimentUser(HttpUser):
    """One virtual user that creates and waits for experiments serially."""

    # No wait_time: the polling loop already paces requests.
    wait_time = between(0.0, 0.0)

    def on_start(self) -> None:
        self.client.cookies.set("ragp_session", _SESSION_COOKIE)
        self.client.headers["Content-Type"] = "application/json"

    @task
    def run_experiment(self) -> None:
        name = f"bench-{_GRID_SIZE}-{uuid.uuid4().hex[:8]}"
        body = {
            "name": name,
            "organization_id": _ORG_ID,
            "dataset_id": _DATASET_ID,
            "plugin_grid": _PLUGIN_GRID,
        }

        start = time.monotonic()

        with self.client.post(
            "/api/v1/experiments",
            json=body,
            name="POST /experiments (create)",
            catch_response=True,
        ) as create_resp:
            if create_resp.status_code != 201:
                create_resp.failure(
                    f"create failed: {create_resp.status_code} "
                    f"{create_resp.text[:200]}"
                )
                return
            experiment_id = create_resp.json()["id"]
            create_resp.success()

        # Poll until terminal status.  We report the *total* time as a single
        # synthetic request entry so locust's percentile maths work directly.
        deadline = start + _POLL_TIMEOUT
        terminal = {"completed", "failed", "error", "cancelled"}
        final_status = "unknown"
        while time.monotonic() < deadline:
            with self.client.get(
                f"/api/v1/experiments/{experiment_id}",
                name="GET /experiments/{id} (poll)",
                catch_response=True,
            ) as poll_resp:
                if poll_resp.status_code != 200:
                    poll_resp.failure(
                        f"poll failed: {poll_resp.status_code}"
                    )
                    return
                poll_resp.success()
                status = poll_resp.json().get("status", "")
                if status in terminal:
                    final_status = status
                    break
            time.sleep(_POLL_INTERVAL)
        else:
            self._fire_synthetic(
                name=f"experiment-{_GRID_SIZE}-timeout",
                duration_ms=int((time.monotonic() - start) * 1000),
                exception=RuntimeError("poll timeout"),
            )
            return

        duration_ms = int((time.monotonic() - start) * 1000)
        # Per-combo throughput proxy: emit one synthetic event per combination
        # so locust's RPS column on the experiment endpoint approximates
        # combos/sec.
        for _ in range(_COMBO_COUNT):
            self._fire_synthetic(
                name=f"experiment-{_GRID_SIZE}-combo",
                duration_ms=duration_ms // max(_COMBO_COUNT, 1),
                exception=None if final_status == "completed" else RuntimeError(final_status),
            )

    def _fire_synthetic(
        self,
        *,
        name: str,
        duration_ms: int,
        exception: BaseException | None,
    ) -> None:
        from locust import events as _events  # local import to avoid cycle

        _events.request.fire(
            request_type="EXPERIMENT",
            name=name,
            response_time=duration_ms,
            response_length=0,
            exception=exception,
            context={},
        )
