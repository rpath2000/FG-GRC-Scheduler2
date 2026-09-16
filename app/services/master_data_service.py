"""MasterDataService: CRUD + soft-delete for Location, Vendor, InstrumentType,
ReservationPurpose, with usage warnings on deactivation."""

from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.contracts import (
    DuplicateError,
    InstrumentTypeDTO,
    LocationDTO,
    NotFoundError,
    ReservationPurposeDTO,
    ValidationError,
    VendorDTO,
)
from app.models import (
    Instrument,
    InstrumentType,
    Location,
    Reservation,
    ReservationPurpose,
    Vendor,
)
from app.services._normalize import normalize_name
from app.services.audit_service import AuditService


class MasterDataService:
    """Business logic for reference/master data entities."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._audit = AuditService(db)

    # -- generic helpers ----------------------------------------------------

    def _check_name_required(self, name: str, entity_label: str) -> str:
        if not name or not name.strip():
            raise ValidationError(f"{entity_label} name is required")
        return name.strip()

    def _check_duplicate(self, model, name: str, exclude_id: int | None, id_field: str, entity_label: str) -> None:
        norm = normalize_name(name)
        stmt = select(model)
        rows = self._db.execute(stmt).scalars().all()
        for row in rows:
            if exclude_id is not None and getattr(row, id_field) == exclude_id:
                continue
            if normalize_name(row.name) == norm:
                raise DuplicateError(f"{entity_label} with name '{name}' already exists")

    # -- Location -------------------------------------------------------------

    def create_location(self, name: str) -> LocationDTO:
        clean = self._check_name_required(name, "Location")
        self._check_duplicate(Location, clean, None, "location_id", "Location")
        loc = Location(name=clean, is_active=True)
        self._db.add(loc)
        self._db.commit()
        self._db.refresh(loc)
        self._audit.log_action("Unknown", "CREATE", "LOCATION", loc.location_id, f"Created location '{clean}'")
        return LocationDTO(location_id=loc.location_id, name=loc.name, is_active=loc.is_active)

    def update_location(self, location_id: int, name: str) -> LocationDTO:
        loc = self._db.get(Location, location_id)
        if loc is None:
            raise NotFoundError(f"Location {location_id} not found")
        clean = self._check_name_required(name, "Location")
        self._check_duplicate(Location, clean, location_id, "location_id", "Location")
        loc.name = clean
        self._db.commit()
        self._db.refresh(loc)
        self._audit.log_action("Unknown", "UPDATE", "LOCATION", loc.location_id, f"Updated location to '{clean}'")
        return LocationDTO(location_id=loc.location_id, name=loc.name, is_active=loc.is_active)

    def list_locations(self, active_only: bool) -> list[LocationDTO]:
        stmt = select(Location)
        if active_only:
            stmt = stmt.where(Location.is_active.is_(True))
        rows = self._db.execute(stmt).scalars().all()
        return [LocationDTO(location_id=r.location_id, name=r.name, is_active=r.is_active) for r in rows]

    def deactivate_location(self, location_id: int) -> int:
        loc = self._db.get(Location, location_id)
        if loc is None:
            raise NotFoundError(f"Location {location_id} not found")
        usage = self._db.execute(
            select(func.count(Instrument.instrument_id)).where(
                Instrument.location_id == location_id, Instrument.is_active.is_(True)
            )
        ).scalar_one()
        loc.is_active = False
        self._db.commit()
        self._audit.log_action(
            "Unknown",
            "DELETE",
            "LOCATION",
            loc.location_id,
            f"Deactivated location '{loc.name}' (in use by {usage} active instrument(s))",
        )
        return int(usage)

    def reactivate_location(self, location_id: int) -> LocationDTO:
        loc = self._db.get(Location, location_id)
        if loc is None:
            raise NotFoundError(f"Location {location_id} not found")
        loc.is_active = True
        self._db.commit()
        self._db.refresh(loc)
        self._audit.log_action("Unknown", "UPDATE", "LOCATION", loc.location_id, f"Reactivated location '{loc.name}'")
        return LocationDTO(location_id=loc.location_id, name=loc.name, is_active=loc.is_active)

    # -- Vendor -----------------------------------------------------------

    def create_vendor(self, name: str) -> VendorDTO:
        clean = self._check_name_required(name, "Vendor")
        self._check_duplicate(Vendor, clean, None, "vendor_id", "Vendor")
        vendor = Vendor(name=clean, is_active=True)
        self._db.add(vendor)
        self._db.commit()
        self._db.refresh(vendor)
        self._audit.log_action("Unknown", "CREATE", "VENDOR", vendor.vendor_id, f"Created vendor '{clean}'")
        return VendorDTO(vendor_id=vendor.vendor_id, name=vendor.name, is_active=vendor.is_active)

    def update_vendor(self, vendor_id: int, name: str) -> VendorDTO:
        vendor = self._db.get(Vendor, vendor_id)
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found")
        clean = self._check_name_required(name, "Vendor")
        self._check_duplicate(Vendor, clean, vendor_id, "vendor_id", "Vendor")
        vendor.name = clean
        self._db.commit()
        self._db.refresh(vendor)
        self._audit.log_action("Unknown", "UPDATE", "VENDOR", vendor.vendor_id, f"Updated vendor to '{clean}'")
        return VendorDTO(vendor_id=vendor.vendor_id, name=vendor.name, is_active=vendor.is_active)

    def list_vendors(self, active_only: bool) -> list[VendorDTO]:
        stmt = select(Vendor)
        if active_only:
            stmt = stmt.where(Vendor.is_active.is_(True))
        rows = self._db.execute(stmt).scalars().all()
        return [VendorDTO(vendor_id=r.vendor_id, name=r.name, is_active=r.is_active) for r in rows]

    def deactivate_vendor(self, vendor_id: int) -> int:
        vendor = self._db.get(Vendor, vendor_id)
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found")
        usage = self._db.execute(
            select(func.count(Instrument.instrument_id)).where(
                Instrument.vendor_id == vendor_id, Instrument.is_active.is_(True)
            )
        ).scalar_one()
        vendor.is_active = False
        self._db.commit()
        self._audit.log_action(
            "Unknown",
            "DELETE",
            "VENDOR",
            vendor.vendor_id,
            f"Deactivated vendor '{vendor.name}' (in use by {usage} active instrument(s))",
        )
        return int(usage)

    def reactivate_vendor(self, vendor_id: int) -> VendorDTO:
        vendor = self._db.get(Vendor, vendor_id)
        if vendor is None:
            raise NotFoundError(f"Vendor {vendor_id} not found")
        vendor.is_active = True
        self._db.commit()
        self._db.refresh(vendor)
        self._audit.log_action("Unknown", "UPDATE", "VENDOR", vendor.vendor_id, f"Reactivated vendor '{vendor.name}'")
        return VendorDTO(vendor_id=vendor.vendor_id, name=vendor.name, is_active=vendor.is_active)

    # -- InstrumentType -----------------------------------------------------

    def create_type(self, name: str) -> InstrumentTypeDTO:
        clean = self._check_name_required(name, "Instrument type")
        self._check_duplicate(InstrumentType, clean, None, "type_id", "Instrument type")
        itype = InstrumentType(name=clean, is_active=True)
        self._db.add(itype)
        self._db.commit()
        self._db.refresh(itype)
        self._audit.log_action("Unknown", "CREATE", "INSTRUMENT_TYPE", itype.type_id, f"Created type '{clean}'")
        return InstrumentTypeDTO(type_id=itype.type_id, name=itype.name, is_active=itype.is_active)

    def update_type(self, type_id: int, name: str) -> InstrumentTypeDTO:
        itype = self._db.get(InstrumentType, type_id)
        if itype is None:
            raise NotFoundError(f"Instrument type {type_id} not found")
        clean = self._check_name_required(name, "Instrument type")
        self._check_duplicate(InstrumentType, clean, type_id, "type_id", "Instrument type")
        itype.name = clean
        self._db.commit()
        self._db.refresh(itype)
        self._audit.log_action("Unknown", "UPDATE", "INSTRUMENT_TYPE", itype.type_id, f"Updated type to '{clean}'")
        return InstrumentTypeDTO(type_id=itype.type_id, name=itype.name, is_active=itype.is_active)

    def list_types(self, active_only: bool) -> list[InstrumentTypeDTO]:
        stmt = select(InstrumentType)
        if active_only:
            stmt = stmt.where(InstrumentType.is_active.is_(True))
        rows = self._db.execute(stmt).scalars().all()
        return [InstrumentTypeDTO(type_id=r.type_id, name=r.name, is_active=r.is_active) for r in rows]

    def deactivate_type(self, type_id: int) -> int:
        itype = self._db.get(InstrumentType, type_id)
        if itype is None:
            raise NotFoundError(f"Instrument type {type_id} not found")
        usage = self._db.execute(
            select(func.count(Instrument.instrument_id)).where(
                Instrument.type_id == type_id, Instrument.is_active.is_(True)
            )
        ).scalar_one()
        itype.is_active = False
        self._db.commit()
        self._audit.log_action(
            "Unknown",
            "DELETE",
            "INSTRUMENT_TYPE",
            itype.type_id,
            f"Deactivated type '{itype.name}' (in use by {usage} active instrument(s))",
        )
        return int(usage)

    def reactivate_type(self, type_id: int) -> InstrumentTypeDTO:
        itype = self._db.get(InstrumentType, type_id)
        if itype is None:
            raise NotFoundError(f"Instrument type {type_id} not found")
        itype.is_active = True
        self._db.commit()
        self._db.refresh(itype)
        self._audit.log_action("Unknown", "UPDATE", "INSTRUMENT_TYPE", itype.type_id, f"Reactivated type '{itype.name}'")
        return InstrumentTypeDTO(type_id=itype.type_id, name=itype.name, is_active=itype.is_active)

    # -- ReservationPurpose --------------------------------------------------

    def create_purpose(self, name: str) -> ReservationPurposeDTO:
        clean = self._check_name_required(name, "Reservation purpose")
        self._check_duplicate(ReservationPurpose, clean, None, "reservation_purpose_id", "Reservation purpose")
        purpose = ReservationPurpose(name=clean, is_active=True)
        self._db.add(purpose)
        self._db.commit()
        self._db.refresh(purpose)
        self._audit.log_action(
            "Unknown", "CREATE", "RESERVATION_PURPOSE", purpose.reservation_purpose_id, f"Created purpose '{clean}'"
        )
        return ReservationPurposeDTO(
            reservation_purpose_id=purpose.reservation_purpose_id, name=purpose.name, is_active=purpose.is_active
        )

    def update_purpose(self, purpose_id: int, name: str) -> ReservationPurposeDTO:
        purpose = self._db.get(ReservationPurpose, purpose_id)
        if purpose is None:
            raise NotFoundError(f"Reservation purpose {purpose_id} not found")
        clean = self._check_name_required(name, "Reservation purpose")
        self._check_duplicate(ReservationPurpose, clean, purpose_id, "reservation_purpose_id", "Reservation purpose")
        purpose.name = clean
        self._db.commit()
        self._db.refresh(purpose)
        self._audit.log_action(
            "Unknown", "UPDATE", "RESERVATION_PURPOSE", purpose.reservation_purpose_id, f"Updated purpose to '{clean}'"
        )
        return ReservationPurposeDTO(
            reservation_purpose_id=purpose.reservation_purpose_id, name=purpose.name, is_active=purpose.is_active
        )

    def list_purposes(self, active_only: bool) -> list[ReservationPurposeDTO]:
        stmt = select(ReservationPurpose)
        if active_only:
            stmt = stmt.where(ReservationPurpose.is_active.is_(True))
        rows = self._db.execute(stmt).scalars().all()
        return [
            ReservationPurposeDTO(reservation_purpose_id=r.reservation_purpose_id, name=r.name, is_active=r.is_active)
            for r in rows
        ]

    def deactivate_purpose(self, purpose_id: int) -> int:
        purpose = self._db.get(ReservationPurpose, purpose_id)
        if purpose is None:
            raise NotFoundError(f"Reservation purpose {purpose_id} not found")
        usage = self._db.execute(
            select(func.count(Reservation.reservation_id)).where(
                Reservation.reservation_purpose_id == purpose_id, Reservation.is_active.is_(True)
            )
        ).scalar_one()
        purpose.is_active = False
        self._db.commit()
        self._audit.log_action(
            "Unknown",
            "DELETE",
            "RESERVATION_PURPOSE",
            purpose.reservation_purpose_id,
            f"Deactivated purpose '{purpose.name}' (in use by {usage} active reservation(s))",
        )
        return int(usage)

    def reactivate_purpose(self, purpose_id: int) -> ReservationPurposeDTO:
        purpose = self._db.get(ReservationPurpose, purpose_id)
        if purpose is None:
            raise NotFoundError(f"Reservation purpose {purpose_id} not found")
        purpose.is_active = True
        self._db.commit()
        self._db.refresh(purpose)
        self._audit.log_action(
            "Unknown", "UPDATE", "RESERVATION_PURPOSE", purpose.reservation_purpose_id, f"Reactivated purpose '{purpose.name}'"
        )
        return ReservationPurposeDTO(
            reservation_purpose_id=purpose.reservation_purpose_id, name=purpose.name, is_active=purpose.is_active
        )
