"""Unit tests for ReservationService."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.contracts import (
    NotFoundError,
    ReservationConflictError,
    ReservationCreateDTO,
    TimeBoundaryError,
)
from app.models import Instrument, InstrumentStatus, Location, Reservation, ReservationPurpose, Type, Vendor
from app.services.reservation import ReservationService


@pytest.fixture
def instrument_and_purpose(db_session):
    location = Location(name="Lab 224", is_active=True)
    vendor = Vendor(name="Illumina", is_active=True)
    type_ = Type(name="Sequencer", is_active=True)
    db_session.add_all([location, vendor, type_])
    db_session.commit()

    instrument = Instrument(
        name="Sequencer A",
        nickname="SeqA",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=type_.type_id,
        asset_id="AST-1",
        color=None,
        status=InstrumentStatus.ACTIVE,
        is_favorite=False,
        is_active=True,
    )
    purpose = ReservationPurpose(name="Sample analysis", is_active=True)
    db_session.add_all([instrument, purpose])
    db_session.commit()
    return instrument, purpose


def test_create_refuses_end_before_start(db_session, instrument_and_purpose):
    instrument, purpose = instrument_and_purpose
    service = ReservationService(db_session)
    start = datetime(2024, 1, 1, 10, 0)
    end = datetime(2024, 1, 1, 9, 30)

    with pytest.raises(TimeBoundaryError):
        service.create(
            ReservationCreateDTO(
                instrument_id=instrument.instrument_id,
                start_datetime=start,
                end_datetime=end,
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by=None,
                can_be_overridden=True,
            )
        )


def test_create_refuses_non_30_minute_boundary(db_session, instrument_and_purpose):
    instrument, purpose = instrument_and_purpose
    service = ReservationService(db_session)
    start = datetime(2024, 1, 1, 10, 17)
    end = datetime(2024, 1, 1, 10, 47)

    with pytest.raises(TimeBoundaryError) as exc_info:
        service.create(
            ReservationCreateDTO(
                instrument_id=instrument.instrument_id,
                start_datetime=start,
                end_datetime=end,
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by=None,
                can_be_overridden=True,
            )
        )
    assert "30-minute boundary" in str(exc_info.value)


def test_create_accepts_valid_30_minute_boundary(db_session, instrument_and_purpose):
    instrument, purpose = instrument_and_purpose
    service = ReservationService(db_session)
    start = datetime(2024, 1, 1, 10, 0)
    end = datetime(2024, 1, 1, 10, 30)

    result = service.create(
        ReservationCreateDTO(
            instrument_id=instrument.instrument_id,
            start_datetime=start,
            end_datetime=end,
            reservation_purpose_id=purpose.reservation_purpose_id,
            requested_by=None,
            can_be_overridden=True,
        )
    )

    assert result.reservation.reservation_id is not None
    assert result.overridden_ids == []
    assert result.reservation.requested_by == "Unknown"


def test_create_raises_conflict_error_when_non_overridable(db_session, instrument_and_purpose):
    instrument, purpose = instrument_and_purpose
    service = ReservationService(db_session)

    existing = Reservation(
        instrument_id=instrument.instrument_id,
        start_datetime=datetime(2024, 1, 1, 10, 30),
        end_datetime=datetime(2024, 1, 1, 11, 30),
        reservation_purpose_id=purpose.reservation_purpose_id,
        requested_by="Alice",
        can_be_overridden=False,
        is_active=True,
    )
    db_session.add(existing)
    db_session.commit()

    with pytest.raises(ReservationConflictError) as exc_info:
        service.create(
            ReservationCreateDTO(
                instrument_id=instrument.instrument_id,
                start_datetime=datetime(2024, 1, 1, 10, 0),
                end_datetime=datetime(2024, 1, 1, 11, 0),
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by="Bob",
                can_be_overridden=True,
            )
        )
    assert str(existing.reservation_id) in str(exc_info.value)

    # The conflicting reservation must remain untouched.
    refreshed = (
        db_session.query(Reservation)
        .filter(Reservation.reservation_id == existing.reservation_id)
        .one()
    )
    assert refreshed.is_active is True


def test_create_soft_deletes_overridable_conflict_and_returns_summary(db_session, instrument_and_purpose):
    instrument, purpose = instrument_and_purpose
    service = ReservationService(db_session)

    existing = Reservation(
        instrument_id=instrument.instrument_id,
        start_datetime=datetime(2024, 1, 1, 10, 30),
        end_datetime=datetime(2024, 1, 1, 11, 30),
        reservation_purpose_id=purpose.reservation_purpose_id,
        requested_by="Alice",
        can_be_overridden=True,
        is_active=True,
    )
    db_session.add(existing)
    db_session.commit()
    existing_id = existing.reservation_id

    result = service.create(
        ReservationCreateDTO(
            instrument_id=instrument.instrument_id,
            start_datetime=datetime(2024, 1, 1, 10, 0),
            end_datetime=datetime(2024, 1, 1, 11, 0),
            reservation_purpose_id=purpose.reservation_purpose_id,
            requested_by="  Bob  ",
            can_be_overridden=True,
        )
    )

    assert result.overridden_ids == [existing_id]
    assert result.reservation.requested_by == "Bob"

    refreshed = (
        db_session.query(Reservation).filter(Reservation.reservation_id == existing_id).one()
    )
    assert refreshed.is_active is False


def test_create_raises_not_found_for_unknown_instrument(db_session, instrument_and_purpose):
    _, purpose = instrument_and_purpose
    service = ReservationService(db_session)

    with pytest.raises(NotFoundError):
        service.create(
            ReservationCreateDTO(
                instrument_id=999999,
                start_datetime=datetime(2024, 1, 1, 10, 0),
                end_datetime=datetime(2024, 1, 1, 10, 30),
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by=None,
                can_be_overridden=True,
            )
        )
