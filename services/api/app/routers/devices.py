from datetime import datetime
from typing import List
from uuid import UUID

from dhara_shared.models import Device, DeviceCommand
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..deps import get_session, require_service_key

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("", response_model=Device)
def register_device(device: Device, session: Session = Depends(get_session)):
    session.add(device)
    session.commit()
    session.refresh(device)
    return device


@router.get("", response_model=List[Device])
def list_devices(
    plot_id: UUID | None = None, cluster_id: UUID | None = None, session: Session = Depends(get_session)
):
    stmt = select(Device)
    if plot_id:
        stmt = stmt.where(Device.plot_id == plot_id)
    if cluster_id:
        stmt = stmt.where(Device.cluster_id == cluster_id)
    return session.exec(stmt).all()


@router.get("/by-hardware-id/{hardware_id}", response_model=Device)
def get_device_by_hardware_id(hardware_id: str, session: Session = Depends(get_session)):
    device = session.exec(select(Device).where(Device.hardware_id == hardware_id)).first()
    if not device:
        raise HTTPException(404, "device not found")
    return device


@router.patch("/{device_id}/heartbeat", dependencies=[Depends(require_service_key)])
def heartbeat(
    device_id: UUID,
    battery_mv: int | None = None,
    health_state: str | None = None,
    session: Session = Depends(get_session),
):
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "device not found")
    device.last_seen = datetime.utcnow()
    if battery_mv is not None:
        device.battery_mv = battery_mv
    if health_state is not None:
        device.health_state = health_state
    session.add(device)
    session.commit()
    return {"ok": True}


@router.post("/{device_id}/commands", response_model=DeviceCommand, dependencies=[Depends(require_service_key)])
def queue_command(device_id: UUID, command: DeviceCommand, session: Session = Depends(get_session)):
    """Record a cloud-to-device command that the decision engine already sent via IoT Hub.

    The IoT Hub send itself happens in the decision-engine service (it holds the
    service connection string); this endpoint just keeps the audit log.
    """
    command.device_id = device_id
    session.add(command)
    session.commit()
    session.refresh(command)
    return command
