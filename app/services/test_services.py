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


def _make_location(db, name="Main Lab"):
    loc = Location(name=name, is_active=True)
    db.add(loc)
    db.flush()
    return loc


def _make_vendor(db, name="Acme Corp"):
    vendor = Vendor(name=name, is_active=True)
    db.add(vendor)
    db.flush()
    return vendor


def _make_type(db, name="Spectrometer"):
    itype = InstrumentType(name=name, is_active=True)
    db.add(itype)
    db.flush()
    return itype


def _make_purpose(db, name="Calibration"):
    purpose = ReservationPurpose(name=name, is_active=True)
    db.add(purpose)
    db.flush()
    return purpose


def _make_instrument(db, location, vendor, itype, name="Instrument A", nickname="INA", status=InstrumentStatus.AVAILABLE):
    instrument = Instrument(
        name=name,
        nickname=nickname,
        location_id=location.location_id,
        vendor_id=vendor.vendor_id,
        type_id=itype.type_id,
        asset_id=None,
        color=None,
        status=status,
        is_active=True,
        is_favorite=False,
    )
    db.add(instrument)
    db.flush()
    return instrument


def _round_to_slot(dt: datetime) -> datetime:
    """Round a datetime down to the nearest 30-minute boundary with zeroed seconds."""
    minute = 0 if dt.minute < 30 else 30
    return dt.replace(minute=minute, second=0, microsecond=0)


class TestInstrumentService:
    def test_create_instrument_duplicate_normalized_name_raises(self, db_session):
        location = _make_location(db_session)
        vendor = _make_vendor(db_session)
        itype = _make_type(db_session)
        service = InstrumentService(db_session)

        service.create(
            InstrumentCreateDTO(
                name="  Gas Chromatograph  ",
                nickname="GC-1",
                location_id=location.location_id,
                vendor_id=vendor.vendor_id,
                type_id=itype.type_id,
                asset_id=None,
                color=None,
            )
        )
        db_session.flush()

        with pytest.raises(DuplicateError):
            service.create(
                InstrumentCreateDTO(
                    name="gas chromatograph",
                    nickname="gc-1",
                    location_id=location.location_id,
                    vendor_id=vendor.vendor_id,
                    type_id=itype.type_id,
                    asset_id=None,
                    color=None,
                )
            )

    def test_create_instrument_duplicate_detected_when_existing_inactive(self, db_session):
        location = _make_location(db_session)
        vendor = _make_vendor(db_session)
        itype = _make_type(db_session)
        service = InstrumentService(db_session)

        created = service.create(
            InstrumentCreateDTO(
                name="HPLC Unit",
                nickname="HPLC-1",
                location_id=location.location_id,
                vendor_id=vendor.vendor_id,
                type_id=itype.type_id,
                asset_id=None,
                color=None,
            )
        )
        service.soft_delete(created.instrument_id)
        db_session.flush()

        with pytest.raises(DuplicateError):
            service.create(
                InstrumentCreateDTO(
                    name="HPLC Unit",
                    nickname="HPLC-1",
                    location_id=location.location_id,
                    vendor_id=vendor.vendor_id,
                    type_id=itype.type_id,
                    asset_id=None,
                    color=None,
                )
            )

    def test_toggle_favorite_flips_flag(self, db_session):
        location = _make_location(db_session)
        vendor = _make_vendor(db_session)
        itype = _make_type(db_session)
        instrument = _make_instrument(db_session, location, vendor, itype)
        service = InstrumentService(db_session)

        result = service.toggle_favorite(instrument.instrument_id)
        assert result.is_favorite is True

        result2 = service.toggle_favorite(instrument.instrument_id)
        assert result2.is_favorite is False


