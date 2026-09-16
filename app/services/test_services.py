"""Unit tests for instrument, master data, reservation, and scheduler services."""

from datetime import date, datetime, timezone

import pytest

from app.contracts import (
    ConflictError,
    DuplicateError,
    InstrumentCreateData,
    ReservationCreateData,
    ValidationError,
)
from app.models import Instrument, InstrumentStatus, Location, ReservationPurpose, Type, Vendor

from app.services.audit import AuditService
from app.services.instrument import InstrumentService
from app.services.master_data import MasterDataService
from app.services.reservation import ReservationService
from app.services.scheduler import SchedulerService


def _make_master_data(db):
    location = Location(name="Main Lab", is_active=True)
    vendor = Vendor(name="Agilent", is_active=True)
    type_ = Type(name="Chromatograph", is_active=True)
    purpose = ReservationPurpose(name="Research", is_active=True)
    db.add_all([location, vendor, type_, purpose])
    db.flush()
    return location, vendor, type_, purpose


def _make_instrument(db, location, vendor, type_, status=InstrumentStatus.ACTIVE, name="Instrument A", nickname="Inst-A"):
    instrument = Instrument(
        name=name,
        nickname=nickname,
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=type_.type_id,
        asset_id="AST-1",
        color="#FF0000",
        status=status,
        is_active=True,
        is_favorite=False,
    )
    db.add(instrument)
    db.flush()
    return instrument


def test_create_instrument_writes_record_and_audit(db_session):
    location, vendor, type_, _ = _make_master_data(db_session)

    service = InstrumentService(db_session)
    data = InstrumentCreateData(
        nickname="Inst-A",
        name="Instrument A",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=type_.type_id,
        asset_id="AST-100",
        color="#00FF00",
        status="Active",
        is_active=True,
        actor="jane.doe",
    )

    result = service.create_instrument(data)

    assert result.instrument_id is not None
    assert result.name == "Instrument A"
    assert result.nickname == "Inst-A"
    assert result.asset_id == "AST-100"
    assert result.is_active is True

    persisted = db_session.get(Instrument, result.instrument_id)
    assert persisted is not None
    assert persisted.name == "Instrument A"

    audit_entries = AuditService(db_session).list_entries()
    matching = [e for e in audit_entries if e.entity_id == result.instrument_id]
    assert len(matching) == 1
    entry = matching[0]
    assert entry.actor == "jane.doe"
    assert entry.action_type == "Create"
    assert "Instrument A" in entry.description
    assert "Inst-A" in entry.description
    assert str(location.location_id) in entry.description
    assert str(vendor.vendor_id) in entry.description
    assert str(type_.type_id) in entry.description
    assert "AST-100" in entry.description
    assert "#00FF00" in entry.description
    assert "Active" in entry.description


def test_create_vendor_duplicate_case_insensitive_raises(db_session):
    service = MasterDataService(db_session)
    service.create_vendor("Vendor A", "actor1")

    with pytest.raises(DuplicateError):
        service.create_vendor("vendor a", "actor2")


def test_create_location_duplicate_whitespace_insensitive_raises(db_session):
    service = MasterDataService(db_session)
    service.create_location("Main   Lab", "actor1")

    with pytest.raises(DuplicateError):
        service.create_location("  main lab  ", "actor2")


def test_reservation_start_time_not_on_boundary_raises_validation_error(db_session):
    location, vendor, type_, purpose = _make_master_data(db_session)
    instrument = _make_instrument(db_session, location, vendor, type_)

    service = ReservationService(db_session)
    data = ReservationCreateData(
        instrument_id=instrument.instrument_id,
        start_time=datetime(2025, 1, 15, 10, 15, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc),
        purpose_id=purpose.reservation_purpose_id,
        requested_by="jane.doe",
        can_be_overridden=True,
    )

    with pytest.raises(ValidationError) as exc_info:
        service.create_reservation(data)

    assert str(exc_info.value) == "Times must fall on a 30-minute boundary."


def test_reservation_end_before_start_raises_validation_error(db_session):
    location, vendor, type_, purpose = _make_master_data(db_session)
    instrument = _make_instrument(db_session, location, vendor, type_)

    service = ReservationService(db_session)
    data = ReservationCreateData(
        instrument_id=instrument.instrument_id,
        start_time=datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
        purpose_id=purpose.reservation_purpose_id,
        requested_by="jane.doe",
        can_be_overridden=True,
    )

    with pytest.raises(ValidationError):
        service.create_reservation(data)


