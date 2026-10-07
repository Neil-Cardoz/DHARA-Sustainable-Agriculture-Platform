from typing import List
from uuid import UUID

from dhara_shared.models import EnergyArbitrationLog
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..deps import get_session, require_service_key

router = APIRouter(prefix="/energy", tags=["energy"])


@router.post("/arbitration-logs", response_model=EnergyArbitrationLog, dependencies=[Depends(require_service_key)])
def record_arbitration(log: EnergyArbitrationLog, session: Session = Depends(get_session)):
    session.add(log)
    session.commit()
    session.refresh(log)
    return log


@router.get("/arbitration-logs", response_model=List[EnergyArbitrationLog])
def list_arbitration(cluster_id: UUID | None = None, limit: int = 50, session: Session = Depends(get_session)):
    stmt = select(EnergyArbitrationLog).order_by(EnergyArbitrationLog.ts.desc()).limit(limit)
    if cluster_id:
        stmt = stmt.where(EnergyArbitrationLog.cluster_id == cluster_id)
    return session.exec(stmt).all()
