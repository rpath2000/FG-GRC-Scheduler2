"""Unit tests for MasterDataService."""
from __future__ import annotations

import pytest

from app.contracts import DuplicateMasterDataError
from app.models import Instrument, InstrumentStatus, Location, Type, Vendor
from app.services.master_data import MasterDataService


def test_duplicate_detection_case_insensitive_normalized(db_session):
    service = MasterDataService(db_session)
    service.create_location("Lab 1")

    with pytest.raises(DuplicateMasterDataError):
        service.create_location("lab1")


def test_duplicate_detection_with_internal_whitespace(db_session):
    service = MasterDataService(db_session)
    service.create_location("Lab  One")

    with pytest.raises(DuplicateMasterDataError):
        service.create_location("  lab one  ")


def test_deactivate_location_returns_usage_count(db_session):
    service = MasterDataService(db_session)
    location = service.create_location("Lab 3")
    vendor = Vendor(name="Vendor X", is_active=True)
    type_ = Type(name="Type X", is_active=True)
    db_session.add_all([vendor, type_])
    db_session.commit()

    for i in range(5):
        db_session.add(
            Instrument(
                name=f"Inst {i}",
                nickname=f"N{i}",
                location_id=location.location_id,
                vendor_id=vendor.vendor_id,
                type_id=type_.type_id,
                asset_id=f"A{i}",
                color=None,
                status=InstrumentStatus.ACTIVE,
                is_favorite=False,
                is_active=True,
            )
        )
    # An extra inactive instrument that should NOT be counted.
    db_session.add(
        Instrument(
            name="Inactive Inst",
            nickname="NX",
            location_id=location.location_id,
            vendor_id=vendor.vendor_id,
            type_id=type_.type_id,
            asset_id="AX",
            color=None,
            status=InstrumentStatus.ACTIVE,
            is_favorite=False,
            is_active=False,
        )
    )
    db_session.commit()

    result = service.deactivate_location(location.location_id)

    assert result.usage_count == 5
    updated_location = (
        db_session.query(Location).filter(Location.location_id == location.location_id).one()
    )
    assert updated_location.is_active is False


def test_update_location_persists_new_name(db_session):
    service = MasterDataService(db_session)
    location = service.create_location("Old Name")

    updated = service.update_location(location.location_id, "New Name")

    assert updated.name == "New Name"
    persisted = (
        db_session.query(Location).filter(Location.location_id == location.location_id).one()
    )
    assert persisted.name == "New Name"


def test_update_to_conflicting_name_raises(db_session):
    service = MasterDataService(db_session)
    service.create_location("Lab A")
    lab_b = service.create_location("Lab B")

    with pytest.raises(DuplicateMasterDataError):
        service.update_location(lab_b.location_id, "lab a")


def test_list_locations_includes_inactive_when_requested(db_session):
    service = MasterDataService(db_session)
    active = service.create_location("Active Lab")
    inactive = service.create_location("Inactive Lab")
    service.deactivate_location(inactive.location_id)

    active_only = service.list_locations(include_inactive=False)
    all_locations = service.list_locations(include_inactive=True)

    assert {loc.name for loc in active_only} == {"Active Lab"}
    assert {loc.name for loc in all_locations} == {"Active Lab", "Inactive Lab"}