def test_reservation_conflict_with_non_overridable_raises_conflict_error(db_session):
    location, vendor, type_, purpose = _make_master_data(db_session)
    instrument = _make_instrument(db_session, location, vendor, type_)

    service = ReservationService(db_session)

    # Overridable existing reservation, 10:00-11:00
    overridable_data = ReservationCreateData(
        instrument_id=instrument.instrument_id,
        start_time=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc),
        purpose_id=purpose.reservation_purpose_id,
        requested_by="alice",
        can_be_overridden=True,
    )
    service.create_reservation(overridable_data)

    # Non-overridable existing reservation, 11:00-12:00 (adjacent, will also overlap new one)
    non_overridable_data = ReservationCreateData(
        instrument_id=instrument.instrument_id,
        start_time=datetime(2025, 1, 15, 11, 0, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc),
        purpose_id=purpose.reservation_purpose_id,
        requested_by="bob",
        can_be_overridden=False,
    )
    non_overridable_result = service.create_reservation(non_overridable_data)

    # New reservation overlapping both: 10:30-11:30
    new_data = ReservationCreateData(
        instrument_id=instrument.instrument_id,
        start_time=datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 15, 11, 30, tzinfo=timezone.utc),
        purpose_id=purpose.reservation_purpose_id,
        requested_by="carol",
        can_be_overridden=True,
    )

    with pytest.raises(ConflictError) as exc_info:
        service.create_reservation(new_data)

    message = str(exc_info.value)
    assert f"#{non_overridable_result.reservation_id}" in message
    assert "bob" in message


def test_reservation_overrides_all_overridable_conflicts(db_session):
    location, vendor, type_, purpose = _make_master_data(db_session)
    instrument = _make_instrument(db_session, location, vendor, type_)

    service = ReservationService(db_session)

    existing_data = ReservationCreateData(
        instrument_id=instrument.instrument_id,
        start_time=datetime(2025, 1, 15, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 15, 10, 0, tzinfo=timezone.utc),
        purpose_id=purpose.reservation_purpose_id,
        requested_by="alice",
        can_be_overridden=True,
    )
    existing_result = service.create_reservation(existing_data)

    new_data = ReservationCreateData(
        instrument_id=instrument.instrument_id,
        start_time=datetime(2025, 1, 15, 9, 30, tzinfo=timezone.utc),
        end_time=datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
        purpose_id=purpose.reservation_purpose_id,
        requested_by="carol",
        can_be_overridden=True,
    )
    result = service.create_reservation(new_data)

    assert existing_result.reservation_id in result.overridden_reservation_ids

    audit_entries = AuditService(db_session).list_entries()
    override_entries = [
        e for e in audit_entries if e.action_type == "ReservationOverridden"
    ]
    assert len(override_entries) == 1
    assert f"#{existing_result.reservation_id}" in override_entries[0].description


def test_scheduler_timeline_excludes_decommissioned_and_sorts(db_session):
    location, vendor, type_, purpose = _make_master_data(db_session)

    active_b = _make_instrument(
        db_session, location, vendor, type_, name="Zebra Analyzer", nickname="ZA-1"
    )
    active_a = _make_instrument(
        db_session, location, vendor, type_, name="Alpha Analyzer", nickname="AA-1"
    )
    decommissioned = _make_instrument(
        db_session,
        location,
        vendor,
        type_,
        status=InstrumentStatus.DECOMMISSIONED,
        name="Old Analyzer",
        nickname="OA-1",
    )
    db_session.flush()

    service = SchedulerService(db_session)
    timeline = service.get_timeline_data(date(2025, 1, 15), "day")

    instrument_ids = [i.instrument_id for i in timeline.instruments]
    assert decommissioned.instrument_id not in instrument_ids
    assert active_a.instrument_id in instrument_ids
    assert active_b.instrument_id in instrument_ids

    names_in_order = [i.name for i in timeline.instruments]
    assert names_in_order == sorted(names_in_order, key=str.lower)
    assert names_in_order.index("Alpha Analyzer") < names_in_order.index("Zebra Analyzer")
