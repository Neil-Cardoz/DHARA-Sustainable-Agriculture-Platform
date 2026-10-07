from typing import List
from uuid import UUID

from dhara_shared.models import Device, FPOCluster, Operator, Plot, StorageLot
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..deps import get_session

router = APIRouter(prefix="/clusters", tags=["clusters"])


@router.post("", response_model=FPOCluster)
def create_cluster(cluster: FPOCluster, session: Session = Depends(get_session)):
    session.add(cluster)
    session.commit()
    session.refresh(cluster)
    return cluster


@router.get("", response_model=List[FPOCluster])
def list_clusters(session: Session = Depends(get_session)):
    return session.exec(select(FPOCluster)).all()


@router.get("/{cluster_id}", response_model=FPOCluster)
def get_cluster(cluster_id: UUID, session: Session = Depends(get_session)):
    cluster = session.get(FPOCluster, cluster_id)
    if not cluster:
        raise HTTPException(404, "cluster not found")
    return cluster


@router.get("/{cluster_id}/summary")
def cluster_summary(cluster_id: UUID, session: Session = Depends(get_session)):
    """Operator console landing view: plot count, device health, cold-room occupancy."""
    cluster = session.get(FPOCluster, cluster_id)
    if not cluster:
        raise HTTPException(404, "cluster not found")

    plots = session.exec(select(Plot).where(Plot.cluster_id == cluster_id)).all()
    devices = session.exec(select(Device).where(Device.cluster_id == cluster_id)).all()
    plot_ids = [p.id for p in plots]
    devices += session.exec(select(Device).where(Device.plot_id.in_(plot_ids))).all() if plot_ids else []
    lots = session.exec(
        select(StorageLot).where(StorageLot.cluster_id == cluster_id, StorageLot.dispatched_ts.is_(None))
    ).all()

    health_counts: dict[str, int] = {}
    for d in devices:
        health_counts[d.health_state] = health_counts.get(d.health_state, 0) + 1

    cold_room_occupied_kg = sum(l.mass_kg for l in lots)

    return {
        "cluster": cluster,
        "plot_count": len(plots),
        "device_count": len(devices),
        "device_health": health_counts,
        "cold_room_occupied_kg": cold_room_occupied_kg,
        "cold_room_capacity_kg": cluster.cold_room_capacity_kg,
        "cold_room_utilisation_pct": round(
            100 * cold_room_occupied_kg / cluster.cold_room_capacity_kg, 1
        ) if cluster.cold_room_capacity_kg else 0,
    }


@router.post("/{cluster_id}/operators", response_model=Operator)
def add_operator(cluster_id: UUID, operator: Operator, session: Session = Depends(get_session)):
    operator.cluster_id = cluster_id
    session.add(operator)
    session.commit()
    session.refresh(operator)
    return operator
