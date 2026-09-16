"""
ORM models for the instrument scheduling application.

This package defines the single declarative Base, all seven persisted
entities, the three domain enumerations, and re-exports get_db for
dependency injection. Every other component imports these names from
`app.models` (package-level) or `app.models.database` (module-level).
"""
import enum
import re
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import relationship

from app.models.database import Base, SessionLocal, engine, get_db  # noqa: F401


class InstrumentStatus(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
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
    TYPE = "TYPE"
    RESERVATION_PURPOSE = "RESERVATION_PURPOSE"
    RESERVATION = "RESERVATION"


def _normalize_name(name: str) -> str:
    """Normalize a master-data name for case-insensitive duplicate detection."""
    return re.sub(r"\s+", "", (name or "")).lower()


class Instrument(Base):
    __tablename__ = "instruments"

    instrument_id = Column("instrument_id", Integer, primary_key=True, autoincrement=True)
    name = Column("name", String(120), nullable=False)
    nickname = Column("nickname", String(120), nullable=False)
    location_id = Column("location_id", Integer, ForeignKey("locations.location_id"), nullable=False)
    vendor_id = Column("vendor_id", Integer, ForeignKey("vendors.vendor_id"), nullable=False)
    type_id = Column("type_id", Integer, ForeignKey("types.type_id"), nullable=False)
    asset_id = Column("asset_id", String(120), nullable=True)
    color = Column("color", String(30), nullable=True)
    status = Column(
        "status",
        SAEnum(InstrumentStatus, name="instrument_status", create_type=False, native_enum=True),
        nullable=False,
        default=InstrumentStatus.AVAILABLE,
    )
    is_favorite = Column("is_favorite", Boolean, nullable=False, default=False)
    is_active = Column("is_active", Boolean, nullable=False, default=True)
    start_datetime = Column("start_datetime", DateTime(timezone=True), nullable=True)
    created_at = Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        "updated_at",
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    location = relationship("Location", back_populates="instruments")
    vendor = relationship("Vendor", back_populates="instruments")
    type = relationship("Type", back_populates="instruments")
    reservations = relationship("Reservation", back_populates="instrument")


class Location(Base):
    __tablename__ = "locations"

    location_id = Column("location_id", Integer, primary_key=True, autoincrement=True)
    name = Column("name", String(120), nullable=False)
    normalized_name = Column("normalized_name", String(120), nullable=False)
    is_active = Column("is_active", Boolean, nullable=False, default=True)
    created_at = Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_locations_normalized_name"),
    )

    instruments = relationship("Instrument", back_populates="location")


class Vendor(Base):
    __tablename__ = "vendors"

    vendor_id = Column("vendor_id", Integer, primary_key=True, autoincrement=True)
    name = Column("name", String(120), nullable=False)
    normalized_name = Column("normalized_name", String(120), nullable=False)
    is_active = Column("is_active", Boolean, nullable=False, default=True)
    created_at = Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_vendors_normalized_name"),
    )

    instruments = relationship("Instrument", back_populates="vendor")


class Type(Base):
    __tablename__ = "types"

    type_id = Column("type_id", Integer, primary_key=True, autoincrement=True)
    name = Column("name", String(120), nullable=False)
    normalized_name = Column("normalized_name", String(120), nullable=False)
    is_active = Column("is_active", Boolean, nullable=False, default=True)
    created_at = Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_types_normalized_name"),
    )

    instruments = relationship("Instrument", back_populates="type")


class ReservationPurpose(Base):
    __tablename__ = "reservation_purposes"

    reservation_purpose_id = Column("reservation_purpose_id", Integer, primary_key=True, autoincrement=True)
    name = Column("name", String(120), nullable=False)
    normalized_name = Column("normalized_name", String(120), nullable=False)
    is_active = Column("is_active", Boolean, nullable=False, default=True)
    created_at = Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_reservation_purposes_normalized_name"),
    )

    reservations = relationship("Reservation", back_populates="purpose")


class Reservation(Base):
    __tablename__ = "reservations"

    reservation_id = Column("reservation_id", Integer, primary_key=True, autoincrement=True)
    instrument_id = Column("instrument_id", Integer, ForeignKey("instruments.instrument_id"), nullable=False)
    start_datetime = Column("start_datetime", DateTime(timezone=True), nullable=False)
    end_datetime = Column("end_datetime", DateTime(timezone=True), nullable=False)
    reservation_purpose_id = Column(
        "reservation_purpose_id",
        Integer,
        ForeignKey("reservation_purposes.reservation_purpose_id"),
        nullable=False,
    )
    requested_by = Column("requested_by", String(120), nullable=True)
    can_be_overridden = Column("can_be_overridden", Boolean, nullable=False, default=False)
    is_active = Column("is_active", Boolean, nullable=False, default=True)
    created_at = Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint("end_datetime > start_datetime", name="ck_reservations_end_after_start"),
    )

    instrument = relationship("Instrument", back_populates="reservations")
    purpose = relationship("ReservationPurpose", back_populates="reservations")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_log_id = Column("audit_log_id", Integer, primary_key=True, autoincrement=True)
    actor = Column("actor", String(120), nullable=False)
    timestamp = Column(
        "timestamp",
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    action_type = Column(
        "action_type",
        SAEnum(AuditActionType, name="audit_action_type", create_type=False, native_enum=True),
        nullable=False,
    )
    entity_type = Column(
        "entity_type",
        SAEnum(AuditEntityType, name="audit_entity_type", create_type=False, native_enum=True),
        nullable=False,
    )
    entity_id = Column("entity_id", Integer, nullable=False)
    description = Column("description", String(1000), nullable=False)


__all__ = [
    "Base",
    "SessionLocal",
    "engine",
    "get_db",
    "InstrumentStatus",
    "AuditActionType",
    "AuditEntityType",
    "Instrument",
    "Location",
    "Vendor",
    "Type",
    "ReservationPurpose",
    "Reservation",
    "AuditLog",
]
