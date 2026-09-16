"""
ORM models for the instrument scheduling application.

Exposes Base, get_db, all entity models, and the audit/enum types so other
components can `from app.models import ...`.
"""
from __future__ import annotations

import enum
import re
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum as SAEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship, validates

from app.models.database import Base, SessionLocal, engine, get_db
from app.models.types import UTCDateTime

__all__ = [
    "Base",
    "get_db",
    "SessionLocal",
    "engine",
    "Instrument",
    "Location",
    "Vendor",
    "InstrumentType",
    "ReservationPurpose",
    "Reservation",
    "AuditLog",
    "InstrumentStatus",
    "AuditActionType",
    "AuditEntityType",
]


def normalize_name(name: str) -> str:
    """Normalize a master-data name for case-insensitive uniqueness comparisons."""
    return re.sub(r"\s+", " ", (name or "").strip()).lower()


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


class Location(Base):
    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_locations_normalized_name"),
    )

    location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    instruments: Mapped[list["Instrument"]] = relationship(back_populates="location")

    @validates("name")
    def _set_normalized_name(self, key, value):
        self.normalized_name = normalize_name(value)
        return value


class Vendor(Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_vendors_normalized_name"),
    )

    vendor_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    instruments: Mapped[list["Instrument"]] = relationship(back_populates="vendor")

    @validates("name")
    def _set_normalized_name(self, key, value):
        self.normalized_name = normalize_name(value)
        return value


class InstrumentType(Base):
    __tablename__ = "instrument_types"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_instrument_types_normalized_name"),
    )

    type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    instruments: Mapped[list["Instrument"]] = relationship(back_populates="type")

    @validates("name")
    def _set_normalized_name(self, key, value):
        self.normalized_name = normalize_name(value)
        return value


class ReservationPurpose(Base):
    __tablename__ = "reservation_purposes"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_reservation_purposes_normalized_name"),
    )

    reservation_purpose_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    reservations: Mapped[list["Reservation"]] = relationship(back_populates="purpose")

    @validates("name")
    def _set_normalized_name(self, key, value):
        self.normalized_name = normalize_name(value)
        return value


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (
        UniqueConstraint("normalized_name", name="uq_instruments_normalized_name"),
        Index("ix_instruments_location_id", "location_id"),
        Index("ix_instruments_vendor_id", "vendor_id"),
        Index("ix_instruments_type_id", "type_id"),
    )

    instrument_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False)
    nickname: Mapped[str] = mapped_column(String(200), nullable=False)
    location_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("locations.location_id"), nullable=False
    )
    vendor_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("vendors.vendor_id"), nullable=False
    )
    type_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("instrument_types.type_id"), nullable=False
    )
    asset_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[InstrumentStatus] = mapped_column(
        SAEnum(
            InstrumentStatus,
            name="instrument_status",
            native_enum=True,
            create_constraint=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
        default=InstrumentStatus.AVAILABLE,
        server_default=InstrumentStatus.AVAILABLE.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    location: Mapped["Location"] = relationship(back_populates="instruments")
    vendor: Mapped["Vendor"] = relationship(back_populates="instruments")
    type: Mapped["InstrumentType"] = relationship(back_populates="instruments")
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="instrument")

    @validates("name")
    def _set_normalized_name(self, key, value):
        self.normalized_name = normalize_name(value)
        return value


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        CheckConstraint("end_datetime > start_datetime", name="ck_reservations_end_after_start"),
        Index("ix_reservations_instrument_id", "instrument_id"),
        Index("ix_reservations_purpose_id", "reservation_purpose_id"),
        Index("ix_reservations_start_end", "start_datetime", "end_datetime"),
    )

    reservation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    instrument_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("instruments.instrument_id"), nullable=False
    )
    start_datetime: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    end_datetime: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    reservation_purpose_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("reservation_purposes.reservation_purpose_id"), nullable=False
    )
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    can_be_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    instrument: Mapped["Instrument"] = relationship(back_populates="reservations")
    purpose: Mapped["ReservationPurpose"] = relationship(back_populates="reservations")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_timestamp", "timestamp"),
    )

    audit_log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    action_type: Mapped[AuditActionType] = mapped_column(
        SAEnum(
            AuditActionType,
            name="audit_action_type",
            native_enum=True,
            create_constraint=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    entity_type: Mapped[AuditEntityType] = mapped_column(
        SAEnum(
            AuditEntityType,
            name="audit_entity_type",
            native_enum=True,
            create_constraint=False,
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        nullable=False,
    )
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