class TestReservationService:
    def test_create_reservation_end_before_start_raises_validation_error(self, db_session):
        location = _make_location(db_session)
        vendor = _make_vendor(db_session)
        itype = _make_type(db_session)
        purpose = _make_purpose(db_session)
        instrument = _make_instrument(db_session, location, vendor, itype)
        service = ReservationService(db_session)

        start = _round_to_slot(datetime(2024, 6, 1, 10, 0))
        end = start - timedelta(minutes=30)

        with pytest.raises(ValidationError):
            service.create(
                ReservationCreateDTO(
                    instrument_id=instrument.instrument_id,
                    start_datetime=start,
                    end_datetime=end,
                    reservation_purpose_id=purpose.reservation_purpose_id,
                    requested_by="Alice",
                    can_be_overridden=False,
                )
            )

    def test_create_reservation_non_30_min_boundary_raises_validation_error(self, db_session):
        location = _make_location(db_session)
        vendor = _make_vendor(db_session)
        itype = _make_type(db_session)
        purpose = _make_purpose(db_session)
        instrument = _make_instrument(db_session, location, vendor, itype)
        service = ReservationService(db_session)

        start = datetime(2024, 6, 1, 10, 15)
        end = start + timedelta(minutes=30)

        with pytest.raises(ValidationError):
            service.create(
                ReservationCreateDTO(
                    instrument_id=instrument.instrument_id,
                    start_datetime=start,
                    end_datetime=end,
                    reservation_purpose_id=purpose.reservation_purpose_id,
                    requested_by="Alice",
                    can_be_overridden=False,
                )
            )

    def test_create_reservation_conflicts_with_non_overridable_raises_conflict_error(self, db_session):
        location = _make_location(db_session)
        vendor = _make_vendor(db_session)
        itype = _make_type(db_session)
        purpose = _make_purpose(db_session)
        instrument = _make_instrument(db_session, location, vendor, itype)
        service = ReservationService(db_session)

        base = _round_to_slot(datetime(2024, 6, 1, 9, 0))
        existing = service.create(
            ReservationCreateDTO(
                instrument_id=instrument.instrument_id,
                start_datetime=base,
                end_datetime=base + timedelta(hours=1),
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by="Bob",
                can_be_overridden=False,
            )
        )

        overlapping_start = base + timedelta(minutes=30)
        overlapping_end = overlapping_start + timedelta(hours=1)

        with pytest.raises(ConflictError) as exc_info:
            service.create(
                ReservationCreateDTO(
                    instrument_id=instrument.instrument_id,
                    start_datetime=overlapping_start,
                    end_datetime=overlapping_end,
                    reservation_purpose_id=purpose.reservation_purpose_id,
                    requested_by="Carol",
                    can_be_overridden=False,
                )
            )
        assert str(existing.reservation.reservation_id) in str(exc_info.value)

    def test_create_reservation_overrides_two_overridable_conflicts_and_audits_both(self, db_session):
        location = _make_location(db_session)
        vendor = _make_vendor(db_session)
        itype = _make_type(db_session)
        purpose = _make_purpose(db_session)
        instrument = _make_instrument(db_session, location, vendor, itype)
        service = ReservationService(db_session)
        audit_service = AuditService(db_session)

        base = _round_to_slot(datetime(2024, 6, 1, 8, 0))

        first = service.create(
            ReservationCreateDTO(
                instrument_id=instrument.instrument_id,
                start_datetime=base,
                end_datetime=base + timedelta(minutes=30),
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by="Dave",
                can_be_overridden=True,
            )
        )
        second = service.create(
            ReservationCreateDTO(
                instrument_id=instrument.instrument_id,
                start_datetime=base + timedelta(minutes=30),
                end_datetime=base + timedelta(minutes=60),
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by="Erin",
                can_be_overridden=True,
            )
        )

        overriding_start = base
        overriding_end = base + timedelta(minutes=60)

        result = service.create(
            ReservationCreateDTO(
                instrument_id=instrument.instrument_id,
                start_datetime=overriding_start,
                end_datetime=overriding_end,
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by="Frank",
                can_be_overridden=False,
            )
        )

        assert set(result.overridden_ids) == {
            first.reservation.reservation_id,
            second.reservation.reservation_id,
        }

        remaining = service.list_by_instrument_and_range(
            [instrument.instrument_id], base, base + timedelta(hours=2)
        )
        remaining_ids = {r.reservation_id for r in remaining}
        assert first.reservation.reservation_id not in remaining_ids
        assert second.reservation.reservation_id not in remaining_ids
        assert result.reservation.reservation_id in remaining_ids

        entries = audit_service.list_entries()
        override_entries = [e for e in entries if e.action_type == "OVERRIDE"]
        assert len(override_entries) == 1
        description = override_entries[0].description
        assert str(first.reservation.reservation_id) in description
        assert str(second.reservation.reservation_id) in description

    def test_list_by_instrument_and_range_filters_correctly(self, db_session):
        location = _make_location(db_session)
        vendor = _make_vendor(db_session)
        itype = _make_type(db_session)
        purpose = _make_purpose(db_session)
        instrument = _make_instrument(db_session, location, vendor, itype)
        service = ReservationService(db_session)

        base = _round_to_slot(datetime(2024, 7, 1, 12, 0))
        service.create(
            ReservationCreateDTO(
                instrument_id=instrument.instrument_id,
                start_datetime=base,
                end_datetime=base + timedelta(minutes=30),
                reservation_purpose_id=purpose.reservation_purpose_id,
                requested_by="Grace",
                can_be_overridden=False,
            )
        )

        in_range = service.list_by_instrument_and_range(
            [instrument.instrument_id], base - timedelta(hours=1), base + timedelta(hours=1)
        )
        out_of_range = service.list_by_instrument_and_range(
            [instrument.instrument_id],
            base + timedelta(hours=5),
            base + timedelta(hours=6),
        )

        assert len(in_range) == 1
        assert len(out_of_range) == 0


