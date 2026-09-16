"""Unit tests for InstrumentService, ReservationService, MasterDataService, AuditService."""

from datetime import datetime, timedelta

import pytest

from app.contracts import (
    ConflictError,
    DuplicateError,
    InstrumentCreateDTO,
    ReservationCreateDTO,
    ValidationError,
)
from app.models import Instrument, InstrumentStatus, Location, Vendor, InstrumentType, ReservationPurpose
from app.services import AuditService, InstrumentService, MasterDataService, ReservationService


def _make_master_data(db_session):
    location = Location(name="Lab A", is_active=True)
    vendor = Vendor(name="Acme Corp", is_active=True)
    itype = InstrumentType(name="Spectrometer", is_active=True)
    purpose = ReservationPurpose(name="Maintenance", is_active=True)
    db_session.add_all([location, vendor, itype, purpose])
    db_session.commit()
    return location, vendor, itype, purpose


def test_create_instrument_duplicate_normalized_name_raises_duplicate_error(db_session):
    location, vendor, itype, _ = _make_master_data(db_session)
    service = InstrumentService(db_session)

    data = InstrumentCreateDTO(
        name="Mass Spec 3000",
        nickname="MS3K",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=itype.type_id,
        asset_id=None,
        color=None,
    )
    service.create(data)

    duplicate = InstrumentCreateDTO(
        name="  mass spec  3000 ",
        nickname=" ms3k ",
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=itype.type_id,
        asset_id=None,
        color=None,
    )
    with pytest.raises(DuplicateError):
        service.create(duplicate)


def test_create_reservation_end_before_start_raises_validation_error(db_session):
    location, vendor, itype, purpose = _make_master_data(db_session)
    instrument_service = InstrumentService(db_session)
    instrument_dto = instrument_service.create(
        InstrumentCreateDTO(
            name="HPLC Unit",
            nickname="HPLC1",
            location_id=location.location_id,
            vendor_id=vendor.vendor_id,
            type_id=itype.type_id,
            asset_id=None,
            color=None,
        )
    )

    reservation_service = ReservationService(db_session)
    start = datetime(2030, 1, 1, 9, 0)
    end = start - timedelta(minutes=30)

    with pytest.raises(ValidationError):
        reservation_service.create(
            ReservationCreateDTO(
                instrument_id=instrument_dto.instrument_id,
                start_datetime=start,
                end_datetime=end,
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by="Alice",
                can_be_overridden=False,
            )
        )


def test_create_reservation_non_30_min_boundary_raises_validation_error(db_session):
    location, vendor, itype, purpose = _make_master_data(db_session)
    instrument_service = InstrumentService(db_session)
    instrument_dto = instrument_service.create(
        InstrumentCreateDTO(
            name="Centrifuge",
            nickname="CNT1",
            location_id=location.location_id,
            vendor_id=vendor.vendor_id,
            type_id=itype.type_id,
            asset_id=None,
            color=None,
        )
    )
    reservation_service = ReservationService(db_session)
    start = datetime(2030, 1, 1, 9, 5)
    end = start + timedelta(minutes=30)

    with pytest.raises(ValidationError):
        reservation_service.create(
            ReservationCreateDTO(
                instrument_id=instrument_dto.instrument_id,
                start_datetime=start,
                end_datetime=end,
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by="Bob",
                can_be_overridden=False,
            )
        )


def test_create_reservation_overlapping_non_overridable_raises_conflict_error(db_session):
    location, vendor, itype, purpose = _make_master_data(db_session)
    instrument_service = InstrumentService(db_session)
    instrument_dto = instrument_service.create(
        InstrumentCreateDTO(
            name="NMR Spectrometer",
            nickname="NMR1",
            location_id=location.location_id,
            vendor_id=vendor.vendor_id,
            type_id=itype.type_id,
            asset_id=None,
            color=None,
        )
    )
    reservation_service = ReservationService(db_session)
    start = datetime(2030, 2, 1, 9, 0)
    end = start + timedelta(hours=1)

    existing_result = reservation_service.create(
        ReservationCreateDTO(
            instrument_id=instrument_dto.instrument_id,
            start_datetime=start,
            end_datetime=end,
            reservation_purpose_id=purpose.reservation_purpose_id,
            requested_by="Carol",
            can_be_overridden=False,
        )
    )
    assert existing_result.reservation.can_be_overridden is False

    overlap_start = start + timedelta(minutes=30)
    overlap_end = overlap_start + timedelta(hours=1)

    with pytest.raises(ConflictError) as exc_info:
        reservation_service.create(
            ReservationCreateDTO(
                instrument_id=instrument_dto.instrument_id,
                start_datetime=overlap_start,
                end_datetime=overlap_end,
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by="Dave",
                can_be_overridden=False,
            )
        )
    assert "Maintenance" in str(exc_info.value)


