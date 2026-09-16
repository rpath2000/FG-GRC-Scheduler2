"""Business logic for Instrument CRUD and dropdown filtering."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    InstrumentCreateData,
    InstrumentData,
    InstrumentFilterData,
    InstrumentUpdateData,
    NotFoundError,
)
from app.models import Instrument, InstrumentStatus, Location, Type, Vendor

from app.services.audit import AuditService
from app.contracts import AuditActionType, AuditEntityType

_EXCLUDED_STATUSES = (InstrumentStatus.DECOMMISSIONED, InstrumentStatus.MAINTENANCE)


def _to_data(instrument: Instrument) -> InstrumentData:
    """Map an ORM Instrument (with loaded relationships) to InstrumentData."""
    location_name = instrument.location.name if instrument.location else ""
    vendor_name = instrument.vendor.name if instrument.vendor else ""
    type_name = instrument.type.name if instrument.type else ""
    status_value = (
        instrument.status.value
        if isinstance(instrument.status, InstrumentStatus)
        else instrument.status
    )
    return InstrumentData(
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
        is_active=instrument.is_active,
        is_favorite=instrument.is_favorite,
    )


def _describe(instrument: Instrument) -> str:
    status_value = (
        instrument.status.value
        if isinstance(instrument.status, InstrumentStatus)
        else instrument.status
    )
    return (
        f"Name={instrument.name}, Nickname={instrument.nickname}, "
        f"LocationId={instrument.location_id}, VendorId={instrument.vendor_id}, "
        f"TypeId={instrument.type_id}, AssetId={instrument.asset_id}, "
        f"Color={instrument.color}, Status={status_value}, "
        f"IsActive={instrument.is_active}"
    )


class InstrumentService:
    """Handles instrument CRUD, soft-delete, favorites, and listing."""

    def __init__(self, db: Session):
        self.db = db

    def create_instrument(self, data: InstrumentCreateData) -> InstrumentData:
        status_value = (
            data.status
            if isinstance(data.status, InstrumentStatus)
            else InstrumentStatus(data.status)
        )
        instrument = Instrument(
            name=data.name,
            nickname=data.nickname,
            location_id=data.location_id,
            vendor_id=data.vendor_id,
            type_id=data.type_id,
            asset_id=data.asset_id,
            color=data.color,
            status=status_value,
            is_active=data.is_active,
            is_favorite=False,
        )
        self.db.add(instrument)
        self.db.flush()
        self.db.refresh(instrument)

        actor = data.actor or "Unknown"
        AuditService(self.db).record_action(
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.INSTRUMENT,
            entity_id=instrument.instrument_id,
            actor=actor,
            description=f"Created instrument: {_describe(instrument)}",
        )
        self.db.commit()
        return self._get_with_relations(instrument.instrument_id)

    def update_instrument(
        self, instrument_id: int, data: InstrumentUpdateData
    ) -> InstrumentData:
        instrument = self.db.get(Instrument, instrument_id)
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found.")

        if data.name is not None:
            instrument.name = data.name
        if data.nickname is not None:
            instrument.nickname = data.nickname
        if data.location_id is not None:
            instrument.location_id = data.location_id
        if data.vendor_id is not None:
            instrument.vendor_id = data.vendor_id
        if data.type_id is not None:
            instrument.type_id = data.type_id
        if data.asset_id is not None:
            instrument.asset_id = data.asset_id
        if data.color is not None:
            instrument.color = data.color
        if data.status is not None:
            instrument.status = (
                data.status
                if isinstance(data.status, InstrumentStatus)
                else InstrumentStatus(data.status)
            )
        if data.is_active is not None:
            instrument.is_active = data.is_active

        self.db.flush()
        self.db.refresh(instrument)

        actor = data.actor or "Unknown"
        AuditService(self.db).record_action(
            action_type=AuditActionType.UPDATE,
            entity_type=AuditEntityType.INSTRUMENT,
            entity_id=instrument.instrument_id,
            actor=actor,
            description=f"Updated instrument: {_describe(instrument)}",
        )
        self.db.commit()
        return self._get_with_relations(instrument.instrument_id)

    def soft_delete_instrument(self, instrument_id: int, actor: str) -> None:
        instrument = self.db.get(Instrument, instrument_id)
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found.")

        instrument.is_active = False
        self.db.flush()

        AuditService(self.db).record_action(
            action_type=AuditActionType.SOFT_DELETE,
            entity_type=AuditEntityType.INSTRUMENT,
            entity_id=instrument.instrument_id,
            actor=actor or "Unknown",
            description=f"Soft-deleted instrument: {_describe(instrument)}",
        )
        self.db.commit()

    def toggle_favorite(self, instrument_id: int) -> bool:
        instrument = self.db.get(Instrument, instrument_id)
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found.")

        instrument.is_favorite = not instrument.is_favorite
        self.db.flush()
        self.db.commit()
        return instrument.is_favorite

    def get_instrument(self, instrument_id: int) -> InstrumentData:
        return self._get_with_relations(instrument_id)

    def list_instruments(
        self, filters: InstrumentFilterData
    ) -> list[InstrumentData]:
        stmt = select(Instrument).where(Instrument.is_active.is_(True))

        if filters.favorites:
            stmt = stmt.where(Instrument.is_favorite.is_(True))
        if filters.nickname:
            stmt = stmt.where(Instrument.nickname.ilike(f"%{filters.nickname}%"))
        if filters.location_id is not None:
            stmt = stmt.where(Instrument.location_id == filters.location_id)
        if filters.vendor_id is not None:
            stmt = stmt.where(Instrument.vendor_id == filters.vendor_id)
        if filters.type_id is not None:
            stmt = stmt.where(Instrument.type_id == filters.type_id)

        sort_by = (filters.sort_by or "name").lower()
        sort_map = {
            "name": Instrument.name,
            "nickname": Instrument.nickname,
            "asset_id": Instrument.asset_id,
            "location": Instrument.location_id,
            "vendor": Instrument.vendor_id,
            "type": Instrument.type_id,
        }
        sort_column = sort_map.get(sort_by, Instrument.name)
        stmt = stmt.order_by(sort_column)

        instruments = self.db.execute(stmt).scalars().all()
        return [self._get_with_relations(i.instrument_id) for i in instruments]

    def list_schedulable_instruments(self) -> list[InstrumentData]:
        stmt = (
            select(Instrument)
            .where(Instrument.is_active.is_(True))
            .where(~Instrument.status.in_(_EXCLUDED_STATUSES))
            .order_by(Instrument.name)
        )
        instruments = self.db.execute(stmt).scalars().all()
        return [self._get_with_relations(i.instrument_id) for i in instruments]

    def _get_with_relations(self, instrument_id: int) -> InstrumentData:
        instrument = self.db.get(Instrument, instrument_id)
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found.")
        location = self.db.get(Location, instrument.location_id)
        vendor = self.db.get(Vendor, instrument.vendor_id)
        type_ = self.db.get(Type, instrument.type_id)
        instrument.location = location
        instrument.vendor = vendor
        instrument.type = type_
        return _to_data(instrument)
