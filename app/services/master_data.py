"""Business logic for master data CRUD with duplicate detection."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.contracts import (
    AuditActionType,
    AuditEntityType,
    DuplicateError,
    LocationData,
    NotFoundError,
    PurposeData,
    TypeData,
    UsageWarning,
    VendorData,
)
from app.models import (
    Instrument,
    Location,
    Reservation,
    ReservationPurpose,
    Type,
    Vendor,
)

from app.services.audit import AuditService


def _normalize(name: str) -> str:
    return " ".join(name.strip().split()).lower()


class MasterDataService:
    """CRUD for Location, Vendor, Type, ReservationPurpose master data."""

    def __init__(self, db: Session):
        self.db = db

    # ---------------------------------------------------------------- Location

    def create_location(self, name: str, actor: str) -> LocationData:
        self._check_duplicate(Location, "location_id", name)
        location = Location(name=name.strip(), is_active=True)
        self.db.add(location)
        self.db.flush()
        self.db.refresh(location)
        AuditService(self.db).record_action(
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.LOCATION,
            entity_id=location.location_id,
            actor=actor or "Unknown",
            description=f"Created location: Name={location.name}",
        )
        self.db.commit()
        return LocationData(
            location_id=location.location_id,
            name=location.name,
            is_active=location.is_active,
        )

    def update_location(self, location_id: int, name: str, actor: str) -> LocationData:
        location = self.db.get(Location, location_id)
        if location is None:
            raise NotFoundError(f"Location {location_id} not found.")
        self._check_duplicate(Location, "location_id", name, exclude_id=location_id)
        location.name = name.strip()
        self.db.flush()
        AuditService(self.db).record_action(
            action_type=AuditActionType.UPDATE,
            entity_type=AuditEntityType.LOCATION,
            entity_id=location.location_id,
            actor=actor or "Unknown",
            description=f"Updated location: Name={location.name}",
        )
        self.db.commit()
        return LocationData(
            location_id=location.location_id,
            name=location.name,
            is_active=location.is_active,
        )

    def soft_delete_location(self, location_id: int, actor: str) -> UsageWarning:
        location = self.db.get(Location, location_id)
        if location is None:
            raise NotFoundError(f"Location {location_id} not found.")
        location.is_active = False
        self.db.flush()

        active_instruments = self.db.execute(
            select(func.count()).select_from(Instrument).where(
                Instrument.location_id == location_id, Instrument.is_active.is_(True)
            )
        ).scalar_one()
        active_reservations = self.db.execute(
            select(func.count())
            .select_from(Reservation)
            .join(Instrument, Instrument.instrument_id == Reservation.instrument_id)
            .where(Instrument.location_id == location_id, Reservation.is_active.is_(True))
        ).scalar_one()

        AuditService(self.db).record_action(
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.LOCATION,
            entity_id=location.location_id,
            actor=actor or "Unknown",
            description=f"Soft-deleted location: Name={location.name}",
        )
        self.db.commit()
        return UsageWarning(
            active_instrument_count=active_instruments,
            active_reservation_count=active_reservations,
        )

    def reactivate_location(self, location_id: int, actor: str) -> LocationData:
        location = self.db.get(Location, location_id)
        if location is None:
            raise NotFoundError(f"Location {location_id} not found.")
        location.is_active = True
        self.db.flush()
        AuditService(self.db).record_action(
            action_type=AuditActionType.STATUS_CHANGE,
            entity_type=AuditEntityType.LOCATION,
            entity_id=location.location_id,
            actor=actor or "Unknown",
            description=f"Reactivated location: Name={location.name}",
        )
        self.db.commit()
        return LocationData(
            location_id=location.location_id,
            name=location.name,
            is_active=location.is_active,
        )

    def list_locations(self, include_inactive: bool) -> list[LocationData]:
        stmt = select(Location)
        if not include_inactive:
            stmt = stmt.where(Location.is_active.is_(True))
        stmt = stmt.order_by(Location.name)
        rows = self.db.execute(stmt).scalars().all()
        return [
            LocationData(location_id=r.location_id, name=r.name, is_active=r.is_active)
            for r in rows
        ]

    # ------------------------------------------------------------------ Vendor

    def create_vendor(self, name: str, actor: str) -> VendorData:
        self._check_duplicate(Vendor, "vendor_id", name)
        vendor = Vendor(name=name.strip(), is_active=True)
        self.db.add(vendor)
        self.db.flush()
        self.db.refresh(vendor)
        AuditService(self.db).record_action(
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.VENDOR,
            entity_id=vendor.vendor_id,
            actor=actor or "Unknown",
            description=f"Created vendor: Name={vendor.name}",
        )
        self.db.commit()
        return VendorData(vendor_id=vendor.vendor_id, name=vendor.name, is_active=vendor.is_active)

    def update_vendor(self, vendor_id: int, name: str, actor: str) -> VendorData:
        vendor = self.db.get(Vendor, vendor_id)
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found.")
        self._check_duplicate(Vendor, "vendor_id", name, exclude_id=vendor_id)
        vendor.name = name.strip()
        self.db.flush()
        AuditService(self.db).record_action(
            action_type=AuditActionType.UPDATE,
            entity_type=AuditEntityType.VENDOR,
            entity_id=vendor.vendor_id,
            actor=actor or "Unknown",
            description=f"Updated vendor: Name={vendor.name}",
        )
        self.db.commit()
        return VendorData(vendor_id=vendor.vendor_id, name=vendor.name, is_active=vendor.is_active)

    def soft_delete_vendor(self, vendor_id: int, actor: str) -> UsageWarning:
        vendor = self.db.get(Vendor, vendor_id)
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found.")
        vendor.is_active = False
        self.db.flush()

        active_instruments = self.db.execute(
            select(func.count()).select_from(Instrument).where(
                Instrument.vendor_id == vendor_id, Instrument.is_active.is_(True)
            )
        ).scalar_one()
        active_reservations = self.db.execute(
            select(func.count())
            .select_from(Reservation)
            .join(Instrument, Instrument.instrument_id == Reservation.instrument_id)
            .where(Instrument.vendor_id == vendor_id, Reservation.is_active.is_(True))
        ).scalar_one()

        AuditService(self.db).record_action(
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.VENDOR,
            entity_id=vendor.vendor_id,
            actor=actor or "Unknown",
            description=f"Soft-deleted vendor: Name={vendor.name}",
        )
        self.db.commit()
        return UsageWarning(
            active_instrument_count=active_instruments,
            active_reservation_count=active_reservations,
        )

    def list_vendors(self, include_inactive: bool) -> list[VendorData]:
        stmt = select(Vendor)
        if not include_inactive:
            stmt = stmt.where(Vendor.is_active.is_(True))
        stmt = stmt.order_by(Vendor.name)
        rows = self.db.execute(stmt).scalars().all()
        return [VendorData(vendor_id=r.vendor_id, name=r.name, is_active=r.is_active) for r in rows]

    # -------------------------------------------------------------------- Type

    def create_type(self, name: str, actor: str) -> TypeData:
        self._check_duplicate(Type, "type_id", name)
        type_ = Type(name=name.strip(), is_active=True)
        self.db.add(type_)
        self.db.flush()
        self.db.refresh(type_)
        AuditService(self.db).record_action(
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.TYPE,
            entity_id=type_.type_id,
            actor=actor or "Unknown",
            description=f"Created type: Name={type_.name}",
        )
        self.db.commit()
        return TypeData(type_id=type_.type_id, name=type_.name, is_active=type_.is_active)

    def update_type(self, type_id: int, name: str, actor: str) -> TypeData:
        type_ = self.db.get(Type, type_id)
        if type_ is None:
            raise NotFoundError(f"Type {type_id} not found.")
        self._check_duplicate(Type, "type_id", name, exclude_id=type_id)
        type_.name = name.strip()
        self.db.flush()
        AuditService(self.db).record_action(
            action_type=AuditActionType.UPDATE,
            entity_type=AuditEntityType.TYPE,
            entity_id=type_.type_id,
            actor=actor or "Unknown",
            description=f"Updated type: Name={type_.name}",
        )
        self.db.commit()
        return TypeData(type_id=type_.type_id, name=type_.name, is_active=type_.is_active)

    def soft_delete_type(self, type_id: int, actor: str) -> UsageWarning:
        type_ = self.db.get(Type, type_id)
        if type_ is None:
            raise NotFoundError(f"Type {type_id} not found.")
        type_.is_active = False
        self.db.flush()

        active_instruments = self.db.execute(
            select(func.count()).select_from(Instrument).where(
                Instrument.type_id == type_id, Instrument.is_active.is_(True)
            )
        ).scalar_one()
        active_reservations = self.db.execute(
            select(func.count())
            .select_from(Reservation)
            .join(Instrument, Instrument.instrument_id == Reservation.instrument_id)
            .where(Instrument.type_id == type_id, Reservation.is_active.is_(True))
        ).scalar_one()

        AuditService(self.db).record_action(
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.TYPE,
            entity_id=type_.type_id,
            actor=actor or "Unknown",
            description=f"Soft-deleted type: Name={type_.name}",
        )
        self.db.commit()
        return UsageWarning(
            active_instrument_count=active_instruments,
            active_reservation_count=active_reservations,
        )

    def list_types(self, include_inactive: bool) -> list[TypeData]:
        stmt = select(Type)
        if not include_inactive:
            stmt = stmt.where(Type.is_active.is_(True))
        stmt = stmt.order_by(Type.name)
        rows = self.db.execute(stmt).scalars().all()
        return [TypeData(type_id=r.type_id, name=r.name, is_active=r.is_active) for r in rows]

    # --------------------------------------------------------------- Purpose

    def create_purpose(self, name: str, actor: str) -> PurposeData:
        self._check_duplicate(ReservationPurpose, "reservation_purpose_id", name)
        purpose = ReservationPurpose(name=name.strip(), is_active=True)
        self.db.add(purpose)
        self.db.flush()
        self.db.refresh(purpose)
        AuditService(self.db).record_action(
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.PURPOSE,
            entity_id=purpose.reservation_purpose_id,
            actor=actor or "Unknown",
            description=f"Created purpose: Name={purpose.name}",
        )
        self.db.commit()
        return PurposeData(
            reservation_purpose_id=purpose.reservation_purpose_id,
            name=purpose.name,
            is_active=purpose.is_active,
        )

    def update_purpose(self, purpose_id: int, name: str, actor: str) -> PurposeData:
        purpose = self.db.get(ReservationPurpose, purpose_id)
        if purpose is None:
            raise NotFoundError(f"Purpose {purpose_id} not found.")
        self._check_duplicate(
            ReservationPurpose, "reservation_purpose_id", name, exclude_id=purpose_id
        )
        purpose.name = name.strip()
        self.db.flush()
        AuditService(self.db).record_action(
            action_type=AuditActionType.UPDATE,
            entity_type=AuditEntityType.PURPOSE,
            entity_id=purpose.reservation_purpose_id,
            actor=actor or "Unknown",
            description=f"Updated purpose: Name={purpose.name}",
        )
        self.db.commit()
        return PurposeData(
            reservation_purpose_id=purpose.reservation_purpose_id,
            name=purpose.name,
            is_active=purpose.is_active,
        )

    def soft_delete_purpose(self, purpose_id: int, actor: str) -> UsageWarning:
        purpose = self.db.get(ReservationPurpose, purpose_id)
        if purpose is None:
            raise NotFoundError(f"Purpose {purpose_id} not found.")
        purpose.is_active = False
        self.db.flush()

        active_reservations = self.db.execute(
            select(func.count())
            .select_from(Reservation)
            .where(
                Reservation.reservation_purpose_id == purpose_id,
                Reservation.is_active.is_(True),
            )
        ).scalar_one()

        AuditService(self.db).record_action(
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.PURPOSE,
            entity_id=purpose.reservation_purpose_id,
            actor=actor or "Unknown",
            description=f"Soft-deleted purpose: Name={purpose.name}",
        )
        self.db.commit()
        return UsageWarning(active_instrument_count=0, active_reservation_count=active_reservations)

    def reactivate_purpose(self, purpose_id: int, actor: str) -> PurposeData:
        purpose = self.db.get(ReservationPurpose, purpose_id)
        if purpose is None:
            raise NotFoundError(f"Purpose {purpose_id} not found.")
        purpose.is_active = True
        self.db.flush()
        AuditService(self.db).record_action(
            action_type=AuditActionType.STATUS_CHANGE,
            entity_type=AuditEntityType.PURPOSE,
            entity_id=purpose.reservation_purpose_id,
            actor=actor or "Unknown",
            description=f"Reactivated purpose: Name={purpose.name}",
        )
        self.db.commit()
        return PurposeData(
            reservation_purpose_id=purpose.reservation_purpose_id,
            name=purpose.name,
            is_active=purpose.is_active,
        )

    def list_purposes(self, include_inactive: bool) -> list[PurposeData]:
        stmt = select(ReservationPurpose)
        if not include_inactive:
            stmt = stmt.where(ReservationPurpose.is_active.is_(True))
        stmt = stmt.order_by(ReservationPurpose.name)
        rows = self.db.execute(stmt).scalars().all()
        return [
            PurposeData(
                reservation_purpose_id=r.reservation_purpose_id,
                name=r.name,
                is_active=r.is_active,
            )
            for r in rows
        ]

    # ---------------------------------------------------------------- Helpers

    def _check_duplicate(
        self, model, pk_attr: str, name: str, exclude_id: int | None = None
    ) -> None:
        """Raise DuplicateError if a case/whitespace-insensitive match exists."""
        normalized = _normalize(name)
        rows = self.db.execute(select(model)).scalars().all()
        for row in rows:
            if exclude_id is not None and getattr(row, pk_attr) == exclude_id:
                continue
            if _normalize(row.name) == normalized:
                raise DuplicateError(
                    f"'{name.strip()}' already exists as '{row.name}'."
                )
