"""Unit tests for the seed data loader."""
from __future__ import annotations

from app.models import Location, ReservationPurpose, Type, Vendor
from app.services.seed import load_seed_data


def test_seed_inserts_expected_locations(db_session):
    load_seed_data(db_session)

    names = {loc.name for loc in db_session.query(Location).all()}
    assert {"Lab 224", "Lab 226", "Lab L128A", "Lab L128B"}.issubset(names)
    for loc in db_session.query(Location).all():
        assert loc.is_active is True


def test_seed_inserts_expected_vendors_types_purposes(db_session):
    load_seed_data(db_session)

    vendor_names = {v.name for v in db_session.query(Vendor).all()}
    type_names = {t.name for t in db_session.query(Type).all()}
    purpose_names = {p.name for p in db_session.query(ReservationPurpose).all()}

    assert {
        "Beckman Coulter",
        "Covaris",
        "Eppendorf",
        "AutoGen",
        "Promega",
        "Illumina",
        "QIAGEN",
    }.issubset(vendor_names)
    assert {"Liquid Handler", "Sonicator", "Extraction", "Sequencer"}.issubset(type_names)
    assert {
        "Method development",
        "Sample analysis",
        "Maintenance",
        "Validation",
        "Training",
    }.issubset(purpose_names)


def test_seed_is_idempotent(db_session):
    load_seed_data(db_session)
    load_seed_data(db_session)
    load_seed_data(db_session)

    location_count = db_session.query(Location).filter(Location.name == "Lab 224").count()
    vendor_count = db_session.query(Vendor).filter(Vendor.name == "Illumina").count()

    assert location_count == 1
    assert vendor_count == 1
