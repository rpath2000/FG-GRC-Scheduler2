"""Business-logic services for instruments, reservations, master data, and audit logging.

This package exposes four services used by the REST/web layer:

- InstrumentService: CRUD, status transitions, soft-delete, favorites, duplicate detection.
- ReservationService: creation with validation, conflict detection/override, listing.
- MasterDataService: CRUD + soft-delete for Location, Vendor, InstrumentType, ReservationPurpose.
- AuditService: append-only audit log recording and listing.

All services accept a SQLAlchemy ``Session`` at construction time and are stateless
otherwise; callers are responsible for constructing a fresh instance per request/call
using a session obtained from ``app.models.get_db``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.contracts import (
    ConflictError,
    DuplicateError,
    InstrumentCreateDTO,
    InstrumentDTO,
    InstrumentFilterDTO,
    InstrumentUpdateDTO,
    InvalidStatusError,
    NotFoundError,
    ValidationError,
    LocationDTO,
    VendorDTO,
    InstrumentTypeDTO,
    ReservationPurposeDTO,
    ReservationCreateDTO,
    ReservationDTO,
    ReservationResultDTO,
    AuditLogDTO,
)
from app.models import (
    Instrument,
    InstrumentStatus,
    Location,
    Vendor,
    InstrumentType,
    ReservationPurpose,
    Reservation,
    AuditLog,
    AuditActionType,
    AuditEntityType,
)

RESERVATION_SLOT_MINUTES = 30


def _normalize(value: str) -> str:
    """Normalize a name for duplicate comparison: trim, collapse whitespace, lowercase."""
    return re.sub(r"\s+", " ", (value or "").strip()).lower()


class AuditService:
    """Append-only audit logging service."""

    def __init__(self, db: Session):
        self.db = db

    def log_action(
        self,
        actor: str,
        action_type: str,
        entity_type: str,
        entity_id: int,
        description: str,
    ) -> None:
        """Record a single audit log entry.

        ``actor`` defaults to 'Unknown' when blank/whitespace-only.
        Raises ValidationError if action_type or entity_type are not recognized values.
        """
        normalized_actor = actor.strip() if actor and actor.strip() else "Unknown"

        try:
            action_enum = AuditActionType(action_type)
        except ValueError as exc:
            raise ValidationError(f"Invalid action_type: {action_type}") from exc

        try:
            entity_enum = AuditEntityType(entity_type)
        except ValueError as exc:
            raise ValidationError(f"Invalid entity_type: {entity_type}") from exc

        entry = AuditLog(
            actor=normalized_actor,
            timestamp=datetime.utcnow(),
            action_type=action_enum,
            entity_type=entity_enum,
            entity_id=entity_id,
            description=description or "",
        )
        self.db.add(entry)
        self.db.flush()

    def list_entries(self) -> list[AuditLogDTO]:
        """List all audit log entries, newest first."""
        rows = (
            self.db.query(AuditLog)
            .order_by(AuditLog.timestamp.desc(), AuditLog.audit_log_id.desc())
            .all()
        )
        return [self._to_dto(row) for row in rows]

    @staticmethod
    def _to_dto(row: AuditLog) -> AuditLogDTO:
        return AuditLogDTO(
            audit_log_id=row.audit_log_id,
            actor=row.actor,
            timestamp=row.timestamp,
            action_type=row.action_type.value if hasattr(row.action_type, "value") else row.action_type,
            entity_type=row.entity_type.value if hasattr(row.entity_type, "value") else row.entity_type,
            entity_id=row.entity_id,
            description=row.description,
        )


class InstrumentService:
    """Business logic for instrument CRUD, status changes, favorites, and soft-delete."""

    def __init__(self, db: Session):
        self.db = db

    def _get_active_locations_map(self) -> dict[int, str]:
        return {loc.location_id: loc.name for loc in self.db.query(Location).all()}

    def _to_dto(self, instrument: Instrument) -> InstrumentDTO:
        location = self.db.query(Location).filter(Location.location_id == instrument.location_id).first()
        vendor = self.db.query(Vendor).filter(Vendor.vendor_id == instrument.vendor_id).first()
        itype = self.db.query(InstrumentType).filter(InstrumentType.type_id == instrument.type_id).first()
        return InstrumentDTO(
            instrument_id=instrument.instrument_id,
            name=instrument.name,
            nickname=instrument.nickname,
            location_id=instrument.location_id,
            location_name=location.name if location else "",
            vendor_id=instrument.vendor_id,
            vendor_name=vendor.name if vendor else "",
            type_id=instrument.type_id,
            type_name=itype.name if itype else "",
            asset_id=instrument.asset_id,
            color=instrument.color,
            status=instrument.status.value if hasattr(instrument.status, "value") else instrument.status,
            is_active=instrument.is_active,
            is_favorite=instrument.is_favorite,
        )

    def _check_duplicate(
        self, name: str, nickname: str, exclude_instrument_id: Optional[int] = None
    ) -> None:
        norm_name = _normalize(name)
        norm_nickname = _normalize(nickname)
        candidates = self.db.query(Instrument).all()
        for candidate in candidates:
            if exclude_instrument_id is not None and candidate.instrument_id == exclude_instrument_id:
                continue
            if (
                _normalize(candidate.name) == norm_name
                and _normalize(candidate.nickname) == norm_nickname
            ):
                raise DuplicateError(
                    f"An instrument with name '{name}' and nickname '{nickname}' already exists."
                )

    def create(self, data: InstrumentCreateDTO) -> InstrumentDTO:
        """Create a new instrument. Raises DuplicateError on normalized name+nickname clash."""
        if not data.name or not data.name.strip():
            raise ValidationError("Instrument name is required.")
        if not data.nickname or not data.nickname.strip():
            raise ValidationError("Instrument nickname is required.")

        self._check_duplicate(data.name, data.nickname)

        instrument = Instrument(
            name=data.name.strip(),
            nickname=data.nickname.strip(),
            location_id=data.location_id,
            vendor_id=data.vendor_id,
            type_id=data.type_id,
            asset_id=data.asset_id,
            color=data.color,
            status=InstrumentStatus.AVAILABLE,
            is_active=True,
            is_favorite=False,
        )
        self.db.add(instrument)
        self.db.flush()
        return self._to_dto(instrument)

    def update(self, instrument_id: int, data: InstrumentUpdateDTO) -> InstrumentDTO:
        """Update an existing instrument. Raises NotFoundError / DuplicateError as applicable."""
        instrument = self.db.query(Instrument).filter(Instrument.instrument_id == instrument_id).first()
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found.")

        if not data.name or not data.name.strip():
            raise ValidationError("Instrument name is required.")
        if not data.nickname or not data.nickname.strip():
            raise ValidationError("Instrument nickname is required.")

        self._check_duplicate(data.name, data.nickname, exclude_instrument_id=instrument_id)

        instrument.name = data.name.strip()
        instrument.nickname = data.nickname.strip()
        instrument.location_id = data.location_id
        instrument.vendor_id = data.vendor_id
        instrument.type_id = data.type_id
        instrument.asset_id = data.asset_id
        instrument.color = data.color
        instrument.is_active = data.is_active
        self.db.flush()
        return self._to_dto(instrument)

    def get_by_id(self, instrument_id: int) -> InstrumentDTO:
        """Fetch a single instrument by id. Raises NotFoundError if absent."""
        instrument = self.db.query(Instrument).filter(Instrument.instrument_id == instrument_id).first()
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found.")
        return self._to_dto(instrument)

    def list_active(self, filters: InstrumentFilterDTO) -> list[InstrumentDTO]:
        """List active instruments matching optional filters."""
        query = self.db.query(Instrument).filter(Instrument.is_active.is_(True))

        if filters is not None:
            if filters.nickname:
                query = query.filter(Instrument.nickname.ilike(f"%{filters.nickname}%"))
            if filters.location_id is not None:
                query = query.filter(Instrument.location_id == filters.location_id)
            if filters.vendor_id is not None:
                query = query.filter(Instrument.vendor_id == filters.vendor_id)
            if filters.type_id is not None:
                query = query.filter(Instrument.type_id == filters.type_id)
            if filters.favorites_only:
                query = query.filter(Instrument.is_favorite.is_(True))

        instruments = query.order_by(Instrument.name.asc()).all()
        return [self._to_dto(i) for i in instruments]

    def list_schedulable(self) -> list[InstrumentDTO]:
        """List active instruments that are not decommissioned/under maintenance."""
        instruments = (
            self.db.query(Instrument)
            .filter(Instrument.is_active.is_(True))
            .filter(Instrument.status == InstrumentStatus.AVAILABLE)
            .order_by(Instrument.name.asc())
            .all()
        )
        return [self._to_dto(i) for i in instruments]

    def change_status(self, instrument_id: int, status: str) -> InstrumentDTO:
        """Change an instrument's status. Raises NotFoundError/ValidationError."""
        instrument = self.db.query(Instrument).filter(Instrument.instrument_id == instrument_id).first()
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found.")
        try:
            new_status = InstrumentStatus(status)
        except ValueError as exc:
            raise ValidationError(f"Invalid status: {status}") from exc
        instrument.status = new_status
        self.db.flush()
        return self._to_dto(instrument)

    def soft_delete(self, instrument_id: int) -> None:
        """Soft-delete (deactivate) an instrument. Raises NotFoundError if absent."""
        instrument = self.db.query(Instrument).filter(Instrument.instrument_id == instrument_id).first()
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found.")
        instrument.is_active = False
        self.db.flush()

    def toggle_favorite(self, instrument_id: int) -> InstrumentDTO:
        """Toggle an instrument's favorite flag. Raises NotFoundError if absent."""
        instrument = self.db.query(Instrument).filter(Instrument.instrument_id == instrument_id).first()
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found.")
        instrument.is_favorite = not instrument.is_favorite
        self.db.flush()
        return self._to_dto(instrument)


