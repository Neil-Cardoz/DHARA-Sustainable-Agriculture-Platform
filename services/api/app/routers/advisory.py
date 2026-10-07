from typing import List
from uuid import UUID

from dhara_shared.models import AdvisoryInteraction
from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from ..deps import get_session, require_service_key

router = APIRouter(prefix="/advisory", tags=["advisory"])


@router.post("/interactions", response_model=AdvisoryInteraction, dependencies=[Depends(require_service_key)])
def log_interaction(interaction: AdvisoryInteraction, session: Session = Depends(get_session)):
    """Called by the advisory-bot service after every WhatsApp/voice/lamp exchange,
    so every recommendation carries its inputs and is replayable in the farmer's language.
    """
    session.add(interaction)
    session.commit()
    session.refresh(interaction)
    return interaction


@router.get("/interactions", response_model=List[AdvisoryInteraction])
def list_interactions(
    plot_id: UUID | None = None,
    escalated_only: bool = False,
    limit: int = 100,
    session: Session = Depends(get_session),
):
    stmt = select(AdvisoryInteraction).order_by(AdvisoryInteraction.ts.desc()).limit(limit)
    if plot_id:
        stmt = stmt.where(AdvisoryInteraction.plot_id == plot_id)
    if escalated_only:
        stmt = stmt.where(AdvisoryInteraction.escalated_to_human.is_(True))
    return session.exec(stmt).all()
