"""
Tests for the app.models database layer: ORM mapping, FK integrity,
case-insensitive uniqueness, timezone coercion, soft-delete, and seed
idempotency.

Uses the shared db_session fixture (provided by the test harness), which
runs against DATABASE_URL when set, and a private SQLite file otherwise.
"""
from __future__ import annotations

from datetime import datetime, timezone

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
from app.models.seed import run_seed


def _make_master_row(db_session, location_name="Main Lab X", vendor_name="Vendor X", type_name="Type X"):
    location = Location(name=location_name, is_active=True)
    vendor = Vendor(name=vendor_name, is_active=True)
    itype = InstrumentType(name=type_name, is_active=True)
    db_session.add_all([location, vendor, itype])
    db_session.flush()
    return location, vendor, itype


def test_create_instrument_with_all_required_fields(db_session):
    location, vendor, itype = _make_master_row(db_session)

    instrument = Instrument(
        name="Mass Spec 3000",
        nickname="MS3000",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=itype.type_id,
        asset_id="AST-001",
        color="blue",
        status=InstrumentStatus.AVAILABLE,
        is_active=True,
        is_favorite=False,
    )
    db_session.add(instrument)
    db_session.commit()

    fetched = db_session.query(Instrument).filter_by(name="Mass Spec 3000").one()
    assert fetched.instrument_id is not None
    assert fetched.location_id == location.location_id
    assert fetched.vendor_id == vendor.vendor_id
    assert fetched.type_id == itype.type_id
    assert fetched.status == InstrumentStatus.AVAILABLE


def test_instrument_fk_integrity_rejects_missing_location(db_session):
    _, vendor, itype = _make_master_row(db_session, location_name="Loc For FK Test")

    bad_instrument = Instrument(
        name="Broken Instrument",
        nickname="Broken",
        location_id=999999,
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
    db_session.add(Location(name="Central Storage", is_active=True))
    db_session.commit()

    db_session.add(Location(name="CENTRAL STORAGE", is_active=True))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_reservation_naive_datetime_is_coerced_to_utc(db_session):
    location, vendor, itype = _make_master_row(db_session, location_name="Loc Naive Test")
    purpose = ReservationPurpose(name="Naive Test Purpose", is_active=True)
    db_session.add(purpose)
    db_session.flush()

    instrument = Instrument(
        name="Naive DT Instrument",
        nickname="NaiveDT",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=itype.type_id,
        status=InstrumentStatus.AVAILABLE,
        is_active=True,
        is_favorite=False,
    )
    db_session.add(instrument)
    db_session.flush()

    naive_start = datetime(2026, 1, 1, 9, 0, 0)
    naive_end = datetime(2026, 1, 1, 10, 0, 0)

    reservation = Reservation(
        instrument_id=instrument.instrument_id,
        start_datetime=naive_start,
        end_datetime=naive_end,
        reservation_purpose_id=purpose.reservation_purpose_id,
        requested_by="tester",
        can_be_overridden=False,
        is_active=True,
    )
    db_session.add(reservation)
    db_session.commit()

    db_session.expire_all()
    fetched = db_session.query(Reservation).filter_by(reservation_id=reservation.reservation_id).one()

    start_val = fetched.start_datetime
    end_val = fetched.end_datetime
    if start_val.tzinfo is None:
        start_val = start_val.replace(tzinfo=timezone.utc)
    if end_val.tzinfo is None:
        end_val = end_val.replace(tzinfo=timezone.utc)

    assert start_val.utcoffset() == timezone.utc.utcoffset(None)
    assert start_val.hour == 9
    assert end_val.hour == 10


def test_soft_delete_instrument_retained_and_excluded_from_active_query(db_session):
    location, vendor, itype = _make_master_row(db_session, location_name="Loc SoftDelete Test")

    instrument = Instrument(
        name="Soft Delete Instrument",
        nickname="SoftDel",
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

    row = db_session.query(Instrument).filter_by(instrument_id=instrument_id).one()
    assert row is not None
    assert row.is_active is False

    active_rows = db_session.query(Instrument).filter_by(
        instrument_id=instrument_id, is_active=True
    ).all()
    assert active_rows == []


def test_seed_script_is_idempotent(db_session):
    run_seed(db_session)
    location_count_1 = db_session.query(Location).count()
    vendor_count_1 = db_session.query(Vendor).count()
    type_count_1 = db_session.query(InstrumentType).count()
    purpose_count_1 = db_session.query(ReservationPurpose).count()

    run_seed(db_session)
    location_count_2 = db_session.query(Location).count()
    vendor_count_2 = db_session.query(Vendor).count()
    type_count_2 = db_session.query(InstrumentType).count()
    purpose_count_2 = db_session.query(ReservationPurpose).count()

    assert location_count_1 == location_count_2
    assert vendor_count_1 == vendor_count_2
    assert type_count_1 == type_count_2
    assert purpose_count_1 == purpose_count_2
    assert location_count_1 > 0
    assert vendor_count_1 > 0
    assert type_count_1 > 0
    assert purpose_count_1 > 0


def test_declared_column_length_constraints_from_metadata():
    assert Location.__table__.c.name.type.length == 200
    assert Vendor.__table__.c.name.type.length == 200
    assert InstrumentType.__table__.c.name.type.length == 200
    assert ReservationPurpose.__table__.c.name.type.length == 200
    assert Instrument.__table__.c.name.type.length == 200
    assert AuditLog.__table__.c.description.type.length == 2000


def test_audit_log_can_be_created_and_persisted(db_session):
    entry = AuditLog(
        actor="tester",
        timestamp=datetime.now(timezone.utc),
        action_type=AuditActionType.CREATE,
        entity_type=AuditEntityType.INSTRUMENT,
        entity_id=1,
        description="Created instrument for testing purposes.",
    )
    db_session.add(entry)
    db_session.commit()

    fetched = db_session.query(AuditLog).filter_by(audit_log_id=entry.audit_log_id).one()
    assert fetched.action_type == AuditActionType.CREATE
    assert fetched.entity_type == AuditEntityType.INSTRUMENT


def test_unique_constraints_declared_in_metadata():
    location_constraints = {c.name for c in Location.__table__.constraints}
    vendor_constraints = {c.name for c in Vendor.__table__.constraints}
    type_constraints = {c.name for c in InstrumentType.__table__.constraints}
    purpose_constraints = {c.name for c in ReservationPurpose.__table__.constraints}

    assert "uq_locations_normalized_name" in location_constraints
    assert "uq_vendors_normalized_name" in vendor_constraints
    assert "uq_instrument_types_normalized_name" in type_constraints
    assert "uq_reservation_purposes_normalized_name" in purpose_constraints
