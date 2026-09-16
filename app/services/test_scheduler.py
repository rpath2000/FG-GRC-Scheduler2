"""Unit tests for SchedulerService."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.models import Instrument, InstrumentStatus, Location, Reservation, ReservationPurpose, Type, Vendor
from app.services.scheduler import SchedulerService


@pytest.fixture
def master_data(db_session):
    location = Location(name="Lab 224", is_active=True)
    vendor = Vendor(name="Illumina", is_active=True)
    type_ = Type(name="Sequencer", is_active=True)
    purpose = ReservationPurpose(name="Sample analysis", is_active=True)
    db_session.add_all([location, vendor, type_, purpose])
    db_session.commit()
    return {"location": location, "vendor": vendor, "type": type_, "purpose": purpose}


def _make_instrument(db_session, master_data, name, nickname, status=InstrumentStatus.ACTIVE, is_active=True):
    instrument = Instrument(
        name=name,
        nickname=nickname,
        location_id=master_data["location"].location_id,
        vendor_id=master_data["vendor"].vendor_id,
        type_id=master_data["type"].type_id,
        asset_id="A1",
        color=None,
        status=status,
        is_favorite=False,
        is_active=is_active,
    )
    db_session.add(instrument)
    db_session.commit()
    return instrument


def test_get_timeline_excludes_decommissioned_and_maintenance(db_session, master_data):
    _make_instrument(db_session, master_data, "Zed", "Z", status=InstrumentStatus.ACTIVE)
    _make_instrument(db_session, master_data, "Decom", "D", status=InstrumentStatus.DECOMMISSIONED)
    _make_instrument(db_session, master_data, "Maint", "M", status=InstrumentStatus.UNDER_MAINTENANCE)

    service = SchedulerService(db_session)
    timeline = service.get_timeline(datetime(2024, 1, 1), "week")

    names = [i.name for i in timeline.instruments]
    assert "Decom" not in names
    assert "Maint" not in names
    assert "Zed" in names


def test_get_timeline_excludes_inactive_instruments(db_session, master_data):
    _make_instrument(db_session, master_data, "Active One", "A1", is_active=True)
    _make_instrument(db_session, master_data, "Inactive One", "I1", is_active=False)

    service = SchedulerService(db_session)
    timeline = service.get_timeline(datetime(2024, 1, 1), "week")

    names = [i.name for i in timeline.instruments]
    assert "Active One" in names
    assert "Inactive One" not in names


def test_get_timeline_sorted_name_then_nickname(db_session, master_data):
    _make_instrument(db_session, master_data, "Alpha", "B")
    _make_instrument(db_session, master_data, "Alpha", "A")
    _make_instrument(db_session, master_data, "Zeta", "Z")

    service = SchedulerService(db_session)
    timeline = service.get_timeline(datetime(2024, 1, 1), "week")

    pairs = [(i.name, i.nickname) for i in timeline.instruments]
    assert pairs == [("Alpha", "A"), ("Alpha", "B"), ("Zeta", "Z")]


def test_get_timeline_returns_reservations_in_range(db_session, master_data):
    instrument = _make_instrument(db_session, master_data, "Seq", "S1")
    reservation = Reservation(
        instrument_id=instrument.instrument_id,
        start_datetime=datetime(2024, 1, 2, 10, 0),
        end_datetime=datetime(2024, 1, 2, 11, 0),
        reservation_purpose_id=master_data["purpose"].reservation_purpose_id,
        requested_by="Unknown",
        can_be_overridden=True,
        is_active=True,
    )
    db_session.add(reservation)
    db_session.commit()

    service = SchedulerService(db_session)
    timeline = service.get_timeline(datetime(2024, 1, 1), "week")

    assert len(timeline.reservations) == 1
    assert timeline.reservations[0].instrument_id == instrument.instrument_id


def test_get_timeline_day_view_range_is_one_day(db_session, master_data):
    service = SchedulerService(db_session)
    timeline = service.get_timeline(datetime(2024, 1, 1, 15, 30), "day")

    assert timeline.end_date - timeline.start_date == timedelta(days=1)
    assert timeline.start_date.hour == 0