class ReservationService:
    """Business logic for reservation creation with validation and conflict handling."""

    def __init__(self, db: Session):
        self.db = db
        self._audit = AuditService(db)

    def _to_dto(self, reservation: Reservation) -> ReservationDTO:
        instrument = (
            self.db.query(Instrument)
            .filter(Instrument.instrument_id == reservation.instrument_id)
            .first()
        )
        purpose = (
            self.db.query(ReservationPurpose)
            .filter(ReservationPurpose.reservation_purpose_id == reservation.reservation_purpose_id)
            .first()
        )
        return ReservationDTO(
            reservation_id=reservation.reservation_id,
            instrument_id=reservation.instrument_id,
            instrument_name=instrument.name if instrument else "",
            start_datetime=reservation.start_datetime,
            end_datetime=reservation.end_datetime,
            reservation_purpose_id=reservation.reservation_purpose_id,
            purpose_name=purpose.name if purpose else "",
            requested_by=reservation.requested_by,
            can_be_overridden=reservation.can_be_overridden,
        )

    @staticmethod
    def _is_on_30_min_boundary(dt: datetime) -> bool:
        return dt.second == 0 and dt.microsecond == 0 and dt.minute % RESERVATION_SLOT_MINUTES == 0

    def create(self, data: ReservationCreateDTO) -> ReservationResultDTO:
        """Create a reservation, validating time boundaries and handling conflicts.

        Raises:
            ValidationError: end <= start, or times not on a 30-minute boundary,
                or the instrument does not exist / is not schedulable.
            ConflictError: a non-overridable conflicting reservation exists.
        """
        if data.end_datetime <= data.start_datetime:
            raise ValidationError("End time must be after start time.")

        if not self._is_on_30_min_boundary(data.start_datetime):
            raise ValidationError("Start time must be on a 30-minute boundary.")
        if not self._is_on_30_min_boundary(data.end_datetime):
            raise ValidationError("End time must be on a 30-minute boundary.")

        instrument = (
            self.db.query(Instrument)
            .filter(Instrument.instrument_id == data.instrument_id)
            .first()
        )
        if instrument is None:
            raise NotFoundError(f"Instrument {data.instrument_id} not found.")
        if not instrument.is_active:
            raise InvalidStatusError("Instrument is inactive and cannot be scheduled.")
        if instrument.status != InstrumentStatus.AVAILABLE:
            raise InvalidStatusError(
                f"Instrument is {instrument.status.value if hasattr(instrument.status, 'value') else instrument.status} "
                "and cannot be scheduled."
            )

        purpose = (
            self.db.query(ReservationPurpose)
            .filter(ReservationPurpose.reservation_purpose_id == data.reservation_purpose_id)
            .first()
        )
        if purpose is None:
            raise NotFoundError(f"Reservation purpose {data.reservation_purpose_id} not found.")

        conflicts = (
            self.db.query(Reservation)
            .filter(Reservation.instrument_id == data.instrument_id)
            .filter(Reservation.is_active.is_(True))
            .filter(
                and_(
                    Reservation.start_datetime < data.end_datetime,
                    Reservation.end_datetime > data.start_datetime,
                )
            )
            .all()
        )

        non_overridable = [c for c in conflicts if not c.can_be_overridden]
        if non_overridable:
            names = ", ".join(
                f"reservation #{c.reservation_id} ({c.start_datetime.isoformat()} - {c.end_datetime.isoformat()})"
                for c in non_overridable
            )
            raise ConflictError(
                f"Requested time conflicts with non-overridable reservation(s): {names}"
            )

        overridden_ids: list[int] = []
        requested_by = data.requested_by.strip() if data.requested_by and data.requested_by.strip() else "Unknown"

        for conflict in conflicts:
            conflict.is_active = False
            overridden_ids.append(conflict.reservation_id)

        reservation = Reservation(
            instrument_id=data.instrument_id,
            start_datetime=data.start_datetime,
            end_datetime=data.end_datetime,
            reservation_purpose_id=data.reservation_purpose_id,
            requested_by=requested_by,
            can_be_overridden=data.can_be_overridden,
            is_active=True,
        )
        self.db.add(reservation)
        self.db.flush()

        self._audit.log_action(
            actor=requested_by,
            action_type=AuditActionType.CREATE.value,
            entity_type=AuditEntityType.RESERVATION.value,
            entity_id=reservation.reservation_id,
            description=f"Created reservation for instrument {data.instrument_id} "
            f"from {data.start_datetime.isoformat()} to {data.end_datetime.isoformat()}.",
        )

        if overridden_ids:
            ids_text = ", ".join(str(i) for i in overridden_ids)
            self._audit.log_action(
                actor=requested_by,
                action_type=AuditActionType.OVERRIDE.value,
                entity_type=AuditEntityType.RESERVATION.value,
                entity_id=reservation.reservation_id,
                description=f"Overrode and soft-deleted reservation(s) [{ids_text}] "
                f"to create reservation {reservation.reservation_id}.",
            )

        return ReservationResultDTO(
            reservation=self._to_dto(reservation),
            overridden_ids=overridden_ids,
        )

    def list_by_instrument_and_range(
        self, instrument_ids: list[int], start: datetime, end: datetime
    ) -> list[ReservationDTO]:
        """List active reservations for the given instruments overlapping [start, end]."""
        query = (
            self.db.query(Reservation)
            .filter(Reservation.is_active.is_(True))
            .filter(
                and_(
                    Reservation.start_datetime < end,
                    Reservation.end_datetime > start,
                )
            )
        )
        if instrument_ids:
            query = query.filter(Reservation.instrument_id.in_(instrument_ids))

        reservations = query.order_by(Reservation.start_datetime.asc()).all()
        return [self._to_dto(r) for r in reservations]


