"""Signed httpOnly session cookies using itsdangerous."""

import os

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SECRET = os.environ.get("RAGP_SESSION_SECRET", "dev-only-not-secret-change-in-prod")
_SALT = "ragp-session"
_MAX_AGE = 30 * 24 * 60 * 60  # 30 days in seconds
COOKIE_NAME = "ragp_session"


def _get_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_SECRET, salt=_SALT)


def make_session_cookie(user_id: str, org_id: str) -> str:
    """Create a signed session token containing user_id and org_id."""
    s = _get_serializer()
    return s.dumps({"u": user_id, "o": org_id})


def read_session_cookie(token: str) -> tuple[str, str] | None:
    """Parse and validate a session token.

    Returns (user_id, org_id) tuple or None if token is invalid or expired.
    """
    s = _get_serializer()
    try:
        data = s.loads(token, max_age=_MAX_AGE)
        return data["u"], data["o"]
    except (BadSignature, SignatureExpired, KeyError):
        return None
