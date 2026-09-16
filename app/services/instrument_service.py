"""InstrumentService: CRUD, status change, soft-delete, favorite toggle, duplicate detection."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    DuplicateError,
    InstrumentCreateDTO,
    InstrumentDTO,
    InstrumentFilterDTO,
    InstrumentUpdateDTO,
    InvalidStatusError,
    NotFoundError,
    ValidationError,
)
from app.models import Instrument, InstrumentStatus, Location, Vendor, InstrumentType
from app.services._normalize import normalize_name
from app.services.audit_service import AuditService

_VALID_STATUSES = {status.value for status in InstrumentStatus}


class InstrumentService:
    """Business logic for instrument records."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._audit = AuditService(db)

    # -- helpers ---------------------------------------------------------

    def _get_or_404(self, instrument_id: int) -> Instrument:
        instrument = self._db.get(Instrument, instrument_id)
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found")
        return instrument

    def _check_duplicate(
        self, name: str, nickname: str, exclude_id: int | None = None
    ) -> None:
        """Raise DuplicateError if normalized name+nickname pair exists (active or inactive)."""
        norm_name = normalize_name(name)
        norm_nickname = normalize_name(nickname)
        stmt = select(Instrument)
        rows = self._db.execute(stmt).scalars().all()
        for row in rows:
            if exclude_id is not None and row.instrument_id == exclude_id:
                continue
            if normalize_name(row.name) == norm_name and normalize_name(row.nickname) == norm_nickname:
                raise DuplicateError(
                    f"Instrument with name '{name}' and nickname '{nickname}' already exists"
                )

    def _to_dto(self, instrument: Instrument) -> InstrumentDTO:
        location = self._db.get(Location, instrument.location_id)
        vendor = self._db.get(Vendor, instrument.vendor_id)
        itype = self._db.get(InstrumentType, instrument.type_id)
        status_value = (
            instrument.status.value if hasattr(instrument.status, "value") else str(instrument.status)
        )
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
            status=status_value,
            is_active=instrument.is_active,
            is_favorite=instrument.is_favorite,
        )

    # -- public API --------------------------------------------------------

    def create(self, data: InstrumentCreateDTO) -> InstrumentDTO:
        if not data.name or not data.name.strip():
            raise ValidationError("Instrument name is required")
        if not data.nickname or not data.nickname.strip():
            raise ValidationError("Instrument nickname is required")

        self._check_duplicate(data.name, data.nickname)

        instrument = Instrument(
            name=data.name.strip(),
            nickname=data.nickname.strip(),
            location_id=data.location_id,
            vendor_id=data.vendor_id,
            type_id=data.type_id,
            asset_id=data.asset_id,
            color=data.color,
            status=InstrumentStatus.ACTIVE if hasattr(InstrumentStatus, "ACTIVE") else list(InstrumentStatus)[0],
            is_active=True,
            is_favorite=False,
        )
        self._db.add(instrument)
        self._db.commit()
        self._db.refresh(instrument)

        self._audit.log_action(
            actor="Unknown",
            action_type="CREATE",
            entity_type="INSTRUMENT",
            entity_id=instrument.instrument_id,
            description=f"Created instrument '{instrument.name}' ({instrument.nickname})",
        )
        return self._to_dto(instrument)

    def update(self, instrument_id: int, data: InstrumentUpdateDTO) -> InstrumentDTO:
        instrument = self._get_or_404(instrument_id)

        if not data.name or not data.name.strip():
            raise ValidationError("Instrument name is required")
        if not data.nickname or not data.nickname.strip():
            raise ValidationError("Instrument nickname is required")

        self._check_duplicate(data.name, data.nickname, exclude_id=instrument_id)

        instrument.name = data.name.strip()
        instrument.nickname = data.nickname.strip()
        instrument.location_id = data.location_id
        instrument.vendor_id = data.vendor_id
        instrument.type_id = data.type_id
        instrument.asset_id = data.asset_id
        instrument.color = data.color
        instrument.is_active = data.is_active

        self._db.commit()
        self._db.refresh(instrument)

        self._audit.log_action(
            actor="Unknown",
            action_type="UPDATE",
            entity_type="INSTRUMENT",
            entity_id=instrument.instrument_id,
            description=f"Updated instrument '{instrument.name}' ({instrument.nickname})",
        )
        return self._to_dto(instrument)

    def get_by_id(self, instrument_id: int) -> InstrumentDTO:
        instrument = self._get_or_404(instrument_id)
        return self._to_dto(instrument)

    def list_active(self, filters: InstrumentFilterDTO) -> list[InstrumentDTO]:
        stmt = select(Instrument).where(Instrument.is_active.is_(True))
        rows = self._db.execute(stmt).scalars().all()

        result = []
        for row in rows:
            if filters.nickname and filters.nickname.strip():
                if normalize_name(filters.nickname) not in normalize_name(row.nickname):
                    continue
            if filters.location_id is not None and row.location_id != filters.location_id:
                continue
            if filters.vendor_id is not None and row.vendor_id != filters.vendor_id:
                continue
            if filters.type_id is not None and row.type_id != filters.type_id:
                continue
            if filters.favorites_only and not row.is_favorite:
                continue
            result.append(self._to_dto(row))
        return result

    def list_schedulable(self) -> list[InstrumentDTO]:
        """List active instruments whose status permits scheduling."""
        stmt = select(Instrument).where(Instrument.is_active.is_(True))
        rows = self._db.execute(stmt).scalars().all()
        schedulable = []
        for row in rows:
            status_value = row.status.value if hasattr(row.status, "value") else str(row.status)
            if status_value.upper() in ("DECOMMISSIONED", "MAINTENANCE"):
                continue
            schedulable.append(self._to_dto(row))
        return schedulable

    def change_status(self, instrument_id: int, status: str) -> InstrumentDTO:
        instrument = self._get_or_404(instrument_id)

        normalized_status = status.strip().upper() if status else ""
        matched = None
        for member in InstrumentStatus:
            if member.value.upper() == normalized_status or member.name.upper() == normalized_status:
                matched = member
                break
        if matched is None:
            raise ValidationError(f"Invalid instrument status: {status!r}")

        instrument.status = matched
        self._db.commit()
        self._db.refresh(instrument)

        self._audit.log_action(
            actor="Unknown",
            action_type="STATUS_CHANGE",
            entity_type="INSTRUMENT",
            entity_id=instrument.instrument_id,
            description=f"Changed status of instrument '{instrument.name}' to {matched.value}",
        )
        return self._to_dto(instrument)

    def soft_delete(self, instrument_id: int) -> None:
        instrument = self._get_or_404(instrument_id)
        instrument.is_active = False
        self._db.commit()

        self._audit.log_action(
            actor="Unknown",
            action_type="DELETE",
            entity_type="INSTRUMENT",
            entity_id=instrument.instrument_id,
            description=f"Soft-deleted instrument '{instrument.name}'",
        )

    def toggle_favorite(self, instrument_id: int) -> InstrumentDTO:
        instrument = self._get_or_404(instrument_id)
        instrument.is_favorite = not instrument.is_favorite
        self._db.commit()
        self._db.refresh(instrument)

        self._audit.log_action(
            actor="Unknown",
            action_type="UPDATE",
            entity_type="INSTRUMENT",
            entity_id=instrument.instrument_id,
            description=(
                f"Marked instrument '{instrument.name}' as "
                f"{'favorite' if instrument.is_favorite else 'not favorite'}"
            ),
        )
        return self._to_dto(instrument)
