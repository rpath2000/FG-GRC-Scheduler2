"""
Tests for the ORM models. Uses the shared `db_session` fixture provided by
the application's test harness - never a locally created engine - so these
tests run against the real deploy engine when DATABASE_URL is set, and
against a private SQLite file otherwise.
"""
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


def _make_location(db_session, name="Lab 1"):
    loc = Location(name=name, normalized_name=name.replace(" ", "").lower())
    db_session.add(loc)
    db_session.commit()
    return loc


def _make_vendor(db_session, name="Acme Corp"):
    v = Vendor(name=name, normalized_name=name.replace(" ", "").lower())
    db_session.add(v)
    db_session.commit()
    return v


def _make_type(db_session, name="Spectrometer"):
    t = Type(name=name, normalized_name=name.replace(" ", "").lower())
    db_session.add(t)
    db_session.commit()
    return t


def _make_purpose(db_session, name="Calibration"):
    p = ReservationPurpose(name=name, normalized_name=name.replace(" ", "").lower())
    db_session.add(p)
    db_session.commit()
    return p


def _make_instrument(db_session, location, vendor, type_, name="Instrument A"):
    inst = Instrument(
        name=name,
        nickname="nick",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=type_.type_id,
        status=InstrumentStatus.AVAILABLE,
        is_favorite=False,
        is_active=True,
    )
    db_session.add(inst)
    db_session.commit()
    return inst


def test_all_seven_tables_created_and_queryable_with_autoincrement_pks(db_session):
    location = _make_location(db_session, "Main Lab")
    vendor = _make_vendor(db_session, "Vendor One")
    type_ = _make_type(db_session, "Type One")
    purpose = _make_purpose(db_session, "Maintenance Check")
    instrument = _make_instrument(db_session, location, vendor, type_, "Inst One")

    start = datetime.now(timezone.utc)
    end = start + timedelta(hours=1)
    reservation = Reservation(
        instrument_id=instrument.instrument_id,
        start_datetime=start,
        end_datetime=end,
        reservation_purpose_id=purpose.reservation_purpose_id,
        requested_by="alice",
        can_be_overridden=False,
        is_active=True,
    )
    db_session.add(reservation)
    db_session.commit()

    audit = AuditLog(
        actor="alice",
        action_type=AuditActionType.CREATE,
        entity_type=AuditEntityType.RESERVATION,
        entity_id=reservation.reservation_id,
        description="Created reservation",
    )
    db_session.add(audit)
    db_session.commit()

    assert location.location_id is not None and location.location_id > 0
    assert vendor.vendor_id is not None and vendor.vendor_id > 0
    assert type_.type_id is not None and type_.type_id > 0
    assert purpose.reservation_purpose_id is not None and purpose.reservation_purpose_id > 0
    assert instrument.instrument_id is not None and instrument.instrument_id > 0
    assert reservation.reservation_id is not None and reservation.reservation_id > 0
    assert audit.audit_log_id is not None and audit.audit_log_id > 0

    fetched_reservation = (
        db_session.query(Reservation)
        .filter(Reservation.reservation_id == reservation.reservation_id)
        .one()
    )
    assert fetched_reservation.requested_by == "alice"

    fetched_audit = db_session.query(AuditLog).filter(AuditLog.audit_log_id == audit.audit_log_id).one()
    assert fetched_audit.description == "Created reservation"


def test_datetime_columns_store_and_retrieve_utc_aware_values(db_session):
    location = _make_location(db_session, "UTC Lab")
    vendor = _make_vendor(db_session, "UTC Vendor")
    type_ = _make_type(db_session, "UTC Type")
    purpose = _make_purpose(db_session, "UTC Purpose")
    instrument = _make_instrument(db_session, location, vendor, type_, "UTC Instrument")

    start = datetime(2024, 6, 1, 12, 30, 0, tzinfo=timezone.utc)
    end = start + timedelta(hours=2)

    reservation = Reservation(
        instrument_id=instrument.instrument_id,
        start_datetime=start,
        end_datetime=end,
        reservation_purpose_id=purpose.reservation_purpose_id,
        requested_by="bob",
        can_be_overridden=False,
        is_active=True,
    )
    db_session.add(reservation)
    db_session.commit()
    db_session.refresh(reservation)

    stored_start = reservation.start_datetime
    stored_end = reservation.end_datetime

    # Normalize before comparing: SQLite drops tzinfo (returns naive) while
    # Postgres returns an aware datetime. We do not assert on tzinfo
    # presence itself (that is engine-supplied behaviour) - we assert that
    # the wall-clock UTC value the application persisted is the value that
    # comes back, after normalizing any naive result to UTC ourselves.
    if stored_start.tzinfo is None:
        stored_start = stored_start.replace(tzinfo=timezone.utc)
    if stored_end.tzinfo is None:
        stored_end = stored_end.replace(tzinfo=timezone.utc)

    assert stored_start == start
    assert stored_end == end
    assert (stored_end - stored_start) == timedelta(hours=2)


