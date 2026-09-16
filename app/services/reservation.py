"""Business logic for reservation creation, conflict detection, and override."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    AuditActionType,
    AuditEntityType,
    ConflictError,
    InvalidStatusError,
    NotFoundError,
    ReservationCreateData,
    ReservationResult,
    ValidationError,
)
from app.models import Instrument, InstrumentStatus, Reservation

from app.services.audit import AuditService

_EXCLUDED_STATUSES = (InstrumentStatus.DECOMMISSIONED, InstrumentStatus.MAINTENANCE)


def _on_boundary(dt: datetime) -> bool:
    return dt.minute % 30 == 0 and dt.second == 0 and dt.microsecond == 0


class ReservationService:
    """Handles reservation creation, time validation, and conflict resolution."""

    def __init__(self, db: Session):
        self.db = db

    def create_reservation(self, data: ReservationCreateData) -> ReservationResult:
        if not _on_boundary(data.start_time):
            raise ValidationError("Times must fall on a 30-minute boundary.")
        if not _on_boundary(data.end_time):
            raise ValidationError("Times must fall on a 30-minute boundary.")
        if data.end_time <= data.start_time:
            raise ValidationError("End time must be after start time.")

        instrument = self.db.get(Instrument, data.instrument_id)
        if instrument is None:
            raise NotFoundError(f"Instrument {data.instrument_id} not found.")
        if not instrument.is_active or instrument.status in _EXCLUDED_STATUSES:
            raise InvalidStatusError(
                "Instrument is decommissioned or under maintenance and cannot be scheduled."
            )

        conflicts = self._find_conflicts(
            data.instrument_id, data.start_time, data.end_time
        )

        non_overridable = [c for c in conflicts if not c.can_be_overridden]
        if non_overridable:
            names = ", ".join(
                f"Reservation #{c.reservation_id} ({c.requested_by})"
                for c in non_overridable
            )
            raise ConflictError(
                f"Conflicts with non-overridable reservation(s): {names}."
            )

        actor = data.requested_by or "Unknown"
        overridden_ids: list[int] = []
        for conflict in conflicts:
            conflict.is_active = False
            overridden_ids.append(conflict.reservation_id)

        reservation = Reservation(
            instrument_id=data.instrument_id,
            start_date_time=data.start_time,
            end_date_time=data.end_time,
            reservation_purpose_id=data.purpose_id,
            requested_by=actor,
            can_be_overridden=data.can_be_overridden,
            is_active=True,
        )
        self.db.add(reservation)
        self.db.flush()
        self.db.refresh(reservation)

        audit = AuditService(self.db)
        audit.record_action(
            action_type=AuditActionType.RESERVATION_CREATED,
            entity_type=AuditEntityType.RESERVATION,
            entity_id=reservation.reservation_id,
            actor=actor,
            description=(
                f"Created reservation for InstrumentId={data.instrument_id}, "
                f"Start={data.start_time.isoformat()}, End={data.end_time.isoformat()}, "
                f"PurposeId={data.purpose_id}"
            ),
        )

        if overridden_ids:
            replaced_names = ", ".join(
                f"Reservation #{cid}" for cid in overridden_ids
            )
            audit.record_action(
                action_type=AuditActionType.RESERVATION_OVERRIDDEN,
                entity_type=AuditEntityType.RESERVATION,
                entity_id=reservation.reservation_id,
                actor=actor,
                description=(
                    f"Reservation #{reservation.reservation_id} overrode and replaced: "
                    f"{replaced_names}."
                ),
            )

        self.db.commit()
        return ReservationResult(
            reservation_id=reservation.reservation_id,
            overridden_reservation_ids=overridden_ids,
        )

    def _find_conflicts(
        self, instrument_id: int, start: datetime, end: datetime
    ) -> list[Reservation]:
        stmt = (
            select(Reservation)
            .where(Reservation.instrument_id == instrument_id)
            .where(Reservation.is_active.is_(True))
            .where(Reservation.start_date_time < end)
            .where(Reservation.end_date_time > start)
        )
        return list(self.db.execute(stmt).scalars().all())
