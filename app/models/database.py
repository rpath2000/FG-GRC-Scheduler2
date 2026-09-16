"""
Shared SQLAlchemy engine, session factory and FastAPI dependency.

This module is the ONE place the application configures its database
connectivity. The engine is built lazily-safe (no connection at import
time) from `app.db_url.DATABASE_URL`, which itself already falls back to
a local sqlite URL when `DATABASE_URL` is unset.

Every other component must import `get_db`, `Base`, and the ORM models
from here (or re-exported via `app.models`) rather than defining its own
engine/session/Base.
"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.db_url import DATABASE_URL

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    future=True,
)


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model in this application."""


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a database session, closed on teardown."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Re-export the ORM models and enums so other components (and this module
# itself) present one coherent `app.models` / `app.models.database` surface.
from app.models.models import (  # noqa: E402  (import after Base is defined)
    AuditActionType,
    AuditEntityType,
    AuditLog,
    Instrument,
    InstrumentStatus,
    Location,
    Reservation,
    ReservationPurpose,
    Type,
    Vendor,
)

__all__ = [
    "engine",
    "SessionLocal",
    "Base",
    "get_db",
    "Instrument",
    "Location",
    "Vendor",
    "Type",
    "ReservationPurpose",
    "Reservation",
    "AuditLog",
    "InstrumentStatus",
    "AuditActionType",
    "AuditEntityType",
]