class TestMasterDataService:
    def test_deactivate_location_in_use_returns_usage_count_and_soft_deletes(self, db_session):
        service = MasterDataService(db_session)
        location = service.create_location("Building A")

        vendor = _make_vendor(db_session)
        itype = _make_type(db_session)

        for i in range(3):
            _make_instrument(
                db_session,
                type("L", (), {"location_id": location.location_id})(),
                vendor,
                itype,
                name=f"Instrument {i}",
                nickname=f"NICK-{i}",
            )

        usage_count = service.deactivate_location(location.location_id)

        assert usage_count == 3
        locations = service.list_locations(active_only=False)
        updated = next(l for l in locations if l.location_id == location.location_id)
        assert updated.is_active is False

        active_locations = service.list_locations(active_only=True)
        assert location.location_id not in {l.location_id for l in active_locations}

    def test_deactivate_location_not_in_use_returns_zero(self, db_session):
        service = MasterDataService(db_session)
        location = service.create_location("Empty Room")

        usage_count = service.deactivate_location(location.location_id)

        assert usage_count == 0

    def test_create_location_duplicate_name_raises(self, db_session):
        service = MasterDataService(db_session)
        service.create_location("Freezer Room")

        with pytest.raises(DuplicateError):
            service.create_location("  freezer room  ")

    def test_reactivate_location_restores_active_flag(self, db_session):
        service = MasterDataService(db_session)
        location = service.create_location("Cold Storage")
        service.deactivate_location(location.location_id)

        reactivated = service.reactivate_location(location.location_id)

        assert reactivated.is_active is True


class TestAuditService:
    def test_log_action_defaults_actor_to_unknown_when_blank(self, db_session):
        service = AuditService(db_session)

        service.log_action(
            actor="   ",
            action_type="CREATE",
            entity_type="INSTRUMENT",
            entity_id=1,
            description="Created instrument via blank actor.",
        )

        entries = service.list_entries()
        assert len(entries) == 1
        assert entries[0].actor == "Unknown"

    def test_list_entries_sorted_newest_first(self, db_session):
        service = AuditService(db_session)

        service.log_action("Alice", "CREATE", "INSTRUMENT", 1, "First action")
        service.log_action("Bob", "UPDATE", "INSTRUMENT", 1, "Second action")
        service.log_action("Carol", "DELETE", "INSTRUMENT", 1, "Third action")

        entries = service.list_entries()

        assert len(entries) == 3
        assert entries[0].description == "Third action"
        assert entries[1].description == "Second action"
        assert entries[2].description == "First action"
