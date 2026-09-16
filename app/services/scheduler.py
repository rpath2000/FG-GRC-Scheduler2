"""Business logic for the scheduler timeline view.

Fetches active, schedulable instruments and their active reservations
for a given date/view (day or week), sorted for consistent rendering.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.contracts import InstrumentDTO, ReservationDTO, SchedulerTimelineDTO
from app.models import (
    Instrument,
    InstrumentStatus,
    Location,
    Reservation,
    ReservationPurpose,
    Type,
    Vendor,
)

_UNSCHEDULABLE_STATUSES = {
    InstrumentStatus.DECOMMISSIONED,
    InstrumentStatus.UNDER_MAINTENANCE,
}


class SchedulerService:
    """Service that builds timeline DTOs for the scheduler page."""

    def __init__(self, db: Session) -> None:
        self._db = db

    @staticmethod
    def _resolve_range(date: datetime, view: str) -> tuple[datetime, datetime]:
        view_normalized = (view or "week").strip().lower()
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        if view_normalized == "day":
            return day_start, day_start + timedelta(days=1)
        if view_normalized == "week":
            # Week starts on the given date's day (per FRS: navigation is
            # relative, not calendar-week aligned).
            return day_start, day_start + timedelta(days=7)
        raise ValueError(f"Unsupported scheduler view: {view}")

    def get_timeline(self, date: datetime, view: str) -> SchedulerTimelineDTO:
        """Return instruments (active + schedulable) and their reservations
        for the requested date range, sorted by name then nickname.
        """
        start_date, end_date = self._resolve_range(date, view)

        instruments = (
            self._db.query(Instrument)
            .filter(
                Instrument.is_active.is_(True),
                Instrument.status == InstrumentStatus.ACTIVE,
            )
            .order_by(Instrument.name.asc(), Instrument.nickname.asc())
            .all()
        )

        location_map = {loc.location_id: loc.name for loc in self._db.query(Location).all()}
        vendor_map = {v.vendor_id: v.name for v in self._db.query(Vendor).all()}
        type_map = {t.type_id: t.name for t in self._db.query(Type).all()}
        purpose_map = {
            p.reservation_purpose_id: p.name for p in self._db.query(ReservationPurpose).all()
        }

        instrument_dtos: list[InstrumentDTO] = []
        instrument_ids: list[int] = []
        for instrument in instruments:
            status_value = (
                instrument.status.value if hasattr(instrument.status, "value") else instrument.status
            )
            instrument_dtos.append(
                InstrumentDTO(
                    instrument_id=instrument.instrument_id,
                    name=instrument.name,
                    nickname=instrument.nickname,
                    location_id=instrument.location_id,
                    location_name=location_map.get(instrument.location_id, ""),
                    vendor_id=instrument.vendor_id,
                    vendor_name=vendor_map.get(instrument.vendor_id, ""),
                    type_id=instrument.type_id,
                    type_name=type_map.get(instrument.type_id, ""),
                    asset_id=instrument.asset_id,
                    color=instrument.color,
                    status=status_value,
                    is_favorite=instrument.is_favorite,
                    is_active=instrument.is_active,
                )
            )
            instrument_ids.append(instrument.instrument_id)

        reservation_dtos: list[ReservationDTO] = []
        if instrument_ids:
            instrument_name_map = {i.instrument_id: i.name for i in instruments}
            reservations = (
                self._db.query(Reservation)
                .filter(
                    Reservation.instrument_id.in_(instrument_ids),
                    Reservation.is_active.is_(True),
                    Reservation.start_datetime < end_date,
                    Reservation.end_datetime > start_date,
                )
                .order_by(Reservation.start_datetime.asc())
                .all()
            )
            for reservation in reservations:
                reservation_dtos.append(
                    ReservationDTO(
                        reservation_id=reservation.reservation_id,
                        instrument_id=reservation.instrument_id,
                        instrument_name=instrument_name_map.get(reservation.instrument_id, ""),
                        start_datetime=reservation.start_datetime,
                        end_datetime=reservation.end_datetime,
                        reservation_purpose_id=reservation.reservation_purpose_id,
                        purpose_name=purpose_map.get(reservation.reservation_purpose_id, ""),
                        requested_by=reservation.requested_by,
                        can_be_overridden=reservation.can_be_overridden,
                        is_active=reservation.is_active,
                    )
                )

        return SchedulerTimelineDTO(
            instruments=instrument_dtos,
            reservations=reservation_dtos,
            start_date=start_date,
            end_date=end_date,
        )
