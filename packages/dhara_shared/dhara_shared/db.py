"""Engine/session factory shared by the API and every worker service."""
from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=300)
    return _engine


def init_db() -> None:
    """Create all tables. Idempotent; used by scripts/init_db.py and local dev."""
    SQLModel.metadata.create_all(get_engine())


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
