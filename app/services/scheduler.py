"""Business logic for generating scheduler timeline data."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import (
    InstrumentData,
    ReservationBlockData,
    TimelineData,
)
from app.models import Instrument, InstrumentStatus, Reservation

_DEFAULT_COLOR = "#3B6FB6"  # mid-blue


class SchedulerService:
    """Produces timeline data (instruments and reservation blocks) for the scheduler UI."""

    def __init__(self, db: Session):
        self.db = db

    def get_timeline_data(self, target_date: date, view: str) -> TimelineData:
        range_start, range_end = self._resolve_range(target_date, view)

        stmt = (
            select(Instrument)
            .where(Instrument.is_active.is_(True))
            .where(Instrument.status == InstrumentStatus.ACTIVE)
        )
        instruments = self.db.execute(stmt).scalars().all()
        instruments = sorted(instruments, key=lambda i: (i.name.lower(), i.nickname.lower()))

        instrument_map: dict[int, Instrument] = {i.instrument_id: i for i in instruments}
        instrument_data = [self._to_instrument_data(i) for i in instruments]

        if instrument_map:
            res_stmt = (
                select(Reservation)
                .where(Reservation.instrument_id.in_(instrument_map.keys()))
                .where(Reservation.is_active.is_(True))
                .where(Reservation.start_date_time < range_end)
                .where(Reservation.end_date_time > range_start)
            )
            reservations = self.db.execute(res_stmt).scalars().all()
        else:
            reservations = []

        blocks = [
            self._to_block_data(r, instrument_map.get(r.instrument_id))
            for r in reservations
        ]

        return TimelineData(instruments=instrument_data, reservations=blocks)

    @staticmethod
    def _resolve_range(target_date: date, view: str) -> tuple[datetime, datetime]:
        day_start = datetime.combine(target_date, time.min)
        if view == "week":
            weekday = target_date.weekday()
            week_start_date = target_date - timedelta(days=weekday)
            range_start = datetime.combine(week_start_date, time.min)
            range_end = range_start + timedelta(days=7)
            return range_start, range_end
        range_start = day_start
        range_end = day_start + timedelta(days=1)
        return range_start, range_end

    @staticmethod
    def _to_instrument_data(instrument: Instrument) -> InstrumentData:
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
            location_name="",
            vendor_id=instrument.vendor_id,
            vendor_name="",
            type_id=instrument.type_id,
            type_name="",
            asset_id=instrument.asset_id,
            color=instrument.color,
            status=status_value,
            is_active=instrument.is_active,
            is_favorite=instrument.is_favorite,
        )

    @staticmethod
    def _to_block_data(
        reservation: Reservation, instrument: Instrument | None
    ) -> ReservationBlockData:
        color = (instrument.color if instrument and instrument.color else None) or _DEFAULT_COLOR
        return ReservationBlockData(
            reservation_id=reservation.reservation_id,
            instrument_id=reservation.instrument_id,
            start_time=reservation.start_date_time,
            end_time=reservation.end_date_time,
            color=color,
        )
