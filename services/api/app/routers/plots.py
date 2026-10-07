from datetime import datetime, timedelta
from typing import Any, List
from uuid import UUID

from dhara_shared.models import CropCycle, Decision, Device, IrrigationEvent, Plot, Reading
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..deps import get_session, require_service_key

router = APIRouter(prefix="/plots", tags=["plots"])


@router.post("", response_model=Plot)
def create_plot(plot: Plot, session: Session = Depends(get_session)):
    session.add(plot)
    session.commit()
    session.refresh(plot)
    return plot


@router.get("", response_model=List[Plot])
def list_plots(cluster_id: UUID | None = None, session: Session = Depends(get_session)):
    stmt = select(Plot)
    if cluster_id:
        stmt = stmt.where(Plot.cluster_id == cluster_id)
    return session.exec(stmt).all()


@router.get("/{plot_id}", response_model=Plot)
def get_plot(plot_id: UUID, session: Session = Depends(get_session)):
    plot = session.get(Plot, plot_id)
    if not plot:
        raise HTTPException(404, "plot not found")
    return plot


@router.patch("/{plot_id}", response_model=Plot, dependencies=[Depends(require_service_key)])
def update_plot(plot_id: UUID, patch: dict[str, Any], session: Session = Depends(get_session)):
    plot = session.get(Plot, plot_id)
    if not plot:
        raise HTTPException(404, "plot not found")
    allowed = {
        "seasonal_volumetric_used_m3", "seasonal_volumetric_cap_m3", "farmer_profile",
        "field_capacity_pct", "wilting_point_pct", "solar_pump_capacity_kw",
    }
    for field in allowed & patch.keys():
        setattr(plot, field, patch[field])
    session.add(plot)
    session.commit()
    session.refresh(plot)
    return plot


@router.post("/{plot_id}/crop-cycles", response_model=CropCycle)
def add_crop_cycle(plot_id: UUID, cycle: CropCycle, session: Session = Depends(get_session)):
    cycle.plot_id = plot_id
    session.add(cycle)
    session.commit()
    session.refresh(cycle)
    return cycle


@router.get("/{plot_id}/dashboard")
def plot_dashboard(plot_id: UUID, session: Session = Depends(get_session)):
    """Everything the operator console / WhatsApp bot needs about one plot at a glance."""
    plot = session.get(Plot, plot_id)
    if not plot:
        raise HTTPException(404, "plot not found")

    active_cycle = session.exec(
        select(CropCycle).where(CropCycle.plot_id == plot_id, CropCycle.status == "active")
    ).first()

    devices = session.exec(select(Device).where(Device.plot_id == plot_id)).all()

    since = datetime.utcnow() - timedelta(hours=24)
    recent_readings = session.exec(
        select(Reading)
        .where(Reading.device_id.in_([d.id for d in devices]) if devices else Reading.device_id.is_(None))
        .where(Reading.ts >= since)
        .order_by(Reading.ts.desc())
        .limit(200)
    ).all() if devices else []

    latest_decision = session.exec(
        select(Decision).where(Decision.plot_id == plot_id).order_by(Decision.ts.desc())
    ).first()

    last_irrigation = session.exec(
        select(IrrigationEvent).where(IrrigationEvent.plot_id == plot_id).order_by(IrrigationEvent.ts_start.desc())
    ).first()

    return {
        "plot": plot,
        "active_crop_cycle": active_cycle,
        "devices": devices,
        "recent_readings": recent_readings,
        "latest_decision": latest_decision,
        "last_irrigation_event": last_irrigation,
        "seasonal_allocation_remaining_m3": max(
            0.0, plot.seasonal_volumetric_cap_m3 - plot.seasonal_volumetric_used_m3
        ),
    }
