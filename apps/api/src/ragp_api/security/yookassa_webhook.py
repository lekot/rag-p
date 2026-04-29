"""IP allowlist enforcement for the public YooKassa webhook endpoint.

YooKassa does not sign webhook payloads (no HMAC, no JWT).  Production
hardening therefore requires:

1.  Filtering inbound traffic by source IP against the published YooKassa
    CIDRs (this module).
2.  Re-fetching the payment via ``GET /payments/{id}`` to confirm the claim
    in the webhook body (see ``services.yookassa_client.fetch_payment_status``).

The dependency ``verify_yookassa_request`` extracts the *real* client IP from
``request.client`` plus the ``X-Forwarded-For`` chain.  XFF entries are only
honoured when the connection is sourced from a trusted reverse proxy (Caddy,
Docker bridge networks).  Otherwise the raw socket peer is used to defeat
client-supplied XFF spoofing.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Iterable

from fastapi import HTTPException, Request, status

from ragp_api.settings import settings

logger = logging.getLogger(__name__)

IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _parse_networks(raw: str) -> list[IPNetwork]:
    """Parse a comma/whitespace separated CIDR list into network objects.

    Empty entries are silently ignored.  Invalid entries are dropped with a
    warning so a single typo in env config never crashes the request path.
    """
    nets: list[IPNetwork] = []
    for token in raw.replace(";", ",").split(","):
        cidr = token.strip()
        if not cidr:
            continue
        try:
            nets.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("yookassa_webhook: ignoring invalid CIDR entry: %r", cidr)
    return nets


def _ip_in_any(ip: IPAddress, networks: Iterable[IPNetwork]) -> bool:
    for net in networks:
        # ip_network and ip_address must be the same family for `in`.
        if ip.version != net.version:
            continue
        if ip in net:
            return True
    return False


def _resolve_client_ip(
    request: Request,
    trusted_proxies: list[IPNetwork],
) -> IPAddress | None:
    """Resolve the originating client IP using the trusted proxy chain.

    Algorithm (matches the de-facto behaviour of Caddy/Nginx):

    1. Take the immediate socket peer (``request.client.host``).
    2. If it is *not* in ``trusted_proxies`` — return it as-is.  XFF cannot
       be trusted because anyone on the internet can set the header.
    3. Otherwise walk ``X-Forwarded-For`` right-to-left, dropping entries
       that fall inside ``trusted_proxies``.  The first non-trusted entry
       is the real client.
    4. If every XFF entry is trusted (or XFF is missing), fall back to the
       original socket peer.
    """
    if request.client is None:
        return None

    try:
        peer_ip = ipaddress.ip_address(request.client.host)
    except ValueError:
        return None

    if not _ip_in_any(peer_ip, trusted_proxies):
        return peer_ip

    xff_header = request.headers.get("x-forwarded-for", "").strip()
    if not xff_header:
        return peer_ip

    # XFF format: "client, proxy1, proxy2".  Right-most entry is the closest
    # proxy.  We strip trusted proxies from the right and the first remaining
    # entry is the real client.
    raw_chain = [item.strip() for item in xff_header.split(",") if item.strip()]
    for candidate in reversed(raw_chain):
        try:
            cand_ip = ipaddress.ip_address(candidate)
        except ValueError:
            # Malformed entry: stop walking, treat as opaque.
            return peer_ip
        if not _ip_in_any(cand_ip, trusted_proxies):
            return cand_ip

    return peer_ip


async def verify_yookassa_request(request: Request) -> None:
    """FastAPI dependency: reject calls that don't originate from YooKassa.

    Behaviour:

    * If ``RAGP_YOOKASSA_REQUIRE_IP_CHECK`` is false -> no-op (used in tests
      and during initial migration).
    * Otherwise compute the real client IP via ``_resolve_client_ip`` and
      require it to fall inside ``RAGP_YOOKASSA_ALLOWED_IPS``.
    * On rejection raise ``HTTPException(403, detail="ip_not_allowed")`` and
      log the offending IP for audit.
    """
    if not settings.yookassa_require_ip_check:
        return

    trusted_proxies = _parse_networks(settings.yookassa_trusted_proxies)
    allowed_nets = _parse_networks(settings.yookassa_allowed_ips)

    if not allowed_nets:
        # Misconfiguration: refuse to fail-open.  An empty allowlist with the
        # check enabled means production is broken — surface that loudly.
        logger.error("yookassa_webhook: ip check enabled but RAGP_YOOKASSA_ALLOWED_IPS is empty")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ip_not_allowed",
        )

    client_ip = _resolve_client_ip(request, trusted_proxies)
    if client_ip is None or not _ip_in_any(client_ip, allowed_nets):
        logger.warning(
            "yookassa_webhook: rejecting request from %s (xff=%r, peer=%r)",
            client_ip,
            request.headers.get("x-forwarded-for"),
            request.client.host if request.client else None,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="ip_not_allowed",
        )