class MasterDataService:
    """CRUD + soft-delete for Location, Vendor, InstrumentType, ReservationPurpose."""

    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- Location

    @staticmethod
    def _location_to_dto(loc: Location) -> LocationDTO:
        return LocationDTO(location_id=loc.location_id, name=loc.name, is_active=loc.is_active)

    def _check_duplicate_name(self, model, name: str, id_field: str, exclude_id: Optional[int] = None) -> None:
        norm = _normalize(name)
        rows = self.db.query(model).all()
        for row in rows:
            if exclude_id is not None and getattr(row, id_field) == exclude_id:
                continue
            if _normalize(row.name) == norm:
                raise DuplicateError(f"'{name}' already exists.")

    def create_location(self, name: str) -> LocationDTO:
        if not name or not name.strip():
            raise ValidationError("Location name is required.")
        self._check_duplicate_name(Location, name, "location_id")
        loc = Location(name=name.strip(), is_active=True)
        self.db.add(loc)
        self.db.flush()
        return self._location_to_dto(loc)

    def update_location(self, location_id: int, name: str) -> LocationDTO:
        loc = self.db.query(Location).filter(Location.location_id == location_id).first()
        if loc is None:
            raise NotFoundError(f"Location {location_id} not found.")
        if not name or not name.strip():
            raise ValidationError("Location name is required.")
        self._check_duplicate_name(Location, name, "location_id", exclude_id=location_id)
        loc.name = name.strip()
        self.db.flush()
        return self._location_to_dto(loc)

    def list_locations(self, active_only: bool) -> list[LocationDTO]:
        query = self.db.query(Location)
        if active_only:
            query = query.filter(Location.is_active.is_(True))
        rows = query.order_by(Location.name.asc()).all()
        return [self._location_to_dto(r) for r in rows]

    def deactivate_location(self, location_id: int) -> int:
        """Soft-delete a location, returning the count of active instruments using it."""
        loc = self.db.query(Location).filter(Location.location_id == location_id).first()
        if loc is None:
            raise NotFoundError(f"Location {location_id} not found.")
        usage_count = (
            self.db.query(Instrument)
            .filter(Instrument.location_id == location_id)
            .filter(Instrument.is_active.is_(True))
            .count()
        )
        loc.is_active = False
        self.db.flush()
        return usage_count

    def reactivate_location(self, location_id: int) -> LocationDTO:
        loc = self.db.query(Location).filter(Location.location_id == location_id).first()
        if loc is None:
            raise NotFoundError(f"Location {location_id} not found.")
        loc.is_active = True
        self.db.flush()
        return self._location_to_dto(loc)

    # ------------------------------------------------------------------ Vendor

    @staticmethod
    def _vendor_to_dto(v: Vendor) -> VendorDTO:
        return VendorDTO(vendor_id=v.vendor_id, name=v.name, is_active=v.is_active)

    def create_vendor(self, name: str) -> VendorDTO:
        if not name or not name.strip():
            raise ValidationError("Vendor name is required.")
        self._check_duplicate_name(Vendor, name, "vendor_id")
        vendor = Vendor(name=name.strip(), is_active=True)
        self.db.add(vendor)
        self.db.flush()
        return self._vendor_to_dto(vendor)

    def update_vendor(self, vendor_id: int, name: str) -> VendorDTO:
        vendor = self.db.query(Vendor).filter(Vendor.vendor_id == vendor_id).first()
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found.")
        if not name or not name.strip():
            raise ValidationError("Vendor name is required.")
        self._check_duplicate_name(Vendor, name, "vendor_id", exclude_id=vendor_id)
        vendor.name = name.strip()
        self.db.flush()
        return self._vendor_to_dto(vendor)

    def list_vendors(self, active_only: bool) -> list[VendorDTO]:
        query = self.db.query(Vendor)
        if active_only:
            query = query.filter(Vendor.is_active.is_(True))
        rows = query.order_by(Vendor.name.asc()).all()
        return [self._vendor_to_dto(r) for r in rows]

    def deactivate_vendor(self, vendor_id: int) -> int:
        """Soft-delete a vendor, returning the count of active instruments using it."""
        vendor = self.db.query(Vendor).filter(Vendor.vendor_id == vendor_id).first()
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found.")
        usage_count = (
            self.db.query(Instrument)
            .filter(Instrument.vendor_id == vendor_id)
            .filter(Instrument.is_active.is_(True))
            .count()
        )
        vendor.is_active = False
        self.db.flush()
        return usage_count

    def reactivate_vendor(self, vendor_id: int) -> VendorDTO:
        vendor = self.db.query(Vendor).filter(Vendor.vendor_id == vendor_id).first()
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found.")
        vendor.is_active = True
        self.db.flush()
        return self._vendor_to_dto(vendor)

    # ------------------------------------------------------------ InstrumentType

    @staticmethod
    def _type_to_dto(t: InstrumentType) -> InstrumentTypeDTO:
        return InstrumentTypeDTO(type_id=t.type_id, name=t.name, is_active=t.is_active)

    def create_type(self, name: str) -> InstrumentTypeDTO:
        if not name or not name.strip():
            raise ValidationError("Type name is required.")
        self._check_duplicate_name(InstrumentType, name, "type_id")
        itype = InstrumentType(name=name.strip(), is_active=True)
        self.db.add(itype)
        self.db.flush()
        return self._type_to_dto(itype)

    def update_type(self, type_id: int, name: str) -> InstrumentTypeDTO:
        itype = self.db.query(InstrumentType).filter(InstrumentType.type_id == type_id).first()
        if itype is None:
            raise NotFoundError(f"Instrument type {type_id} not found.")
        if not name or not name.strip():
            raise ValidationError("Type name is required.")
        self._check_duplicate_name(InstrumentType, name, "type_id", exclude_id=type_id)
        itype.name = name.strip()
        self.db.flush()
        return self._type_to_dto(itype)

    def list_types(self, active_only: bool) -> list[InstrumentTypeDTO]:
        query = self.db.query(InstrumentType)
        if active_only:
            query = query.filter(InstrumentType.is_active.is_(True))
        rows = query.order_by(InstrumentType.name.asc()).all()
        return [self._type_to_dto(r) for r in rows]

    def deactivate_type(self, type_id: int) -> int:
        """Soft-delete an instrument type, returning the count of active instruments using it."""
        itype = self.db.query(InstrumentType).filter(InstrumentType.type_id == type_id).first()
        if itype is None:
            raise NotFoundError(f"Instrument type {type_id} not found.")
        usage_count = (
            self.db.query(Instrument)
            .filter(Instrument.type_id == type_id)
            .filter(Instrument.is_active.is_(True))
            .count()
        )
        itype.is_active = False
        self.db.flush()
        return usage_count

    def reactivate_type(self, type_id: int) -> InstrumentTypeDTO:
        itype = self.db.query(InstrumentType).filter(InstrumentType.type_id == type_id).first()
        if itype is None:
            raise NotFoundError(f"Instrument type {type_id} not found.")
        itype.is_active = True
        self.db.flush()
        return self._type_to_dto(itype)

    # ------------------------------------------------------------ ReservationPurpose

    @staticmethod
    def _purpose_to_dto(p: ReservationPurpose) -> ReservationPurposeDTO:
        return ReservationPurposeDTO(
            reservation_purpose_id=p.reservation_purpose_id, name=p.name, is_active=p.is_active
        )

    def create_purpose(self, name: str) -> ReservationPurposeDTO:
        if not name or not name.strip():
            raise ValidationError("Purpose name is required.")
        self._check_duplicate_name(ReservationPurpose, name, "reservation_purpose_id")
        purpose = ReservationPurpose(name=name.strip(), is_active=True)
        self.db.add(purpose)
        self.db.flush()
        return self._purpose_to_dto(purpose)

    def update_purpose(self, purpose_id: int, name: str) -> ReservationPurposeDTO:
        purpose = (
            self.db.query(ReservationPurpose)
            .filter(ReservationPurpose.reservation_purpose_id == purpose_id)
            .first()
        )
        if purpose is None:
            raise NotFoundError(f"Reservation purpose {purpose_id} not found.")
        if not name or not name.strip():
            raise ValidationError("Purpose name is required.")
        self._check_duplicate_name(
            ReservationPurpose, name, "reservation_purpose_id", exclude_id=purpose_id
        )
        purpose.name = name.strip()
        self.db.flush()
        return self._purpose_to_dto(purpose)

    def list_purposes(self, active_only: bool) -> list[ReservationPurposeDTO]:
        query = self.db.query(ReservationPurpose)
        if active_only:
            query = query.filter(ReservationPurpose.is_active.is_(True))
        rows = query.order_by(ReservationPurpose.name.asc()).all()
        return [self._purpose_to_dto(r) for r in rows]

    def deactivate_purpose(self, purpose_id: int) -> int:
        """Soft-delete a reservation purpose, returning the count of active reservations using it."""
        purpose = (
            self.db.query(ReservationPurpose)
            .filter(ReservationPurpose.reservation_purpose_id == purpose_id)
            .first()
        )
        if purpose is None:
            raise NotFoundError(f"Reservation purpose {purpose_id} not found.")
        usage_count = (
            self.db.query(Reservation)
            .filter(Reservation.reservation_purpose_id == purpose_id)
            .filter(Reservation.is_active.is_(True))
            .count()
        )
        purpose.is_active = False
        self.db.flush()
        return usage_count

    def reactivate_purpose(self, purpose_id: int) -> ReservationPurposeDTO:
        purpose = (
            self.db.query(ReservationPurpose)
            .filter(ReservationPurpose.reservation_purpose_id == purpose_id)
            .first()
        )
        if purpose is None:
            raise NotFoundError(f"Reservation purpose {purpose_id} not found.")
        purpose.is_active = True
        self.db.flush()
        return self._purpose_to_dto(purpose)
