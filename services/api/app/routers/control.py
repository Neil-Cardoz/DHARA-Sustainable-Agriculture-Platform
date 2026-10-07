from typing import Any, List
from uuid import UUID

from dhara_shared.models import Decision, IrrigationEvent
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..deps import get_session, require_service_key

router = APIRouter(prefix="/control", tags=["control"])


@router.post("/decisions", response_model=Decision, dependencies=[Depends(require_service_key)])
def record_decision(decision: Decision, session: Session = Depends(get_session)):
    session.add(decision)
    session.commit()
    session.refresh(decision)
    return decision


@router.get("/decisions", response_model=List[Decision])
def list_decisions(plot_id: UUID | None = None, limit: int = 100, session: Session = Depends(get_session)):
    stmt = select(Decision).order_by(Decision.ts.desc()).limit(limit)
    if plot_id:
        stmt = stmt.where(Decision.plot_id == plot_id)
    return session.exec(stmt).all()


@router.post("/irrigation-events", response_model=IrrigationEvent, dependencies=[Depends(require_service_key)])
def record_irrigation_event(event: IrrigationEvent, session: Session = Depends(get_session)):
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


@router.get("/irrigation-events", response_model=List[IrrigationEvent])
def list_irrigation_events(plot_id: UUID | None = None, limit: int = 100, session: Session = Depends(get_session)):
    stmt = select(IrrigationEvent).order_by(IrrigationEvent.ts_start.desc()).limit(limit)
    if plot_id:
        stmt = stmt.where(IrrigationEvent.plot_id == plot_id)
    return session.exec(stmt).all()


@router.patch(
    "/irrigation-events/{event_id}",
    response_model=IrrigationEvent,
    dependencies=[Depends(require_service_key)],
)
def update_irrigation_event(event_id: UUID, patch: dict[str, Any], session: Session = Depends(get_session)):
    """Used by the decision-engine's verify step to reconcile measured vs intended volume."""
    event = session.get(IrrigationEvent, event_id)
    if not event:
        raise HTTPException(404, "irrigation event not found")
    for field in ("verified", "verification_delta_pct", "volume_m3", "energy_kwh", "ts_end", "source"):
        if field in patch:
            setattr(event, field, patch[field])
    session.add(event)
    session.commit()
    session.refresh(event)
    return event
