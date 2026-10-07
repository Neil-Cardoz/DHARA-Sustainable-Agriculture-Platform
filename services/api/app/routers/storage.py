from datetime import datetime
from typing import Any, List
from uuid import UUID

from dhara_shared.models import StorageLot
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..deps import get_session, require_service_key

router = APIRouter(prefix="/storage-lots", tags=["storage"])


@router.post("", response_model=StorageLot)
def create_lot(lot: StorageLot, session: Session = Depends(get_session)):
    session.add(lot)
    session.commit()
    session.refresh(lot)
    return lot


@router.get("", response_model=List[StorageLot])
def list_lots(cluster_id: UUID | None = None, active_only: bool = True, session: Session = Depends(get_session)):
    stmt = select(StorageLot)
    if cluster_id:
        stmt = stmt.where(StorageLot.cluster_id == cluster_id)
    if active_only:
        stmt = stmt.where(StorageLot.dispatched_ts.is_(None))
    return session.exec(stmt.order_by(StorageLot.intake_ts)).all()


@router.patch("/{lot_id}", response_model=StorageLot, dependencies=[Depends(require_service_key)])
def update_lot(lot_id: UUID, patch: dict[str, Any], session: Session = Depends(get_session)):
    lot = session.get(StorageLot, lot_id)
    if not lot:
        raise HTTPException(404, "lot not found")
    if "predicted_shelf_life_hours" in patch:
        lot.predicted_shelf_life_hours = patch["predicted_shelf_life_hours"]
    session.add(lot)
    session.commit()
    session.refresh(lot)
    return lot


@router.post("/{lot_id}/thermal-event", response_model=StorageLot)
def log_thermal_event(lot_id: UUID, temp_c: float, session: Session = Depends(get_session)):
    """A door-open event or cold-room excursion. Recomputing predicted_shelf_life_hours
    happens in the decision-engine's shelf-life model; this just appends the reading
    so a lot that warmed moves up the dispatch queue automatically.
    """
    lot = session.get(StorageLot, lot_id)
    if not lot:
        raise HTTPException(404, "lot not found")
    lot.thermal_history = [*lot.thermal_history, {"ts": datetime.utcnow().isoformat(), "temp_c": temp_c}]
    session.add(lot)
    session.commit()
    session.refresh(lot)
    return lot


@router.post("/{lot_id}/dispatch", response_model=StorageLot)
def dispatch_lot(lot_id: UUID, destination: str, session: Session = Depends(get_session)):
    lot = session.get(StorageLot, lot_id)
    if not lot:
        raise HTTPException(404, "lot not found")
    lot.dispatched_ts = datetime.utcnow()
    lot.dispatched_to = destination
    session.add(lot)
    session.commit()
    session.refresh(lot)
    return lot
