"""Idempotent seed-data loader for initial master data.

Inserts the baseline Locations, Vendors, Types, and ReservationPurposes on
first run. Safe to run multiple times: existing active or inactive records
(matched by normalized name) are never duplicated.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.models import Location, ReservationPurpose, Type, Vendor

_LOCATIONS = ["Lab 224", "Lab 226", "Lab L128A", "Lab L128B"]
_VENDORS = [
    "Beckman Coulter",
    "Covaris",
    "Eppendorf",
    "AutoGen",
    "Promega",
    "Illumina",
    "QIAGEN",
]
_TYPES = ["Liquid Handler", "Sonicator", "Extraction", "Sequencer"]
_PURPOSES = ["Method development", "Sample analysis", "Maintenance", "Validation", "Training"]


def _normalize(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).lower()


def _seed_model(db: Session, model, names: list[str]) -> None:
    existing_normalized = {_normalize(row.name) for row in db.query(model).all()}
    for name in names:
        if _normalize(name) not in existing_normalized:
            db.add(model(name=name, is_active=True))
            existing_normalized.add(_normalize(name))


def load_seed_data(db: Session) -> None:
    """Insert baseline master data if it does not already exist.

    Idempotent: safe to call on every startup. Matches on normalized
    (trimmed, lowercased, whitespace-collapsed) name to avoid duplicates
    regardless of active/inactive state.
    """
    _seed_model(db, Location, _LOCATIONS)
    _seed_model(db, Vendor, _VENDORS)
    _seed_model(db, Type, _TYPES)
    _seed_model(db, ReservationPurpose, _PURPOSES)
    db.commit()
