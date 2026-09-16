"""
Idempotent seed script for master data (Location, Vendor, InstrumentType,
ReservationPurpose).

Populates each master-data table with a baseline set of rows only if that
table is currently empty, and is safe to run multiple times: subsequent
runs perform no writes and create no duplicate rows.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import InstrumentType, Location, ReservationPurpose, Vendor, normalize_name

DEFAULT_LOCATIONS = ["Main Lab", "Building A", "Building B", "Warehouse"]
DEFAULT_VENDORS = ["Agilent", "Thermo Fisher", "Waters", "PerkinElmer"]
DEFAULT_TYPES = ["Spectrometer", "Chromatograph", "Balance", "Centrifuge"]
DEFAULT_PURPOSES = ["Routine Testing", "Calibration", "Research", "Maintenance"]


def _seed_master_table(db: Session, model, names: list[str]) -> None:
    existing_count = db.query(model).count()
    if existing_count > 0:
        return
    for name in names:
        row = model(name=name, is_active=True)
        db.add(row)
    db.flush()


def run_seed(db: Session) -> None:
    """Seed all master-data tables if they are empty. Idempotent across calls."""
    _seed_master_table(db, Location, DEFAULT_LOCATIONS)
    _seed_master_table(db, Vendor, DEFAULT_VENDORS)
    _seed_master_table(db, InstrumentType, DEFAULT_TYPES)
    _seed_master_table(db, ReservationPurpose, DEFAULT_PURPOSES)
    db.commit()


if __name__ == "__main__":
    from app.models.database import SessionLocal

    session = SessionLocal()
    try:
        run_seed(session)
    finally:
        session.close()
