"""Business logic for managing instruments.

Encapsulates create/update/soft-delete/toggle-favorite/list operations for
instruments, enforcing required-field validation, decommissioned/maintenance
scheduling exclusion, and audit logging for every mutation.
"""
from __future__ import annotations

from sqlalchemy import asc
from sqlalchemy.orm import Session

from app.contracts import (
    InstrumentCreateDTO,
    InstrumentDTO,
    InstrumentFilterDTO,
    InstrumentUpdateDTO,
    NotFoundError,
)
from app.models import AuditActionType, AuditEntityType, Instrument, InstrumentStatus
from app.services.audit_log import AuditLogService

#: Instrument statuses that make an instrument unavailable for scheduling.
_UNSCHEDULABLE_STATUSES = {
    InstrumentStatus.DECOMMISSIONED,
    InstrumentStatus.UNDER_MAINTENANCE,
}


def _to_dto(instrument: Instrument, location_name: str, vendor_name: str, type_name: str) -> InstrumentDTO:
    status_value = instrument.status.value if hasattr(instrument.status, "value") else instrument.status
    return InstrumentDTO(
        instrument_id=instrument.instrument_id,
        name=instrument.name,
        nickname=instrument.nickname,
        location_id=instrument.location_id,
        location_name=location_name,
        vendor_id=instrument.vendor_id,
        vendor_name=vendor_name,
        type_id=instrument.type_id,
        type_name=type_name,
        asset_id=instrument.asset_id,
        color=instrument.color,
        status=status_value,
        is_favorite=instrument.is_favorite,
        is_active=instrument.is_active,
    )


