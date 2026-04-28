"""S3-compatible object storage for raw uploaded documents."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import hmac
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from ragp_api.settings import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObjectStorageRef:
    backend: str
    key: str | None


@dataclass(frozen=True)
class S3Config:
    endpoint_url: str
    region: str
    bucket: str
    access_key_id: str
    secret_access_key: str


class ObjectStorageError(RuntimeError):
    """Raised when object storage is configured but an operation fails."""


def _infer_region(endpoint_url: str) -> str:
    host = urllib.parse.urlparse(endpoint_url).netloc
    match = re.search(r"\b(ru-\d+)\b", host)
    if match:
        return match.group(1)
    return "ru-1"


def _get_config() -> S3Config | None:
    if not (
        settings.s3_endpoint_url
        and settings.s3_bucket
        and settings.s3_access_key_id
        and settings.s3_secret_access_key
    ):
        return None
    return S3Config(
        endpoint_url=settings.s3_endpoint_url.rstrip("/"),
        region=settings.s3_region or _infer_region(settings.s3_endpoint_url),
        bucket=settings.s3_bucket,
        access_key_id=settings.s3_access_key_id,
        secret_access_key=settings.s3_secret_access_key,
    )


def _quote_key(key: str) -> str:
    return urllib.parse.quote(key, safe="/")


def _safe_filename(filename: str) -> str:
    candidate = filename.strip().replace("\\", "/").split("/")[-1]
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate)
    return candidate[:128] or "document"


def build_document_object_key(
    *,
    organization_id: str,
    dataset_id: str,
    document_id: str,
    filename: str,
) -> str:
    return (
        f"orgs/{organization_id}/datasets/{dataset_id}/"
        f"documents/{document_id}/{_safe_filename(filename)}"
    )


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def _send_s3_request(
    *,
    config: S3Config,
    method: str,
    key: str,
    body: bytes = b"",
    content_type: str | None = None,
    metadata: dict[str, str] | None = None,
) -> None:
    parsed = urllib.parse.urlparse(config.endpoint_url)
    host = parsed.netloc
    canonical_uri = f"/{config.bucket}/{_quote_key(key)}"
    url = f"{config.endpoint_url}{canonical_uri}"

    now = dt.datetime.now(dt.UTC)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()

    headers: dict[str, str] = {
        "Host": host,
        "X-Amz-Content-Sha256": payload_hash,
        "X-Amz-Date": amz_date,
    }
    if content_type:
        headers["Content-Type"] = content_type
    for name, value in (metadata or {}).items():
        headers[f"X-Amz-Meta-{name.lower()}"] = value

    signed_header_names = sorted(name.lower() for name in headers)
    header_values = {name.lower(): value for name, value in headers.items()}
    canonical_headers = "".join(
        f"{name}:{header_values[name].strip()}\n" for name in signed_header_names
    )
    signed_headers = ";".join(signed_header_names)
    canonical_request = "\n".join(
        [
            method,
            canonical_uri,
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        ]
    )

    credential_scope = f"{date_stamp}/{config.region}/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    k_date = _sign(("AWS4" + config.secret_access_key).encode("utf-8"), date_stamp)
    k_region = _sign(k_date, config.region)
    k_service = _sign(k_region, "s3")
    k_signing = _sign(k_service, "aws4_request")
    signature = hmac.new(k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    headers["Authorization"] = (
        "AWS4-HMAC-SHA256 "
        f"Credential={config.access_key_id}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            if response.status >= 300:
                raise ObjectStorageError(f"S3 {method} {key} returned {response.status}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise ObjectStorageError(
            f"S3 {method} {key} failed with HTTP {exc.code}: {detail}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ObjectStorageError(f"S3 {method} {key} failed: {exc}") from exc


async def store_raw_document(
    *,
    raw: bytes,
    organization_id: str,
    dataset_id: str,
    document_id: str,
    filename: str,
    content_type: str,
    sha256: str,
) -> ObjectStorageRef:
    config = _get_config()
    if config is None:
        return ObjectStorageRef(backend="transient", key=None)

    key = build_document_object_key(
        organization_id=organization_id,
        dataset_id=dataset_id,
        document_id=document_id,
        filename=filename,
    )
    await asyncio.to_thread(
        _send_s3_request,
        config=config,
        method="PUT",
        key=key,
        body=raw,
        content_type=content_type or "application/octet-stream",
        metadata={"sha256": sha256, "document-id": document_id},
    )
    return ObjectStorageRef(backend="s3", key=key)


async def delete_raw_documents(refs: list[ObjectStorageRef]) -> None:
    config = _get_config()
    if config is None:
        if any(ref.backend == "s3" and ref.key for ref in refs):
            logger.warning("S3 document refs exist but S3 storage is not configured")
        return

    for ref in refs:
        if ref.backend != "s3" or not ref.key:
            continue
        await asyncio.to_thread(
            _send_s3_request,
            config=config,
            method="DELETE",
            key=ref.key,
        )
