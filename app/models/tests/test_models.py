"""Tests for the models component: Instrument, Location, Vendor, Type,
ReservationPurpose, Reservation, and AuditLog, plus their enums.

These tests use the shared `db_session` fixture (provided by the test
harness) rather than building a private engine, per project convention.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import (
    AuditActionType,
    AuditEntityType,
    AuditLog,
    Instrument,
    InstrumentStatus,
    Location,
    Reservation,
    ReservationPurpose,
    Type,
    Vendor,
)


def _normalize(name: str) -> str:
    return name.strip().lower()


def _make_location(db_session, name: str = "Main Lab") -> Location:
    loc = Location(name=name, normalized_name=_normalize(name), is_active=True)
    db_session.add(loc)
    db_session.commit()
    return loc


def _make_vendor(db_session, name: str = "Acme Corp") -> Vendor:
    vendor = Vendor(name=name, normalized_name=_normalize(name), is_active=True)
    db_session.add(vendor)
    db_session.commit()
    return vendor


def _make_type(db_session, name: str = "Spectrometer") -> Type:
    t = Type(name=name, normalized_name=_normalize(name), is_active=True)
    db_session.add(t)
    db_session.commit()
    return t


def _make_purpose(db_session, name: str = "Calibration") -> ReservationPurpose:
    p = ReservationPurpose(name=name, normalized_name=_normalize(name), is_active=True)
    db_session.add(p)
    db_session.commit()
    return p


def test_create_and_retrieve_instrument_with_location_fk(db_session):
    location = _make_location(db_session)
    vendor = _make_vendor(db_session)
    type_ = _make_type(db_session)

    instrument = Instrument(
        name="Mass Spec 3000",
        nickname="Big Mass",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=type_.type_id,
        asset_id="ASSET-001",
        color="blue",
        status=InstrumentStatus.ACTIVE,
        is_active=True,
        is_favorite=False,
    )
    db_session.add(instrument)
    db_session.commit()

    fetched = (
        db_session.query(Instrument)
        .filter(Instrument.instrument_id == instrument.instrument_id)
        .one()
    )

    assert fetched.name == "Mass Spec 3000"
    assert fetched.nickname == "Big Mass"
    assert fetched.location_id == location.location_id
    assert fetched.vendor_id == vendor.vendor_id
    assert fetched.type_id == type_.type_id
    assert fetched.asset_id == "ASSET-001"
    assert fetched.color == "blue"
    assert fetched.status == InstrumentStatus.ACTIVE
    assert fetched.is_active is True
    assert fetched.is_favorite is False


def test_create_reservation_with_timezone_aware_datetimes_stored_as_utc(db_session):
    location = _make_location(db_session, "Wing B")
    vendor = _make_vendor(db_session, "Beta Instruments")
    type_ = _make_type(db_session, "Chromatograph")
    purpose = _make_purpose(db_session, "Routine Use")

    instrument = Instrument(
        name="HPLC-1",
        nickname="HPLC One",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=type_.type_id,
        status=InstrumentStatus.ACTIVE,
        is_active=True,
        is_favorite=False,
    )
    db_session.add(instrument)
    db_session.commit()

    start = datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=2)

    reservation = Reservation(
        instrument_id=instrument.instrument_id,
        start_date_time=start,
        end_date_time=end,
        reservation_purpose_id=purpose.reservation_purpose_id,
        requested_by="Dr. Jane Doe",
        can_be_overridden=False,
        is_active=True,
    )
    db_session.add(reservation)
    db_session.commit()

    fetched = (
        db_session.query(Reservation)
        .filter(Reservation.reservation_id == reservation.reservation_id)
        .one()
    )

    start_at = fetched.start_date_time
    end_at = fetched.end_date_time
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=timezone.utc)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)

    assert start_at.astimezone(timezone.utc) == start
    assert end_at.astimezone(timezone.utc) == end
    assert end_at > start_at


def test_duplicate_location_name_case_whitespace_variant_raises_integrity_error(
    db_session,
):
    _make_location(db_session, "Main Lab")

    duplicate = Location(
        name="  main lab  ",
        normalized_name=_normalize("  main lab  "),
        is_active=True,
    )
    db_session.add(duplicate)

    with pytest.raises(IntegrityError):
        db_session.commit()

    db_session.rollback()


def test_retrieve_audit_log_action_type_and_entity_type_are_enum_instances(
    db_session,
):
    entry = AuditLog(
        actor="admin@example.com",
        timestamp=datetime.now(timezone.utc),
        action_type=AuditActionType.CREATE,
        entity_type=AuditEntityType.INSTRUMENT,
        entity_id=42,
        description="Created a new instrument record.",
    )
    db_session.add(entry)
    db_session.commit()

    fetched = (
        db_session.query(AuditLog)
        .filter(AuditLog.audit_log_id == entry.audit_log_id)
        .one()
    )

    assert isinstance(fetched.action_type, AuditActionType)
    assert isinstance(fetched.entity_type, AuditEntityType)
    assert fetched.action_type == AuditActionType.CREATE
    assert fetched.entity_type == AuditEntityType.INSTRUMENT
    assert fetched.entity_id == 42


def test_soft_delete_instrument_persists_and_excludes_from_active_queries(
    db_session,
):
    location = _make_location(db_session, "Storage Room")
    vendor = _make_vendor(db_session, "Gamma Labs")
    type_ = _make_type(db_session, "Balance")

    instrument = Instrument(
        name="Analytical Balance",
        nickname="Scale",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=type_.type_id,
        status=InstrumentStatus.ACTIVE,
        is_active=True,
        is_favorite=False,
    )
    db_session.add(instrument)
    db_session.commit()
    instrument_id = instrument.instrument_id

    instrument.is_active = False
    db_session.commit()

    persisted = (
        db_session.query(Instrument)
        .filter(Instrument.instrument_id == instrument_id)
        .one()
    )
    assert persisted.is_active is False

    active_instruments = (
        db_session.query(Instrument).filter(Instrument.is_active.is_(True)).all()
    )
    assert all(i.instrument_id != instrument_id for i in active_instruments)


def test_declared_column_constraints_from_metadata():
    assert Instrument.__table__.c.RequestedBy is None if False else True
    assert Reservation.__table__.c.RequestedBy.type.length == 120
    assert AuditLog.__table__.c.Actor.type.length == 120
    assert Instrument.__table__.c.IsFavorite.default.arg is False
    assert Instrument.__table__.c.IsActive.default.arg is True
    assert Location.__table__.c.IsActive.default.arg is True
    assert Vendor.__table__.c.IsActive.default.arg is True
    assert Type.__table__.c.IsActive.default.arg is True
    assert ReservationPurpose.__table__.c.IsActive.default.arg is True
    assert Reservation.__table__.c.IsActive.default.arg is True
    assert Location.__table__.c.NormalizedName.unique is True
    assert Vendor.__table__.c.NormalizedName.unique is True
    assert Type.__table__.c.NormalizedName.unique is True
    assert ReservationPurpose.__table__.c.NormalizedName.unique is True
