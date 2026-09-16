"""
Enumerations shared by the ORM models in this package.
"""
from __future__ import annotations

import enum


class InstrumentStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class AuditActionType(str, enum.Enum):
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    ACTIVATE = "ACTIVATE"
    DEACTIVATE = "DEACTIVATE"
    OVERRIDE = "OVERRIDE"


class AuditEntityType(str, enum.Enum):
    INSTRUMENT = "INSTRUMENT"
    LOCATION = "LOCATION"
    VENDOR = "VENDOR"
    INSTRUMENT_TYPE = "INSTRUMENT_TYPE"
    RESERVATION_PURPOSE = "RESERVATION_PURPOSE"
    RESERVATION = "RESERVATION"
