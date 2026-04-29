"""Ingest capacity scenario.

Measures throughput of ``POST /api/v1/datasets/{id}/documents`` —
the endpoint that performs upload -> parse -> chunk -> embed in one shot.

The scenario is intentionally narrow: each virtual user uploads files from
the bundled corpus in a loop against a single, pre-seeded dataset.  Concurrent
users translate directly into concurrent embedding jobs which is exactly what
we want to stress.

Required env (see scripts/bench/README.md):

* ``RAGP_BENCH_BASE_URL``        — e.g. ``https://api.lekottt.ru``
* ``RAGP_BENCH_SESSION_COOKIE``  — value of the ``ragp_session`` cookie for the
  benchmark account.  Document upload is session-authenticated, not API-key.
* ``RAGP_BENCH_DATASET_ID``      — UUID of the dataset to upload into.

Optional:

* ``RAGP_BENCH_CHUNKER`` (default ``recursive-character``)
* ``RAGP_BENCH_CHUNKER_PARAMS`` (JSON string, default ``{}``)

Run example::

    locust -f scripts/bench/locustfile_ingest.py \\
           --users 5 --spawn-rate 1 --run-time 5m \\
           --host "$RAGP_BENCH_BASE_URL" \\
           --csv=results/ingest --headless
"""

from __future__ import annotations

import random
import uuid
from typing import Any

from locust import HttpUser, between, events, task

from scripts.bench._common import (  # noqa: E402  -- locust loads as script
    env_optional,
    env_required,
    load_corpus,
)


# ---------------------------------------------------------------------------
# Module-level config — captured once at import time so locust workers reuse it.
# ---------------------------------------------------------------------------

_BASE_URL = env_required("RAGP_BENCH_BASE_URL")
_SESSION_COOKIE = env_required("RAGP_BENCH_SESSION_COOKIE")
_DATASET_ID = env_required("RAGP_BENCH_DATASET_ID")
_CHUNKER = env_optional("RAGP_BENCH_CHUNKER", "recursive-character")
_CHUNKER_PARAMS = env_optional("RAGP_BENCH_CHUNKER_PARAMS", "{}")

_CORPUS = load_corpus()


@events.init_command_line_parser.add_listener
def _on_parser(parser: Any) -> None:
    """Document the env contract in ``--help`` output."""
    parser.add_argument(
        "--bench-note",
        default="ingest",
        help="Free-form tag persisted to the locust CSV name (informational).",
    )


class IngestUser(HttpUser):
    """One virtual user uploading documents in a tight loop."""

    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        # Each user gets its own RNG so distribution across files is stable.
        self._rng = random.Random()
        # Pre-build a session-authenticated cookie jar for httpx/requests.
        self.client.cookies.set("ragp_session", _SESSION_COOKIE)

    @task
    def upload_document(self) -> None:
        filename, payload = self._rng.choice(_CORPUS)
        # Add a uuid suffix so the server does not reject as duplicate sha if it
        # decides to dedupe in the future, and so audit logs are easy to read.
        unique_name = f"bench-{uuid.uuid4().hex[:8]}-{filename}"

        files = {
            "file": (unique_name, payload, "text/plain"),
        }
        data = {
            "chunker_name": _CHUNKER,
            "chunker_params": _CHUNKER_PARAMS,
        }

        # Use absolute path; locust prefixes ``--host`` automatically.
        with self.client.post(
            f"/api/v1/datasets/{_DATASET_ID}/documents",
            files=files,
            data=data,
            name="POST /datasets/{id}/documents",
            catch_response=True,
        ) as response:
            if response.status_code in (200, 201):
                response.success()
            elif response.status_code == 402:
                response.failure(
                    "402 Payment Required — bench account has no active plan or "
                    "storage quota exhausted; re-run seed_dataset.py."
                )
            elif response.status_code == 401:
                response.failure(
                    "401 Unauthorized — session cookie expired; refresh "
                    "RAGP_BENCH_SESSION_COOKIE."
                )
            else:
                response.failure(
                    f"unexpected status {response.status_code}: {response.text[:200]}"
                )
