"""Business logic for master data: Location, Vendor, Type, ReservationPurpose.

Handles normalized-name duplicate detection, soft-delete with usage-count
warnings, and audit logging for every mutation.
"""
from __future__ import annotations

import re

from sqlalchemy.orm import Session

from app.contracts import (
    DuplicateMasterDataError,
    LocationDTO,
    NotFoundError,
    ReservationPurposeDTO,
    TypeDTO,
    UsageWarningDTO,
    VendorDTO,
)
from app.models import (
    AuditActionType,
    AuditEntityType,
    Instrument,
    InstrumentStatus,
    Location,
    Reservation,
    ReservationPurpose,
    Type,
    Vendor,
)
from app.services.audit_log import AuditLogService


def _normalize(name: str) -> str:
    """Trim, lowercase, and collapse internal whitespace to single spaces."""
    return re.sub(r"\s+", " ", name.strip()).lower()


class MasterDataService:
    """CRUD + soft-delete for master data entities with duplicate detection."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._audit = AuditLogService(db)

    # ------------------------------------------------------------------
    # Generic helpers
    # ------------------------------------------------------------------
    def _check_duplicate(self, model, name: str, exclude_id: int | None, id_field: str) -> None:
        normalized = _normalize(name)
        query = self._db.query(model).filter(model.is_active.is_(True))
        for existing in query.all():
            if _normalize(existing.name) == normalized:
                if exclude_id is not None and getattr(existing, id_field) == exclude_id:
                    continue
                raise DuplicateMasterDataError(
                    f"A record named '{existing.name}' already exists"
                )

    @staticmethod
    def _validate_name(name: str) -> str:
        cleaned = (name or "").strip()
        if not cleaned:
            raise ValueError("Name is required")
        return cleaned

    # ------------------------------------------------------------------
    # Location
    # ------------------------------------------------------------------
    def create_location(self, name: str) -> LocationDTO:
        cleaned = self._validate_name(name)
        self._check_duplicate(Location, cleaned, None, "location_id")
        location = Location(name=cleaned, is_active=True)
        self._db.add(location)
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.LOCATION,
            entity_id=location.location_id,
            description=f"Created location '{location.name}'",
        )
        self._db.commit()
        return LocationDTO(location_id=location.location_id, name=location.name, is_active=location.is_active)

    def update_location(self, location_id: int, name: str) -> LocationDTO:
        location = self._db.query(Location).filter(Location.location_id == location_id).one_or_none()
        if location is None:
            raise NotFoundError(f"Location {location_id} not found")
        cleaned = self._validate_name(name)
        self._check_duplicate(Location, cleaned, location_id, "location_id")
        old_name = location.name
        location.name = cleaned
        self._db.flush()
        if old_name != cleaned:
            self._audit.log(
                actor="Unknown",
                action_type=AuditActionType.UPDATE,
                entity_type=AuditEntityType.LOCATION,
                entity_id=location.location_id,
                description=f"name: '{old_name}' -> '{cleaned}'",
            )
        self._db.commit()
        return LocationDTO(location_id=location.location_id, name=location.name, is_active=location.is_active)

    def deactivate_location(self, location_id: int) -> UsageWarningDTO:
        location = self._db.query(Location).filter(Location.location_id == location_id).one_or_none()
        if location is None:
            raise NotFoundError(f"Location {location_id} not found")
        usage_count = (
            self._db.query(Instrument)
            .filter(Instrument.location_id == location_id, Instrument.is_active.is_(True))
            .count()
        )
        location.is_active = False
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.LOCATION,
            entity_id=location.location_id,
            description=f"Deactivated location '{location.name}' (used by {usage_count} active instruments)",
        )
        self._db.commit()
        message = (
            f"{usage_count} active instrument(s) use this location."
            if usage_count
            else "No active instruments use this location."
        )
        return UsageWarningDTO(usage_count=usage_count, message=message)

    def reactivate_location(self, location_id: int) -> LocationDTO:
        location = self._db.query(Location).filter(Location.location_id == location_id).one_or_none()
        if location is None:
            raise NotFoundError(f"Location {location_id} not found")
        location.is_active = True
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.UPDATE,
            entity_type=AuditEntityType.LOCATION,
            entity_id=location.location_id,
            description=f"Reactivated location '{location.name}'",
        )
        self._db.commit()
        return LocationDTO(location_id=location.location_id, name=location.name, is_active=location.is_active)

    def list_locations(self, include_inactive: bool) -> list[LocationDTO]:
        query = self._db.query(Location)
        if not include_inactive:
            query = query.filter(Location.is_active.is_(True))
        query = query.order_by(Location.name.asc())
        return [
            LocationDTO(location_id=loc.location_id, name=loc.name, is_active=loc.is_active)
            for loc in query.all()
        ]

    # ------------------------------------------------------------------
    # Vendor
    # ------------------------------------------------------------------
    def create_vendor(self, name: str) -> VendorDTO:
        cleaned = self._validate_name(name)
        self._check_duplicate(Vendor, cleaned, None, "vendor_id")
        vendor = Vendor(name=cleaned, is_active=True)
        self._db.add(vendor)
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.VENDOR,
            entity_id=vendor.vendor_id,
            description=f"Created vendor '{vendor.name}'",
        )
        self._db.commit()
        return VendorDTO(vendor_id=vendor.vendor_id, name=vendor.name, is_active=vendor.is_active)

    def update_vendor(self, vendor_id: int, name: str) -> VendorDTO:
        vendor = self._db.query(Vendor).filter(Vendor.vendor_id == vendor_id).one_or_none()
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found")
        cleaned = self._validate_name(name)
        self._check_duplicate(Vendor, cleaned, vendor_id, "vendor_id")
        old_name = vendor.name
        vendor.name = cleaned
        self._db.flush()
        if old_name != cleaned:
            self._audit.log(
                actor="Unknown",
                action_type=AuditActionType.UPDATE,
                entity_type=AuditEntityType.VENDOR,
                entity_id=vendor.vendor_id,
                description=f"name: '{old_name}' -> '{cleaned}'",
            )
        self._db.commit()
        return VendorDTO(vendor_id=vendor.vendor_id, name=vendor.name, is_active=vendor.is_active)

    def deactivate_vendor(self, vendor_id: int) -> UsageWarningDTO:
        vendor = self._db.query(Vendor).filter(Vendor.vendor_id == vendor_id).one_or_none()
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found")
        usage_count = (
            self._db.query(Instrument)
            .filter(Instrument.vendor_id == vendor_id, Instrument.is_active.is_(True))
            .count()
        )
        vendor.is_active = False
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.VENDOR,
            entity_id=vendor.vendor_id,
            description=f"Deactivated vendor '{vendor.name}' (used by {usage_count} active instruments)",
        )
        self._db.commit()
        message = (
            f"{usage_count} active instrument(s) use this vendor."
            if usage_count
            else "No active instruments use this vendor."
        )
        return UsageWarningDTO(usage_count=usage_count, message=message)

    def list_vendors(self, include_inactive: bool) -> list[VendorDTO]:
        query = self._db.query(Vendor)
        if not include_inactive:
            query = query.filter(Vendor.is_active.is_(True))
        query = query.order_by(Vendor.name.asc())
        return [
            VendorDTO(vendor_id=v.vendor_id, name=v.name, is_active=v.is_active) for v in query.all()
        ]

    # ------------------------------------------------------------------
    # Type
    # ------------------------------------------------------------------
    def create_type(self, name: str) -> TypeDTO:
        cleaned = self._validate_name(name)
        self._check_duplicate(Type, cleaned, None, "type_id")
        type_ = Type(name=cleaned, is_active=True)
        self._db.add(type_)
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.TYPE,
            entity_id=type_.type_id,
            description=f"Created type '{type_.name}'",
        )
        self._db.commit()
        return TypeDTO(type_id=type_.type_id, name=type_.name, is_active=type_.is_active)

    def update_type(self, type_id: int, name: str) -> TypeDTO:
        type_ = self._db.query(Type).filter(Type.type_id == type_id).one_or_none()
        if type_ is None:
            raise NotFoundError(f"Type {type_id} not found")
        cleaned = self._validate_name(name)
        self._check_duplicate(Type, cleaned, type_id, "type_id")
        old_name = type_.name
        type_.name = cleaned
        self._db.flush()
        if old_name != cleaned:
            self._audit.log(
                actor="Unknown",
                action_type=AuditActionType.UPDATE,
                entity_type=AuditEntityType.TYPE,
                entity_id=type_.type_id,
                description=f"name: '{old_name}' -> '{cleaned}'",
            )
        self._db.commit()
        return TypeDTO(type_id=type_.type_id, name=type_.name, is_active=type_.is_active)

    def deactivate_type(self, type_id: int) -> UsageWarningDTO:
        type_ = self._db.query(Type).filter(Type.type_id == type_id).one_or_none()
        if type_ is None:
            raise NotFoundError(f"Type {type_id} not found")
        usage_count = (
            self._db.query(Instrument)
            .filter(Instrument.type_id == type_id, Instrument.is_active.is_(True))
            .count()
        )
        type_.is_active = False
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.TYPE,
            entity_id=type_.type_id,
            description=f"Deactivated type '{type_.name}' (used by {usage_count} active instruments)",
        )
        self._db.commit()
        message = (
            f"{usage_count} active instrument(s) use this type."
            if usage_count
            else "No active instruments use this type."
        )
        return UsageWarningDTO(usage_count=usage_count, message=message)

    def list_types(self, include_inactive: bool) -> list[TypeDTO]:
        query = self._db.query(Type)
        if not include_inactive:
            query = query.filter(Type.is_active.is_(True))
        query = query.order_by(Type.name.asc())
        return [TypeDTO(type_id=t.type_id, name=t.name, is_active=t.is_active) for t in query.all()]

    # ------------------------------------------------------------------
    # ReservationPurpose
    # ------------------------------------------------------------------
    def create_purpose(self, name: str) -> ReservationPurposeDTO:
        cleaned = self._validate_name(name)
        self._check_duplicate(ReservationPurpose, cleaned, None, "reservation_purpose_id")
        purpose = ReservationPurpose(name=cleaned, is_active=True)
        self._db.add(purpose)
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.RESERVATION_PURPOSE,
            entity_id=purpose.reservation_purpose_id,
            description=f"Created reservation purpose '{purpose.name}'",
        )
        self._db.commit()
        return ReservationPurposeDTO(
            reservation_purpose_id=purpose.reservation_purpose_id,
            name=purpose.name,
            is_active=purpose.is_active,
        )

    def update_purpose(self, purpose_id: int, name: str) -> ReservationPurposeDTO:
        purpose = (
            self._db.query(ReservationPurpose)
            .filter(ReservationPurpose.reservation_purpose_id == purpose_id)
            .one_or_none()
        )
        if purpose is None:
            raise NotFoundError(f"ReservationPurpose {purpose_id} not found")
        cleaned = self._validate_name(name)
        self._check_duplicate(ReservationPurpose, cleaned, purpose_id, "reservation_purpose_id")
        old_name = purpose.name
        purpose.name = cleaned
        self._db.flush()
        if old_name != cleaned:
            self._audit.log(
                actor="Unknown",
                action_type=AuditActionType.UPDATE,
                entity_type=AuditEntityType.RESERVATION_PURPOSE,
                entity_id=purpose.reservation_purpose_id,
                description=f"name: '{old_name}' -> '{cleaned}'",
            )
        self._db.commit()
        return ReservationPurposeDTO(
            reservation_purpose_id=purpose.reservation_purpose_id,
            name=purpose.name,
            is_active=purpose.is_active,
        )

    def deactivate_purpose(self, purpose_id: int) -> UsageWarningDTO:
        purpose = (
            self._db.query(ReservationPurpose)
            .filter(ReservationPurpose.reservation_purpose_id == purpose_id)
            .one_or_none()
        )
        if purpose is None:
            raise NotFoundError(f"ReservationPurpose {purpose_id} not found")
        usage_count = (
            self._db.query(Reservation)
            .filter(
                Reservation.reservation_purpose_id == purpose_id,
                Reservation.is_active.is_(True),
            )
            .count()
        )
        purpose.is_active = False
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.RESERVATION_PURPOSE,
            entity_id=purpose.reservation_purpose_id,
            description=f"Deactivated purpose '{purpose.name}' (used by {usage_count} active reservations)",
        )
        self._db.commit()
        message = (
            f"{usage_count} active reservation(s) use this purpose."
            if usage_count
            else "No active reservations use this purpose."
        )
        return UsageWarningDTO(usage_count=usage_count, message=message)

    def reactivate_purpose(self, purpose_id: int) -> ReservationPurposeDTO:
        purpose = (
            self._db.query(ReservationPurpose)
            .filter(ReservationPurpose.reservation_purpose_id == purpose_id)
            .one_or_none()
        )
        if purpose is None:
            raise NotFoundError(f"ReservationPurpose {purpose_id} not found")
        purpose.is_active = True
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.UPDATE,
            entity_type=AuditEntityType.RESERVATION_PURPOSE,
            entity_id=purpose.reservation_purpose_id,
            description=f"Reactivated purpose '{purpose.name}'",
        )
        self._db.commit()
        return ReservationPurposeDTO(
            reservation_purpose_id=purpose.reservation_purpose_id,
            name=purpose.name,
            is_active=purpose.is_active,
        )

    def list_purposes(self, include_inactive: bool) -> list[ReservationPurposeDTO]:
        query = self._db.query(ReservationPurpose)
        if not include_inactive:
            query = query.filter(ReservationPurpose.is_active.is_(True))
        query = query.order_by(ReservationPurpose.name.asc())
        return [
            ReservationPurposeDTO(
                reservation_purpose_id=p.reservation_purpose_id, name=p.name, is_active=p.is_active
            )
            for p in query.all()
        ]
