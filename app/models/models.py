"""
ORM model declarations for all persisted entities and audit records.

Master data tables (Location, Vendor, InstrumentType, ReservationPurpose)
enforce a case-insensitive unique constraint on `name` via a functional
unique index on lower(name), and support soft-delete via `is_active`.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base
from app.models.enums import AuditActionType, AuditEntityType, InstrumentStatus
from app.models.types import UTCDateTime

# Enum column types. `native_enum=True` + `create_type=False` on Postgres
# means the migration is fully responsible for creating the underlying
# CREATE TYPE, avoiding a duplicate/unguarded CREATE TYPE from create_table.
_instrument_status_enum = Enum(
    InstrumentStatus,
    name="instrument_status",
    native_enum=True,
    create_constraint=False,
    validate_strings=True,
)
_audit_action_type_enum = Enum(
    AuditActionType,
    name="audit_action_type",
    native_enum=True,
    create_constraint=False,
    validate_strings=True,
)
_audit_entity_type_enum = Enum(
    AuditEntityType,
    name="audit_entity_type",
    native_enum=True,
    create_constraint=False,
    validate_strings=True,
)


class Location(Base):
    __tablename__ = "locations"

    location_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    instruments: Mapped[list["Instrument"]] = relationship(back_populates="location")

    __table_args__ = (
        Index("uq_locations_name_lower", func.lower(name), unique=True),
    )


class Vendor(Base):
    __tablename__ = "vendors"

    vendor_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    instruments: Mapped[list["Instrument"]] = relationship(back_populates="vendor")

    __table_args__ = (
        Index("uq_vendors_name_lower", func.lower(name), unique=True),
    )


class InstrumentType(Base):
    __tablename__ = "instrument_types"

    type_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    instruments: Mapped[list["Instrument"]] = relationship(back_populates="type")

    __table_args__ = (
        Index("uq_instrument_types_name_lower", func.lower(name), unique=True),
    )


class ReservationPurpose(Base):
    __tablename__ = "reservation_purposes"

    reservation_purpose_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    reservations: Mapped[list["Reservation"]] = relationship(back_populates="purpose")

    __table_args__ = (
        Index("uq_reservation_purposes_name_lower", func.lower(name), unique=True),
    )


class Instrument(Base):
    __tablename__ = "instruments"

    instrument_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
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
        _instrument_status_enum, nullable=False, default=InstrumentStatus.AVAILABLE,
        server_default=InstrumentStatus.AVAILABLE.value,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    location: Mapped["Location"] = relationship(back_populates="instruments")
    vendor: Mapped["Vendor"] = relationship(back_populates="instruments")
    type: Mapped["InstrumentType"] = relationship(back_populates="instruments")
    reservations: Mapped[list["Reservation"]] = relationship(back_populates="instrument")

    __table_args__ = (
        Index("uq_instruments_name_lower", func.lower(name), unique=True),
    )


class Reservation(Base):
    __tablename__ = "reservations"

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
    can_be_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    instrument: Mapped["Instrument"] = relationship(back_populates="reservations")
    purpose: Mapped["ReservationPurpose"] = relationship(back_populates="reservations")

    __table_args__ = (
        CheckConstraint("end_datetime > start_datetime", name="ck_reservations_end_after_start"),
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        UTCDateTime, nullable=False, default=lambda: __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        )
    )
    action_type: Mapped[AuditActionType] = mapped_column(_audit_action_type_enum, nullable=False)
    entity_type: Mapped[AuditEntityType] = mapped_column(_audit_entity_type_enum, nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(1000), nullable=False)
