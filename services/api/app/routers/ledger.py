from typing import List
from uuid import UUID

from dhara_shared.models import SavingsLedgerEntry
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..deps import get_session, require_service_key

router = APIRouter(prefix="/ledger", tags=["ledger"])


@router.post("", response_model=SavingsLedgerEntry, dependencies=[Depends(require_service_key)])
def record_entry(entry: SavingsLedgerEntry, session: Session = Depends(get_session)):
    """The verification ledger a discom, carbon buyer, or PMKSY audit can check against.
    Written by the decision-engine's period-close job, never edited by hand.
    """
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


@router.get("", response_model=List[SavingsLedgerEntry])
def list_entries(plot_id: UUID | None = None, session: Session = Depends(get_session)):
    stmt = select(SavingsLedgerEntry).order_by(SavingsLedgerEntry.period_start.desc())
    if plot_id:
        stmt = stmt.where(SavingsLedgerEntry.plot_id == plot_id)
    return session.exec(stmt).all()


@router.get("/summary")
def ledger_summary(session: Session = Depends(get_session)):
    entries = session.exec(select(SavingsLedgerEntry)).all()
    total_water = sum(e.baseline_water_m3 - e.actual_water_m3 for e in entries)
    total_energy = sum(e.baseline_energy_kwh - e.actual_energy_kwh for e in entries)
    total_co2e = sum(e.avoided_tco2e for e in entries)
    return {
        "entries": len(entries),
        "total_water_saved_m3": round(total_water, 1),
        "total_energy_saved_kwh": round(total_energy, 1),
        "total_avoided_tco2e": round(total_co2e, 3),
    }