def test_create_reservation_overlapping_two_overridable_soft_deletes_and_audits(db_session):
    location, vendor, itype, purpose = _make_master_data(db_session)
    instrument_service = InstrumentService(db_session)
    instrument_dto = instrument_service.create(
        InstrumentCreateDTO(
            name="Flow Cytometer",
            nickname="FCM1",
            location_id=location.location_id,
            vendor_id=vendor.vendor_id,
            type_id=itype.type_id,
            asset_id=None,
            color=None,
        )
    )
    reservation_service = ReservationService(db_session)
    base_start = datetime(2030, 3, 1, 9, 0)

    result_1 = reservation_service.create(
        ReservationCreateDTO(
            instrument_id=instrument_dto.instrument_id,
            start_datetime=base_start,
            end_datetime=base_start + timedelta(minutes=30),
            reservation_purpose_id=purpose.reservation_purpose_id,
            requested_by="Erin",
            can_be_overridden=True,
        )
    )
    result_2 = reservation_service.create(
        ReservationCreateDTO(
            instrument_id=instrument_dto.instrument_id,
            start_datetime=base_start + timedelta(minutes=30),
            end_datetime=base_start + timedelta(hours=1),
            reservation_purpose_id=purpose.reservation_purpose_id,
            requested_by="Frank",
            can_be_overridden=True,
        )
    )

    overriding_result = reservation_service.create(
        ReservationCreateDTO(
            instrument_id=instrument_dto.instrument_id,
            start_datetime=base_start,
            end_datetime=base_start + timedelta(hours=1),
            reservation_purpose_id=purpose.reservation_purpose_id,
            requested_by="Grace",
            can_be_overridden=False,
        )
    )

    assert sorted(overriding_result.overridden_ids) == sorted(
        [result_1.reservation.reservation_id, result_2.reservation.reservation_id]
    )

    remaining = reservation_service.list_by_instrument_and_range(
        [instrument_dto.instrument_id], base_start - timedelta(days=1), base_start + timedelta(days=1)
    )
    remaining_ids = {r.reservation_id for r in remaining}
    assert result_1.reservation.reservation_id not in remaining_ids
    assert result_2.reservation.reservation_id not in remaining_ids
    assert overriding_result.reservation.reservation_id in remaining_ids

    audit_service = AuditService(db_session)
    entries = audit_service.list_entries()
    override_entries = [e for e in entries if e.action_type == "OVERRIDE"]
    assert len(override_entries) == 1
    description = override_entries[0].description
    assert str(result_1.reservation.reservation_id) in description
    assert str(result_2.reservation.reservation_id) in description


def test_deactivate_location_in_use_by_three_instruments_returns_count_and_soft_deletes(db_session):
    location, vendor, itype, _ = _make_master_data(db_session)
    instrument_service = InstrumentService(db_session)

    for i in range(3):
        instrument_service.create(
            InstrumentCreateDTO(
                name=f"Instrument {i}",
                nickname=f"INST{i}",
                location_id=location.location_id,
                vendor_id=vendor.vendor_id,
                type_id=itype.type_id,
                asset_id=None,
                color=None,
            )
        )

    master_data_service = MasterDataService(db_session)
    usage_count = master_data_service.deactivate_location(location.location_id)

    assert usage_count == 3

    locations = master_data_service.list_locations(active_only=False)
    updated = next(loc for loc in locations if loc.location_id == location.location_id)
    assert updated.is_active is False

    active_locations = master_data_service.list_locations(active_only=True)
    assert all(loc.location_id != location.location_id for loc in active_locations)


def test_audit_service_log_action_defaults_actor_to_unknown_when_blank(db_session):
    audit_service = AuditService(db_session)
    audit_service.log_action(
        actor="   ",
        action_type="CREATE",
        entity_type="LOCATION",
        entity_id=1,
        description="Test entry with blank actor",
    )
    entries = audit_service.list_entries()
    assert entries[0].actor == "Unknown"


def test_audit_service_list_entries_sorted_newest_first(db_session):
    audit_service = AuditService(db_session)
    audit_service.log_action("Alice", "CREATE", "LOCATION", 1, "first entry")
    audit_service.log_action("Bob", "UPDATE", "LOCATION", 1, "second entry")
    audit_service.log_action("Carol", "DELETE", "LOCATION", 1, "third entry")

    entries = audit_service.list_entries()
    descriptions = [e.description for e in entries]
    assert descriptions == ["third entry", "second entry", "first entry"]
