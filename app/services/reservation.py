"""Business logic for reservation creation, conflict detection, and listing.

Enforces time-boundary rules (end after start, 30-minute boundaries),
detects overlapping reservations, refuses non-overridable conflicts, and
soft-deletes overridable conflicts while recording an audit trail.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.contracts import (
    InvalidInstrumentStatusError,
    NotFoundError,
    ReservationConflictError,
    ReservationCreateDTO,
    ReservationDTO,
    ReservationResultDTO,
    TimeBoundaryError,
)
from app.models import (
    AuditActionType,
    AuditEntityType,
    Instrument,
    InstrumentStatus,
    Reservation,
    ReservationPurpose,
)
from app.services.audit_log import AuditLogService

_MAX_REQUESTED_BY_LENGTH = 120
_UNSCHEDULABLE_STATUSES = {
    InstrumentStatus.DECOMMISSIONED,
    InstrumentStatus.UNDER_MAINTENANCE,
}


def _to_dto(reservation: Reservation, instrument_name: str, purpose_name: str) -> ReservationDTO:
    return ReservationDTO(
        reservation_id=reservation.reservation_id,
        instrument_id=reservation.instrument_id,
        instrument_name=instrument_name,
        start_datetime=reservation.start_datetime,
        end_datetime=reservation.end_datetime,
        reservation_purpose_id=reservation.reservation_purpose_id,
        purpose_name=purpose_name,
        requested_by=reservation.requested_by,
        can_be_overridden=reservation.can_be_overridden,
        is_active=reservation.is_active,
    )


class ReservationService:
    """Service layer for reservation validation, conflict handling, listing."""

    def __init__(self, db: Session) -> None:
        self._db = db
        self._audit = AuditLogService(db)

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _validate_time_boundaries(start: datetime, end: datetime) -> None:
        if end <= start:
            raise TimeBoundaryError("End time must be after start time")
        if start.minute % 30 != 0 or start.second != 0 or start.microsecond != 0:
            raise TimeBoundaryError("Start time must fall on a 30-minute boundary")
        if end.minute % 30 != 0 or end.second != 0 or end.microsecond != 0:
            raise TimeBoundaryError("End time must fall on a 30-minute boundary")

    def _get_instrument_names(self, instrument_id: int) -> tuple[str, InstrumentStatus]:
        instrument = (
            self._db.query(Instrument).filter(Instrument.instrument_id == instrument_id).one_or_none()
        )
        if instrument is None:
            raise NotFoundError(f"Instrument {instrument_id} not found")
        return instrument.name, instrument.status

    def _get_purpose_name(self, purpose_id: int) -> str:
        purpose = (
            self._db.query(ReservationPurpose)
            .filter(ReservationPurpose.reservation_purpose_id == purpose_id)
            .one_or_none()
        )
        if purpose is None:
            raise NotFoundError(f"ReservationPurpose {purpose_id} not found")
        return purpose.name

    def _find_conflicts(
        self, instrument_id: int, start: datetime, end: datetime
    ) -> list[Reservation]:
        return (
            self._db.query(Reservation)
            .filter(
                Reservation.instrument_id == instrument_id,
                Reservation.is_active.is_(True),
                Reservation.start_datetime < end,
                Reservation.end_datetime > start,
            )
            .all()
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def create(self, data: ReservationCreateDTO) -> ReservationResultDTO:
        """Create a reservation, resolving conflicts per override rules."""
        self._validate_time_boundaries(data.start_datetime, data.end_datetime)

        instrument_name, status = self._get_instrument_names(data.instrument_id)
        if status in _UNSCHEDULABLE_STATUSES:
            status_label = status.value if hasattr(status, "value") else status
            raise InvalidInstrumentStatusError(
                f"Instrument {instrument_name} is not available for scheduling (status: {status_label})."
            )

        purpose_name = self._get_purpose_name(data.reservation_purpose_id)

        conflicts = self._find_conflicts(data.instrument_id, data.start_datetime, data.end_datetime)
        non_overridable = [c for c in conflicts if not c.can_be_overridden]
        if non_overridable:
            conflict = non_overridable[0]
            raise ReservationConflictError(
                f"Conflicts with existing reservation #{conflict.reservation_id} "
                f"({conflict.start_datetime.isoformat()} - {conflict.end_datetime.isoformat()})"
            )

        requested_by_raw = (data.requested_by or "").strip()
        requested_by_trimmed = requested_by_raw[:_MAX_REQUESTED_BY_LENGTH]
        actor = requested_by_trimmed if requested_by_trimmed else "Unknown"

        reservation = Reservation(
            instrument_id=data.instrument_id,
            start_datetime=data.start_datetime,
            end_datetime=data.end_datetime,
            reservation_purpose_id=data.reservation_purpose_id,
            requested_by=actor,
            can_be_overridden=data.can_be_overridden,
            is_active=True,
        )
        self._db.add(reservation)
        self._db.flush()

        overridden_ids: list[int] = []
        overridden_descriptions: list[str] = []
        for conflict in conflicts:
            overridden_ids.append(conflict.reservation_id)
            overridden_descriptions.append(
                f"#{conflict.reservation_id} ({conflict.start_datetime.isoformat()} - "
                f"{conflict.end_datetime.isoformat()})"
            )
            conflict.is_active = False
        self._db.flush()

        if overridden_ids:
            description = (
                f"Created reservation #{reservation.reservation_id} for instrument "
                f"'{instrument_name}'; replaced: {', '.join(overridden_descriptions)}"
            )
        else:
            description = (
                f"Created reservation #{reservation.reservation_id} for instrument '{instrument_name}'"
            )

        self._audit.log(
            actor=actor,
            action_type=AuditActionType.CREATE,
            entity_type=AuditEntityType.RESERVATION,
            entity_id=reservation.reservation_id,
            description=description,
        )
        self._db.commit()

        dto = _to_dto(reservation, instrument_name, purpose_name)
        return ReservationResultDTO(reservation=dto, overridden_ids=overridden_ids)

    def list_reservations(
        self, instrument_id: int, start_date: datetime, end_date: datetime
    ) -> list[ReservationDTO]:
        """List active reservations for an instrument within a date range."""
        instrument_name, _ = self._get_instrument_names(instrument_id)
        reservations = (
            self._db.query(Reservation)
            .filter(
                Reservation.instrument_id == instrument_id,
                Reservation.is_active.is_(True),
                Reservation.start_datetime < end_date,
                Reservation.end_datetime > start_date,
            )
            .order_by(Reservation.start_datetime.asc())
            .all()
        )
        results = []
        for reservation in reservations:
            purpose_name = self._get_purpose_name(reservation.reservation_purpose_id)
            results.append(_to_dto(reservation, instrument_name, purpose_name))
        return results
