"""
ORM model definitions for the Instrument Scheduler domain.

All models share the declarative `Base` defined in `app.models.database`.
This module is imported BY `database.py` (not the other way round) so that
`Base` exists before the models that use it are declared, while still
letting `database.py` be the single canonical import path other
components rely on (`from app.models.database import get_db`).
"""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.database import Base


class InstrumentStatus(str, enum.Enum):
    ACTIVE = "Active"
    DECOMMISSIONED = "Decommissioned"
    UNDER_MAINTENANCE = "UnderMaintenance"


class AuditActionType(str, enum.Enum):
    CREATE = "Create"
    UPDATE = "Update"
    STATUS_CHANGE = "StatusChange"
    SOFT_DELETE = "SoftDelete"
    RESERVATION_CREATED = "ReservationCreated"
    RESERVATION_OVERRIDDEN = "ReservationOverridden"


class AuditEntityType(str, enum.Enum):
    INSTRUMENT = "Instrument"
    LOCATION = "Location"
    VENDOR = "Vendor"
    TYPE = "Type"
    RESERVATION_PURPOSE = "ReservationPurpose"
    RESERVATION = "Reservation"


class Location(Base):
    __tablename__ = "locations"

    location_id: Mapped[int] = mapped_column(
        "LocationID", Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        "NormalizedName", String(120), nullable=False, unique=True
    )
    is_active: Mapped[bool] = mapped_column(
        "IsActive", Boolean, nullable=False, default=True, server_default="1"
    )

    instruments: Mapped[list["Instrument"]] = relationship(
        back_populates="location"
    )


class Vendor(Base):
    __tablename__ = "vendors"

    vendor_id: Mapped[int] = mapped_column(
        "VendorID", Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        "NormalizedName", String(120), nullable=False, unique=True
    )
    is_active: Mapped[bool] = mapped_column(
        "IsActive", Boolean, nullable=False, default=True, server_default="1"
    )

    instruments: Mapped[list["Instrument"]] = relationship(back_populates="vendor")


class Type(Base):
    __tablename__ = "types"

    type_id: Mapped[int] = mapped_column(
        "TypeID", Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        "NormalizedName", String(120), nullable=False, unique=True
    )
    is_active: Mapped[bool] = mapped_column(
        "IsActive", Boolean, nullable=False, default=True, server_default="1"
    )

    instruments: Mapped[list["Instrument"]] = relationship(back_populates="type")


class ReservationPurpose(Base):
    __tablename__ = "reservation_purposes"

    reservation_purpose_id: Mapped[int] = mapped_column(
        "ReservationPurposeID", Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False)
    normalized_name: Mapped[str] = mapped_column(
        "NormalizedName", String(120), nullable=False, unique=True
    )
    is_active: Mapped[bool] = mapped_column(
        "IsActive", Boolean, nullable=False, default=True, server_default="1"
    )

    reservations: Mapped[list["Reservation"]] = relationship(back_populates="purpose")


class Instrument(Base):
    __tablename__ = "instruments"

    instrument_id: Mapped[int] = mapped_column(
        "InstrumentID", Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column("Name", String(120), nullable=False)
    nickname: Mapped[str] = mapped_column("Nickname", String(120), nullable=False)
    location_id: Mapped[int] = mapped_column(
        "LocationID", Integer, ForeignKey("locations.LocationID"), nullable=False
    )
    vendor_id: Mapped[int] = mapped_column(
        "VendorID", Integer, ForeignKey("vendors.VendorID"), nullable=False
    )
    type_id: Mapped[int] = mapped_column(
        "TypeID", Integer, ForeignKey("types.TypeID"), nullable=False
    )
    asset_id: Mapped[str | None] = mapped_column("AssetID", String(120), nullable=True)
    color: Mapped[str | None] = mapped_column("Color", String(32), nullable=True)
    status: Mapped[InstrumentStatus] = mapped_column(
        "Status",
        Enum(
            InstrumentStatus,
            name="instrument_status",
            native_enum=True,
            create_type=False,
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
        default=InstrumentStatus.ACTIVE,
    )
    is_active: Mapped[bool] = mapped_column(
        "IsActive", Boolean, nullable=False, default=True, server_default="1"
    )
    is_favorite: Mapped[bool] = mapped_column(
        "IsFavorite", Boolean, nullable=False, default=False, server_default="0"
    )

    location: Mapped["Location"] = relationship(back_populates="instruments")
    vendor: Mapped["Vendor"] = relationship(back_populates="instruments")
    type: Mapped["Type"] = relationship(back_populates="instruments")
    reservations: Mapped[list["Reservation"]] = relationship(
        back_populates="instrument"
    )


class Reservation(Base):
    __tablename__ = "reservations"

    reservation_id: Mapped[int] = mapped_column(
        "ReservationID", Integer, primary_key=True, autoincrement=True
    )
    instrument_id: Mapped[int] = mapped_column(
        "InstrumentID",
        Integer,
        ForeignKey("instruments.InstrumentID"),
        nullable=False,
    )
    start_date_time: Mapped[datetime] = mapped_column(
        "StartDateTime", DateTime(timezone=True), nullable=False
    )
    end_date_time: Mapped[datetime] = mapped_column(
        "EndDateTime", DateTime(timezone=True), nullable=False
    )
    reservation_purpose_id: Mapped[int] = mapped_column(
        "ReservationPurposeID",
        Integer,
        ForeignKey("reservation_purposes.ReservationPurposeID"),
        nullable=False,
    )
    requested_by: Mapped[str] = mapped_column(
        "RequestedBy", String(120), nullable=False
    )
    can_be_overridden: Mapped[bool] = mapped_column(
        "CanBeOverridden", Boolean, nullable=False, default=False, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        "IsActive", Boolean, nullable=False, default=True, server_default="1"
    )

    instrument: Mapped["Instrument"] = relationship(back_populates="reservations")
    purpose: Mapped["ReservationPurpose"] = relationship(
        back_populates="reservations"
    )


class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_log_id: Mapped[int] = mapped_column(
        "AuditLogID", Integer, primary_key=True, autoincrement=True
    )
    actor: Mapped[str] = mapped_column("Actor", String(120), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        "Timestamp", DateTime(timezone=True), nullable=False
    )
    action_type: Mapped[AuditActionType] = mapped_column(
        "ActionType",
        Enum(
            AuditActionType,
            name="audit_action_type",
            native_enum=True,
            create_type=False,
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
    )
    entity_type: Mapped[AuditEntityType] = mapped_column(
        "EntityType",
        Enum(
            AuditEntityType,
            name="audit_entity_type",
            native_enum=True,
            create_type=False,
            values_callable=lambda e: [member.value for member in e],
        ),
        nullable=False,
    )
    entity_id: Mapped[int] = mapped_column("EntityID", Integer, nullable=False)
    description: Mapped[str] = mapped_column("Description", Text, nullable=False)
