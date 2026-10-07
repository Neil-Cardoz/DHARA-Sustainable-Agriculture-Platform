from typing import Iterator

from dhara_shared.db import get_session as _get_session
from dhara_shared.config import get_settings
from fastapi import Header, HTTPException, status
from sqlmodel import Session


def get_session() -> Iterator[Session]:
    with _get_session() as session:
        yield session


def require_service_key(x_api_key: str | None = Header(default=None)) -> None:
    """Coarse-grained shared-secret check for ingestion/decision-engine -> API calls.

    Kept intentionally simple: these are internal service-to-service calls inside
    the same Container Apps environment / VNet, not internet-facing.
    """
    settings = get_settings()
    if x_api_key != settings.api_shared_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing X-API-Key")