class InstrumentService:
    """Service layer for instrument CRUD, favoriting, and listing."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._audit = AuditLogService(db)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_or_404(self, instrument_id: int) -> Instrument:
        instrument = (
            self._db.query(Instrument)
            .filter(Instrument.instrument_id == instrument_id)
            .one_or_none()
        )
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found")
        return instrument

    def _lookup_names(self, instrument: Instrument) -> tuple[str, str, str]:
        from app.models import Location, Type, Vendor

        location = (
            self._db.query(Location)
            .filter(Location.location_id == instrument.location_id)
            .one_or_none()
        )
        vendor = (
            self._db.query(Vendor)
            .filter(Vendor.vendor_id == instrument.vendor_id)
            .one_or_none()
        )
        type_ = (
            self._db.query(Type)
            .filter(Type.type_id == instrument.type_id)
            .one_or_none()
        )
        return (
            location.name if location else "",
            vendor.name if vendor else "",
            type_.name if type_ else "",
        )

    def _to_dto(self, instrument: Instrument) -> InstrumentDTO:
        location_name, vendor_name, type_name = self._lookup_names(instrument)
        return _to_dto(instrument, location_name, vendor_name, type_name)

    @staticmethod
    def _normalize_status(status: str) -> InstrumentStatus:
        try:
            return InstrumentStatus(status)
        except ValueError:
            for member in InstrumentStatus:
                if member.value.lower() == str(status).lower() or member.name.lower() == str(status).lower():
                    return member
            raise ValueError(f"Invalid instrument status: {status}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create(self, data: InstrumentCreateDTO) -> InstrumentDTO:
        """Create a new instrument, validating required fields and logging audit."""
        name = (data.name or "").strip()
        nickname = (data.nickname or "").strip()
        if not name:
            raise ValueError("Instrument name is required")
        if not nickname:
            raise ValueError("Instrument nickname is required")
        if not data.location_id:
            raise ValueError("Location is required")
        if not data.vendor_id:
            raise ValueError("Vendor is required")
        if not data.type_id:
            raise ValueError("Type is required")

        status = self._normalize_status(data.status) if data.status else InstrumentStatus.ACTIVE

        instrument = Instrument(
            name=name,
            nickname=nickname,
            location_id=data.location_id,
            vendor_id=data.vendor_id,
            type_id=data.type_id,
            asset_id=data.asset_id,
            color=data.color,
            status=status,
            is_favorite=False,
            is_active=data.is_active if data.is_active is not None else True,
        )
        self._db.add(instrument)
        self._db.flush()

        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.INSTRUMENT,
            entity_id=instrument.instrument_id,
            description=f"Created instrument '{instrument.name}' (nickname: {instrument.nickname})",
        )
        self._db.commit()
        return self._to_dto(instrument)

    def update(self, instrument_id: int, data: InstrumentUpdateDTO) -> InstrumentDTO:
        """Update an existing instrument and log field-level changes."""
        instrument = self._get_or_404(instrument_id)

        changes: list[str] = []

        def _apply(field: str, new_value):
            nonlocal changes
            if new_value is None:
                return
            old_value = getattr(instrument, field)
            old_repr = old_value.value if hasattr(old_value, "value") else old_value
            if old_repr == new_value:
                return
            changes.append(f"{field}: '{old_repr}' -> '{new_value}'")
            setattr(instrument, field, new_value)

        if data.name is not None:
            new_name = data.name.strip()
            if not new_name:
                raise ValueError("Instrument name is required")
            _apply("name", new_name)
        if data.nickname is not None:
            new_nick = data.nickname.strip()
            if not new_nick:
                raise ValueError("Instrument nickname is required")
            _apply("nickname", new_nick)
        if data.location_id is not None:
            _apply("location_id", data.location_id)
        if data.vendor_id is not None:
            _apply("vendor_id", data.vendor_id)
        if data.type_id is not None:
            _apply("type_id", data.type_id)
        if data.asset_id is not None:
            _apply("asset_id", data.asset_id)
        if data.color is not None:
            _apply("color", data.color)
        if data.status is not None:
            new_status = self._normalize_status(data.status)
            _apply("status", new_status)
        if data.is_active is not None:
            _apply("is_active", data.is_active)

        if changes:
            self._db.flush()
            self._audit.log(
                actor="Unknown",
                action_type=AuditActionType.UPDATE,
                entity_type=AuditEntityType.INSTRUMENT,
                entity_id=instrument.instrument_id,
                description="Updated fields: " + "; ".join(changes),
            )
        self._db.commit()
        return self._to_dto(instrument)

    def soft_delete(self, instrument_id: int) -> None:
        """Mark an instrument inactive without removing the row."""
        instrument = self._get_or_404(instrument_id)
        instrument.is_active = False
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.INSTRUMENT,
            entity_id=instrument.instrument_id,
            description=f"Soft-deleted instrument '{instrument.name}'",
        )
        self._db.commit()

    def toggle_favorite(self, instrument_id: int) -> bool:
        """Flip is_favorite and log the change; returns new value."""
        instrument = self._get_or_404(instrument_id)
        old_value = instrument.is_favorite
        instrument.is_favorite = not old_value
        self._db.flush()
        self._audit.log(
            actor="Unknown",
            action_type=AuditActionType.UPDATE,
            entity_type=AuditEntityType.INSTRUMENT,
            entity_id=instrument.instrument_id,
            description=f"is_favorite: '{old_value}' -> '{instrument.is_favorite}'",
        )
        self._db.commit()
        return instrument.is_favorite

    def list_instruments(self, filters: InstrumentFilterDTO) -> list[InstrumentDTO]:
        """List instruments applying optional filters, sorted name then nickname."""
        query = self._db.query(Instrument).filter(Instrument.is_active.is_(True))

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

        query = query.order_by(asc(Instrument.name), asc(Instrument.nickname))
        return [self._to_dto(instrument) for instrument in query.all()]

    def get_instrument(self, instrument_id: int) -> InstrumentDTO:
        """Fetch a single instrument by id."""
        instrument = self._get_or_404(instrument_id)
        return self._to_dto(instrument)

    @staticmethod
    def is_schedulable_status(status: InstrumentStatus) -> bool:
        """True if the given status allows the instrument to be scheduled."""
        return status not in _UNSCHEDULABLE_STATUSES
