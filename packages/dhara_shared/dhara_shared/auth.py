"""Auth helpers shared across services.

Two schemes are used deliberately, matching who is calling:
  - Service-to-service and simulator calls: a shared-secret HMAC bearer token
    (`X-Dhara-Signature`), cheap enough to run on an ESP32-class edge box.
  - Operator console (humans): Microsoft Entra ID JWT bearer tokens, validated
    against the tenant's JWKS.
"""
import hashlib
import hmac
import time

import httpx
from jose import jwt

from .config import get_settings

_jwks_cache: dict = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_SECONDS = 3600


def sign_payload(body: bytes, timestamp: str) -> str:
    settings = get_settings()
    mac = hmac.new(settings.api_shared_secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return mac.hexdigest()


def verify_signature(body: bytes, timestamp: str, signature: str, max_skew_seconds: int = 300) -> bool:
    try:
        if abs(time.time() - float(timestamp)) > max_skew_seconds:
            return False
    except ValueError:
        return False
    expected = sign_payload(body, timestamp)
    return hmac.compare_digest(expected, signature)


def _get_jwks(tenant_id: str) -> dict:
    now = time.time()
    if _jwks_cache["keys"] is None or now - _jwks_cache["fetched_at"] > _JWKS_TTL_SECONDS:
        url = f"https://login.microsoftonline.com/{tenant_id}/discovery/v2.0/keys"
        resp = httpx.get(url, timeout=10)
        resp.raise_for_status()
        _jwks_cache["keys"] = resp.json()
        _jwks_cache["fetched_at"] = now
    return _jwks_cache["keys"]


def validate_entra_token(token: str) -> dict:
    """Validate an Entra ID access token for the operator console API.

    Raises jose.JWTError on any validation failure; caller maps that to HTTP 401.
    """
    settings = get_settings()
    if not settings.entra_tenant_id or not settings.entra_api_client_id:
        raise RuntimeError("ENTRA_TENANT_ID / ENTRA_API_CLIENT_ID not configured")

    jwks = _get_jwks(settings.entra_tenant_id)
    unverified_header = jwt.get_unverified_header(token)
    key = next((k for k in jwks["keys"] if k["kid"] == unverified_header["kid"]), None)
    if key is None:
        raise jwt.JWTError("signing key not found in tenant JWKS")

    claims = jwt.decode(
        token,
        key,
        algorithms=["RS256"],
        audience=settings.entra_api_client_id,
        issuer=f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0",
    )
    return claims
