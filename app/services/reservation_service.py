"""ReservationService: creation with validation/conflict detection, and listing."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    ConflictError,
    NotFoundError,
    ReservationCreateDTO,
    ReservationDTO,
    ReservationResultDTO,
    ValidationError,
    InvalidStatusError,
)
from app.models import Instrument, Reservation, ReservationPurpose
from app.services.audit_service import AuditService

_SLOT_MINUTES = 30


def _on_boundary(dt: datetime) -> bool:
    """Return True if `dt` falls on a 30-minute boundary (minute in {0, 30}, second/micro == 0)."""
    return dt.minute % _SLOT_MINUTES == 0 and dt.second == 0 and dt.microsecond == 0


class ReservationService:
    """Business logic for reservation creation and lookup."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._audit = AuditService(db)

    # -- helpers ----------------------------------------------------------

    def _to_dto(self, reservation: Reservation) -> ReservationDTO:
        instrument = self._db.get(Instrument, reservation.instrument_id)
        purpose = self._db.get(ReservationPurpose, reservation.reservation_purpose_id)
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

    def _find_conflicts(
        self, instrument_id: int, start: datetime, end: datetime, exclude_id: int | None = None
    ) -> list[Reservation]:
        stmt = select(Reservation).where(
            Reservation.instrument_id == instrument_id,
            Reservation.is_active.is_(True),
        )
        rows = self._db.execute(stmt).scalars().all()
        conflicts = []
        for row in rows:
            if exclude_id is not None and row.reservation_id == exclude_id:
                continue
            # Overlap if start < other.end and end > other.start
            if start < row.end_datetime and end > row.start_datetime:
                conflicts.append(row)
        return conflicts

    # -- public API ---------------------------------------------------------

    def create(self, data: ReservationCreateDTO) -> ReservationResultDTO:
        instrument = self._db.get(Instrument, data.instrument_id)
        if instrument is None:
            raise NotFoundError(f"Instrument {data.instrument_id} not found")

        status_value = instrument.status.value if hasattr(instrument.status, "value") else str(instrument.status)
        if status_value.upper() in ("DECOMMISSIONED", "MAINTENANCE"):
            raise InvalidStatusError(
                f"Instrument '{instrument.name}' is {status_value} and cannot be scheduled"
            )
        if not instrument.is_active:
            raise InvalidStatusError(f"Instrument '{instrument.name}' is inactive and cannot be scheduled")

        start = data.start_datetime
        end = data.end_datetime

        if end <= start:
            raise ValidationError("Reservation end_datetime must be after start_datetime")
        if not _on_boundary(start) or not _on_boundary(end):
            raise ValidationError("Reservation times must fall on 30-minute boundaries")

        conflicts = self._find_conflicts(data.instrument_id, start, end)

        non_overridable = [c for c in conflicts if not c.can_be_overridden]
        if non_overridable:
            first = non_overridable[0]
            purpose = self._db.get(ReservationPurpose, first.reservation_purpose_id)
            purpose_name = purpose.name if purpose else "reservation"
            raise ConflictError(
                f"Conflicts with existing non-overridable reservation "
                f"'{purpose_name}' ({first.start_datetime.isoformat()} - {first.end_datetime.isoformat()}) "
                f"requested by {first.requested_by}"
            )

        overridable = [c for c in conflicts if c.can_be_overridden]
        overridden_ids: list[int] = []
        for conflict in overridable:
            conflict.is_active = False
            overridden_ids.append(conflict.reservation_id)

        requested_by = data.requested_by.strip() if data.requested_by and data.requested_by.strip() else "Unknown"

        reservation = Reservation(
            instrument_id=data.instrument_id,
            start_datetime=start,
            end_datetime=end,
            reservation_purpose_id=data.reservation_purpose_id,
            requested_by=requested_by,
            can_be_overridden=data.can_be_overridden,
            is_active=True,
        )
        self._db.add(reservation)
        self._db.commit()
        self._db.refresh(reservation)

        self._audit.log_action(
            actor=requested_by,
            action_type="CREATE",
            entity_type="RESERVATION",
            entity_id=reservation.reservation_id,
            description=(
                f"Created reservation for instrument '{instrument.name}' "
                f"from {start.isoformat()} to {end.isoformat()}"
            ),
        )

        if overridden_ids:
            self._audit.log_action(
                actor=requested_by,
                action_type="OVERRIDE",
                entity_type="RESERVATION",
                entity_id=reservation.reservation_id,
                description=(
                    f"Overrode and soft-deleted conflicting reservations "
                    f"{sorted(overridden_ids)} to create reservation {reservation.reservation_id}"
                ),
            )

        return ReservationResultDTO(
            reservation=self._to_dto(reservation),
            overridden_ids=overridden_ids,
        )

    def list_by_instrument_and_range(
        self, instrument_ids: list[int], start: datetime, end: datetime
    ) -> list[ReservationDTO]:
        if not instrument_ids:
            return []
        stmt = select(Reservation).where(
            Reservation.instrument_id.in_(instrument_ids),
            Reservation.is_active.is_(True),
            Reservation.start_datetime < end,
            Reservation.end_datetime > start,
        ).order_by(Reservation.start_datetime.asc())
        rows = self._db.execute(stmt).scalars().all()
        return [self._to_dto(row) for row in rows]
