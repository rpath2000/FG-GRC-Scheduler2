"""Loads initial master data on first deployment."""

from __future__ import annotations

from sqlalchemy import select

from app.models import Location, ReservationPurpose, Type, Vendor
from sqlalchemy.orm import Session

_SEED_LOCATIONS = ["Main Lab", "Annex Lab", "Storage Room"]
_SEED_VENDORS = ["Agilent", "Thermo Fisher", "Waters"]
_SEED_TYPES = ["Chromatograph", "Spectrometer", "Balance"]
_SEED_PURPOSES = ["Research", "Maintenance", "Calibration"]


class SeedService:
    """Loads seed master data if the corresponding tables are empty."""

    def __init__(self, db: Session):
        self.db = db

    def load_seed_data(self) -> None:
        self._seed_locations()
        self._seed_vendors()
        self._seed_types()
        self._seed_purposes()
        self.db.commit()

    def _seed_locations(self) -> None:
        existing = self.db.execute(select(Location)).scalars().first()
        if existing is not None:
            return
        for name in _SEED_LOCATIONS:
            self.db.add(Location(name=name, is_active=True))
        self.db.flush()

    def _seed_vendors(self) -> None:
        existing = self.db.execute(select(Vendor)).scalars().first()
        if existing is not None:
            return
        for name in _SEED_VENDORS:
            self.db.add(Vendor(name=name, is_active=True))
        self.db.flush()

    def _seed_types(self) -> None:
        existing = self.db.execute(select(Type)).scalars().first()
        if existing is not None:
            return
        for name in _SEED_TYPES:
            self.db.add(Type(name=name, is_active=True))
        self.db.flush()

    def _seed_purposes(self) -> None:
        existing = self.db.execute(select(ReservationPurpose)).scalars().first()
        if existing is not None:
            return
        for name in _SEED_PURPOSES:
            self.db.add(ReservationPurpose(name=name, is_active=True))
        self.db.flush()