def test_declared_column_lengths_from_metadata():
    # Assert constraints declared in metadata - true on every engine,
    # regardless of what the underlying database enforces at write time.
    assert Instrument.__table__.c.name.type.length == 120
    assert Instrument.__table__.c.nickname.type.length == 120
    assert Reservation.__table__.c.requested_by.type.length == 120
    assert AuditLog.__table__.c.actor.type.length == 120


def test_duplicate_normalized_master_data_name_violates_unique_constraint(db_session):
    _make_location(db_session, "Lab 1")
    db_session.expunge_all()

    duplicate = Location(name="lab1", normalized_name="lab1")
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_foreign_key_enforces_referential_integrity_instrument_to_location(db_session):
    bogus_instrument = Instrument(
        name="Orphan",
        nickname="orphan",
        location_id=999999,
        vendor_id=999999,
        type_id=999999,
        status=InstrumentStatus.AVAILABLE,
        is_favorite=False,
        is_active=True,
    )
    db_session.add(bogus_instrument)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_foreign_key_enforces_referential_integrity_reservation_to_instrument(db_session):
    location = _make_location(db_session, "FK Lab")
    vendor = _make_vendor(db_session, "FK Vendor")
    type_ = _make_type(db_session, "FK Type")
    purpose = _make_purpose(db_session, "FK Purpose")

    bogus_reservation = Reservation(
        instrument_id=999999,
        start_datetime=datetime.now(timezone.utc),
        end_datetime=datetime.now(timezone.utc) + timedelta(hours=1),
        reservation_purpose_id=purpose.reservation_purpose_id,
        requested_by="carol",
        can_be_overridden=False,
        is_active=True,
    )
    db_session.add(bogus_reservation)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_enum_column_accepts_only_declared_values_instrument_status(db_session):
    location = _make_location(db_session, "Enum Lab")
    vendor = _make_vendor(db_session, "Enum Vendor")
    type_ = _make_type(db_session, "Enum Type")

    good_instrument = Instrument(
        name="Good Instrument",
        nickname="good",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=type_.type_id,
        status=InstrumentStatus.MAINTENANCE,
        is_favorite=False,
        is_active=True,
    )
    db_session.add(good_instrument)
    db_session.commit()
    assert good_instrument.status == InstrumentStatus.MAINTENANCE

    bad_instrument = Instrument(
        name="Bad Instrument",
        nickname="bad",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=type_.type_id,
        status="NOT_A_REAL_STATUS",
        is_favorite=False,
        is_active=True,
    )
    db_session.add(bad_instrument)
    with pytest.raises((IntegrityError, LookupError, ValueError)):
        db_session.commit()
    db_session.rollback()


def test_enum_column_accepts_only_declared_values_audit_action_type(db_session):
    location = _make_location(db_session, "Audit Lab")
    vendor = _make_vendor(db_session, "Audit Vendor")
    type_ = _make_type(db_session, "Audit Type")
    instrument = _make_instrument(db_session, location, vendor, type_, "Audit Instrument")

    bad_audit = AuditLog(
        actor="dave",
        action_type="NOT_A_REAL_ACTION",
        entity_type=AuditEntityType.INSTRUMENT,
        entity_id=instrument.instrument_id,
        description="Should fail",
    )
    db_session.add(bad_audit)
    with pytest.raises((IntegrityError, LookupError, ValueError)):
        db_session.commit()
    db_session.rollback()


def test_enum_python_values_match_data_specification():
    assert {e.value for e in InstrumentStatus} == {
        "AVAILABLE",
        "IN_USE",
        "MAINTENANCE",
        "DECOMMISSIONED",
    }
    assert {e.value for e in AuditActionType} == {
        "CREATE",
        "UPDATE",
        "DELETE",
        "ACTIVATE",
        "DEACTIVATE",
        "OVERRIDE",
    }
    assert {e.value for e in AuditEntityType} == {
        "INSTRUMENT",
        "LOCATION",
        "VENDOR",
        "TYPE",
        "RESERVATION_PURPOSE",
        "RESERVATION",
    }
