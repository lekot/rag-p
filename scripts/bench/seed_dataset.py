"""Seed a benchmark organisation, dataset, corpus and golden Q&A.

Run this ONCE before any locust scenario.  It is idempotent on dataset name —
re-running will create a fresh dataset under the same org without disturbing
old ones.

Outputs (printed and dumped to ``scripts/bench/.bench-env``)::

    RAGP_BENCH_BASE_URL=...
    RAGP_BENCH_SESSION_COOKIE=...
    RAGP_BENCH_API_KEY=...
    RAGP_BENCH_ORG_ID=...
    RAGP_BENCH_DATASET_ID=...

Source these into the locust shells:

    set -a; . scripts/bench/.bench-env; set +a

Required env on the *seed* run:

* ``RAGP_BENCH_BASE_URL``       — e.g. ``https://api.lekottt.ru``
* ``RAGP_BENCH_EMAIL``          — e.g. ``bench+$(date +%s)@lekottt.ru``
* ``RAGP_BENCH_PASSWORD``       — strong password
* ``RAGP_BENCH_ORG_NAME``       — display name, e.g. ``BenchOrg``

Optional:

* ``RAGP_BENCH_REUSE_EMAIL=1`` — log in instead of signing up.
* ``RAGP_BENCH_DATASET_NAME``  — defaults to ``bench-<timestamp>``.
* ``RAGP_BENCH_GOLDEN_COUNT``  — number of golden Q&A pairs (default 5).
* ``RAGP_BENCH_PLAN_ID``       — if set, the script attempts to start a
  subscription via direct DB seed instructions (printed, not executed).

The script never enables YooKassa payments.  Activating a paid plan on the
target environment is a manual step described in the runbook.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

CORPUS_DIR = Path(__file__).parent / "sample_docs"
ENV_FILE = Path(__file__).parent / ".bench-env"


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"missing env: {name}")
    return value


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


def _post(client: httpx.Client, path: str, **kwargs: Any) -> httpx.Response:
    resp = client.post(path, **kwargs)
    if resp.status_code >= 400:
        sys.exit(
            f"POST {path} failed: HTTP {resp.status_code}\n{resp.text[:500]}"
        )
    return resp


def main() -> int:
    base_url = _require("RAGP_BENCH_BASE_URL").rstrip("/")
    email = _require("RAGP_BENCH_EMAIL")
    password = _require("RAGP_BENCH_PASSWORD")
    org_name = _require("RAGP_BENCH_ORG_NAME")
    dataset_name = _optional("RAGP_BENCH_DATASET_NAME", f"bench-{int(time.time())}")
    reuse = _optional("RAGP_BENCH_REUSE_EMAIL", "0") == "1"
    golden_count = int(_optional("RAGP_BENCH_GOLDEN_COUNT", "5"))

    if not CORPUS_DIR.exists():
        sys.exit(f"missing corpus: {CORPUS_DIR}")

    corpus_files = sorted(p for p in CORPUS_DIR.iterdir() if p.suffix in {".txt", ".md"})
    if not corpus_files:
        sys.exit(f"no corpus files under {CORPUS_DIR}")

    client = httpx.Client(base_url=base_url, timeout=60.0, follow_redirects=False)

    # 1. signup or login
    if reuse:
        print(f"[seed] login as {email}")
        auth_resp = _post(
            client,
            "/api/v1/auth/login",
            json={"email": email, "password": password},
        )
    else:
        print(f"[seed] signup {email} / org={org_name}")
        auth_resp = _post(
            client,
            "/api/v1/auth/signup",
            json={
                "email": email,
                "password": password,
                "organization_name": org_name,
            },
        )

    auth_data = auth_resp.json()
    org_id = auth_data["organization"]["id"]
    session_cookie = client.cookies.get("ragp_session", "")
    if not session_cookie:
        sys.exit("auth response did not set ragp_session cookie")

    print(f"[seed] org_id={org_id}")

    # 2. create API key
    print("[seed] creating API key")
    key_resp = _post(
        client,
        "/api/v1/keys",
        json={"name": f"bench-{int(time.time())}"},
    )
    api_key = key_resp.json()["key"]
    print(f"[seed] api_key prefix={api_key[:8]}...")

    # 3. create dataset
    print(f"[seed] creating dataset {dataset_name}")
    ds_resp = _post(
        client,
        "/api/v1/datasets",
        json={"name": dataset_name, "organization_id": org_id},
    )
    dataset_id = ds_resp.json()["id"]
    print(f"[seed] dataset_id={dataset_id}")

    # 4. upload corpus
    for path in corpus_files:
        print(f"[seed] uploading {path.name} ({path.stat().st_size} bytes)")
        with path.open("rb") as fh:
            files = {"file": (path.name, fh.read(), "text/plain")}
        data = {"chunker_name": "recursive-character", "chunker_params": "{}"}
        upload_resp = client.post(
            f"/api/v1/datasets/{dataset_id}/documents",
            files=files,
            data=data,
            timeout=300.0,
        )
        if upload_resp.status_code == 402:
            sys.exit(
                "402 Payment Required during upload — activate a plan for the "
                "bench org first.  See scripts/bench/README.md "
                "section 'Activate plan on prod'."
            )
        if upload_resp.status_code not in (200, 201):
            sys.exit(
                f"upload {path.name} failed: HTTP {upload_resp.status_code}: "
                f"{upload_resp.text[:400]}"
            )

    # 5. generate golden Q&A
    print(f"[seed] generating {golden_count} golden Q&A items")
    try:
        golden_resp = client.post(
            f"/api/v1/datasets/{dataset_id}/golden",
            json={"count": golden_count},
            timeout=600.0,
        )
        if golden_resp.status_code in (200, 201):
            print(f"[seed] golden Q&A generated: {len(golden_resp.json())} items")
        else:
            print(
                f"[seed] WARN golden generation returned "
                f"{golden_resp.status_code}: {golden_resp.text[:200]} — "
                "continuing without golden set."
            )
    except httpx.HTTPError as exc:
        print(f"[seed] WARN golden generation network error: {exc}")

    # 6. write env file
    env_payload = (
        f"RAGP_BENCH_BASE_URL={base_url}\n"
        f"RAGP_BENCH_SESSION_COOKIE={session_cookie}\n"
        f"RAGP_BENCH_API_KEY={api_key}\n"
        f"RAGP_BENCH_ORG_ID={org_id}\n"
        f"RAGP_BENCH_DATASET_ID={dataset_id}\n"
    )
    ENV_FILE.write_text(env_payload, encoding="utf-8")
    print(f"\n[seed] wrote {ENV_FILE}")
    print("[seed] source it with:  set -a; . scripts/bench/.bench-env; set +a")
    print(env_payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
