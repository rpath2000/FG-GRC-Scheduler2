"""
Tests for app.models: ORM mapping, constraints, timezone handling,
soft-delete, and seed idempotency.

Uses the shared `db_session` fixture (provided by the test harness) which
supplies a session against DATABASE_URL when set, or a private SQLite file
otherwise, with schema created and PRAGMA foreign_keys=ON already applied.
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
    InstrumentType,
    Location,
    Reservation,
    ReservationPurpose,
    Vendor,
)
from app.models.seed import seed_master_data


def _make_master_data(db_session):
    location = Location(name="Main Lab", is_active=True)
    vendor = Vendor(name="Acme Instruments", is_active=True)
    itype = InstrumentType(name="Multimeter", is_active=True)
    db_session.add_all([location, vendor, itype])
    db_session.commit()
    return location, vendor, itype


def test_create_instrument_with_all_required_fields(db_session):
    location, vendor, itype = _make_master_data(db_session)

    instrument = Instrument(
        name="Fluke 87V",
        nickname="Fluke Yellow",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=itype.type_id,
        asset_id="AST-001",
        color="Yellow",
        status=InstrumentStatus.AVAILABLE,
        is_active=True,
        is_favorite=False,
    )
    db_session.add(instrument)
    db_session.commit()

    fetched = db_session.query(Instrument).filter_by(name="Fluke 87V").one()
    assert fetched.instrument_id is not None
    assert fetched.location_id == location.location_id
    assert fetched.vendor_id == vendor.vendor_id
    assert fetched.type_id == itype.type_id
    assert fetched.status == InstrumentStatus.AVAILABLE


def test_instrument_fk_integrity_rejects_missing_location(db_session):
    _, vendor, itype = _make_master_data(db_session)

    bad_instrument = Instrument(
        name="Broken FK Instrument",
        nickname="Broken",
        location_id=999999,  # does not exist
        vendor_id=vendor.vendor_id,
        type_id=itype.type_id,
        status=InstrumentStatus.AVAILABLE,
        is_active=True,
        is_favorite=False,
    )
    db_session.add(bad_instrument)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_duplicate_location_name_case_insensitive_raises_integrity_error(db_session):
    db_session.add(Location(name="Main Lab", is_active=True))
    db_session.commit()

    db_session.add(Location(name="MAIN LAB", is_active=True))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_reservation_naive_datetime_is_coerced_to_utc(db_session):
    location, vendor, itype = _make_master_data(db_session)
    purpose = ReservationPurpose(name="Calibration", is_active=True)
    db_session.add(purpose)
    db_session.commit()

    instrument = Instrument(
        name="Scope 1",
        nickname="Scope",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=itype.type_id,
        status=InstrumentStatus.AVAILABLE,
        is_active=True,
        is_favorite=False,
    )
    db_session.add(instrument)
    db_session.commit()

    naive_start = datetime(2026, 1, 1, 9, 0, 0)  # no tzinfo
    naive_end = datetime(2026, 1, 1, 10, 0, 0)

    reservation = Reservation(
        instrument_id=instrument.instrument_id,
        start_datetime=naive_start,
        end_datetime=naive_end,
        reservation_purpose_id=purpose.reservation_purpose_id,
        requested_by="jdoe",
        can_be_overridden=False,
        is_active=True,
    )
    db_session.add(reservation)
    db_session.commit()

    fetched = db_session.query(Reservation).filter_by(
        reservation_id=reservation.reservation_id
    ).one()

    # The application's own type decorator must have coerced these to UTC
    # rather than leaving them ambiguous / naive.
    assert fetched.start_datetime.tzinfo is not None
    assert fetched.start_datetime.utcoffset() == timedelta(0)
    assert fetched.end_datetime.tzinfo is not None
    assert fetched.end_datetime.utcoffset() == timedelta(0)


def test_soft_delete_instrument_retains_row_but_excludes_from_active_query(db_session):
    location, vendor, itype = _make_master_data(db_session)

    instrument = Instrument(
        name="Caliper A",
        nickname="Caliper",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=itype.type_id,
        status=InstrumentStatus.AVAILABLE,
        is_active=True,
        is_favorite=False,
    )
    db_session.add(instrument)
    db_session.commit()
    instrument_id = instrument.instrument_id

    instrument.is_active = False
    db_session.commit()

    # Row is retained in the table.
    still_present = db_session.query(Instrument).filter_by(instrument_id=instrument_id).one()
    assert still_present is not None
    assert still_present.is_active is False

    # Excluded from an "active" query.
    active_instruments = db_session.query(Instrument).filter_by(is_active=True).all()
    assert instrument_id not in [i.instrument_id for i in active_instruments]


def test_seed_script_is_idempotent_when_run_twice(db_session):
    seed_master_data(db_session)
    first_location_count = db_session.query(Location).count()
    first_vendor_count = db_session.query(Vendor).count()
    first_type_count = db_session.query(InstrumentType).count()
    first_purpose_count = db_session.query(ReservationPurpose).count()

    assert first_location_count > 0
    assert first_vendor_count > 0
    assert first_type_count > 0
    assert first_purpose_count > 0

    # Run again: because the tables are no longer empty, seeding must be a no-op.
    seed_master_data(db_session)

    assert db_session.query(Location).count() == first_location_count
    assert db_session.query(Vendor).count() == first_vendor_count
    assert db_session.query(InstrumentType).count() == first_type_count
    assert db_session.query(ReservationPurpose).count() == first_purpose_count


def test_declared_column_lengths_from_metadata():
    # Constraints checked against the METADATA (true on every engine),
    # not against what a specific database engine rejects.
    assert Instrument.__table__.c.name.type.length == 200
    assert Instrument.__table__.c.nickname.type.length == 200
    assert Location.__table__.c.name.type.length == 200
    assert Vendor.__table__.c.name.type.length == 200
    assert InstrumentType.__table__.c.name.type.length == 200
    assert ReservationPurpose.__table__.c.name.type.length == 200
    assert AuditLog.__table__.c.description.type.length == 1000


def test_audit_log_creation_with_timezone_aware_timestamp(db_session):
    now_utc = datetime.now(timezone.utc)
    entry = AuditLog(
        actor="jdoe",
        timestamp=now_utc,
        action_type=AuditActionType.CREATE,
        entity_type=AuditEntityType.INSTRUMENT,
        entity_id=1,
        description="Created instrument",
    )
    db_session.add(entry)
    db_session.commit()

    fetched = db_session.query(AuditLog).filter_by(audit_log_id=entry.audit_log_id).one()
    assert fetched.action_type == AuditActionType.CREATE
    assert fetched.entity_type == AuditEntityType.INSTRUMENT
    # Normalize before comparing tz-awareness-dependent behaviour, since
    # SQLite drops tzinfo on round-trip while Postgres preserves it.
    ts = fetched.timestamp
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    assert ts.utcoffset() == timedelta(0)
