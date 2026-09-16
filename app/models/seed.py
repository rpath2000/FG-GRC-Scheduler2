"""
Idempotent seed script for master data.

Populates Location, Vendor, InstrumentType, and ReservationPurpose with a
baseline set of active rows if (and only if) each table is currently empty.
Running this script multiple times must never create duplicate rows.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.database import SessionLocal
from app.models.models import InstrumentType, Location, ReservationPurpose, Vendor

DEFAULT_LOCATIONS = ["Main Lab", "Calibration Room", "Field Storage"]
DEFAULT_VENDORS = ["Acme Instruments", "Precision Corp", "Metrology Labs"]
DEFAULT_TYPES = ["Multimeter", "Oscilloscope", "Caliper"]
DEFAULT_PURPOSES = ["Calibration", "Training", "Production Use"]


def _seed_table(db: Session, model, names: list[str]) -> None:
    """Seed `model` with `names` only if the table currently has no rows."""
    existing_count = db.query(model).count()
    if existing_count > 0:
        return
    for name in names:
        db.add(model(name=name, is_active=True))


def seed_master_data(db: Session | None = None) -> None:
    """
    Populate master data tables if empty. Safe to call repeatedly: each
    table is only ever seeded from a zero-row state, so re-running this
    function against an already-seeded database is a no-op.
    """
    owns_session = db is None
    session = db if db is not None else SessionLocal()
    try:
        _seed_table(session, Location, DEFAULT_LOCATIONS)
        _seed_table(session, Vendor, DEFAULT_VENDORS)
        _seed_table(session, InstrumentType, DEFAULT_TYPES)
        _seed_table(session, ReservationPurpose, DEFAULT_PURPOSES)
        session.commit()
    finally:
        if owns_session:
            session.close()


if __name__ == "__main__":
    seed_master_data()
