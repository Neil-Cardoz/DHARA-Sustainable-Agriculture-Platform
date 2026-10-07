from datetime import datetime
from typing import List
from uuid import UUID

from dhara_shared.models import Reading
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session, select

from ..deps import get_session, require_service_key

router = APIRouter(prefix="/telemetry", tags=["telemetry"])


class ReadingIn(BaseModel):
    device_id: UUID
    ts: datetime
    metric: str
    value: float
    quality_flag: str = "ok"


@router.post("/ingest", dependencies=[Depends(require_service_key)])
def ingest_readings(readings: List[ReadingIn], session: Session = Depends(get_session)):
    """Bulk ingest called by the ingestion worker after it decodes IoT Hub messages."""
    rows = [Reading(**r.model_dump()) for r in readings]
    session.add_all(rows)
    session.commit()
    return {"inserted": len(rows)}


@router.get("", response_model=List[Reading])
def query_readings(
    device_id: UUID | None = None,
    metric: str | None = None,
    since: datetime | None = None,
    limit: int = 500,
    session: Session = Depends(get_session),
):
    stmt = select(Reading).order_by(Reading.ts.desc()).limit(limit)
    if device_id:
        stmt = stmt.where(Reading.device_id == device_id)
    if metric:
        stmt = stmt.where(Reading.metric == metric)
    if since:
        stmt = stmt.where(Reading.ts >= since)
    return session.exec(stmt).all()
