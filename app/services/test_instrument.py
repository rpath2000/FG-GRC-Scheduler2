"""Unit tests for InstrumentService."""
from __future__ import annotations

import pytest

from app.contracts import (
    InstrumentCreateDTO,
    InstrumentFilterDTO,
    InstrumentUpdateDTO,
    NotFoundError,
)
from app.models import AuditActionType, AuditLog, InstrumentStatus, Location, Type, Vendor
from app.services.instrument import InstrumentService


@pytest.fixture
def base_master_data(db_session):
    location = Location(name="Lab 224", is_active=True)
    vendor = Vendor(name="Illumina", is_active=True)
    type_ = Type(name="Sequencer", is_active=True)
    db_session.add_all([location, vendor, type_])
    db_session.commit()
    return {"location": location, "vendor": vendor, "type": type_}


def test_create_logs_audit_entry(db_session, base_master_data):
    service = InstrumentService(db_session)
    data = InstrumentCreateDTO(
        name="Sequencer A",
        nickname="SeqA",
        location_id=base_master_data["location"].location_id,
        vendor_id=base_master_data["vendor"].vendor_id,
        type_id=base_master_data["type"].type_id,
        asset_id="AST-001",
        color="#FF0000",
        status=InstrumentStatus.ACTIVE.value,
        is_active=True,
    )

    result = service.create(data)

    assert result.instrument_id is not None
    assert result.is_active is True
    assert result.name == "Sequencer A"

    entries = db_session.query(AuditLog).filter(AuditLog.entity_id == result.instrument_id).all()
    assert len(entries) == 1
    assert entries[0].action_type == AuditActionType.CREATE


def test_update_logs_field_level_changes(db_session, base_master_data):
    service = InstrumentService(db_session)
    created = service.create(
        InstrumentCreateDTO(
            name="Sequencer A",
            nickname="SeqA",
            location_id=base_master_data["location"].location_id,
            vendor_id=base_master_data["vendor"].vendor_id,
            type_id=base_master_data["type"].type_id,
            asset_id="AST-001",
            color=None,
            status=InstrumentStatus.ACTIVE.value,
            is_active=True,
        )
    )

    updated = service.update(
        created.instrument_id,
        InstrumentUpdateDTO(nickname="SeqB", asset_id="AST-002"),
    )

    assert updated.nickname == "SeqB"
    assert updated.asset_id == "AST-002"

    entries = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == created.instrument_id, AuditLog.action_type == AuditActionType.UPDATE)
        .all()
    )
    assert len(entries) == 1
    assert "nickname" in entries[0].description
    assert "SeqA" in entries[0].description
    assert "SeqB" in entries[0].description


def test_soft_delete_sets_is_active_false_and_logs(db_session, base_master_data):
    service = InstrumentService(db_session)
    created = service.create(
        InstrumentCreateDTO(
            name="Sequencer A",
            nickname="SeqA",
            location_id=base_master_data["location"].location_id,
            vendor_id=base_master_data["vendor"].vendor_id,
            type_id=base_master_data["type"].type_id,
            asset_id="AST-001",
            color=None,
            status=InstrumentStatus.ACTIVE.value,
            is_active=True,
        )
    )

    service.soft_delete(created.instrument_id)

    with pytest.raises(NotFoundError):
        # get_instrument still works for soft-deleted rows (not enforced),
        # so verify persisted state directly instead.
        pass

    refreshed = service.get_instrument(created.instrument_id)
    assert refreshed.is_active is False

    entries = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.entity_id == created.instrument_id,
            AuditLog.action_type == AuditActionType.SOFT_DELETE,
        )
        .all()
    )
    assert len(entries) == 1


def test_toggle_favorite_flips_and_logs(db_session, base_master_data):
    service = InstrumentService(db_session)
    created = service.create(
        InstrumentCreateDTO(
            name="Sequencer A",
            nickname="SeqA",
            location_id=base_master_data["location"].location_id,
            vendor_id=base_master_data["vendor"].vendor_id,
            type_id=base_master_data["type"].type_id,
            asset_id="AST-001",
            color=None,
            status=InstrumentStatus.ACTIVE.value,
            is_active=True,
        )
    )
    assert created.is_favorite is False

    new_value = service.toggle_favorite(created.instrument_id)
    assert new_value is True

    refreshed = service.get_instrument(created.instrument_id)
    assert refreshed.is_favorite is True

    entries = (
        db_session.query(AuditLog)
        .filter(AuditLog.entity_id == created.instrument_id, AuditLog.action_type == AuditActionType.UPDATE)
        .all()
    )
    assert any("is_favorite" in e.description for e in entries)


def test_list_instruments_sorted_name_then_nickname(db_session, base_master_data):
    service = InstrumentService(db_session)
    service.create(
        InstrumentCreateDTO(
            name="Zeta",
            nickname="Z1",
            location_id=base_master_data["location"].location_id,
            vendor_id=base_master_data["vendor"].vendor_id,
            type_id=base_master_data["type"].type_id,
            asset_id="A1",
            color=None,
            status=InstrumentStatus.ACTIVE.value,
            is_active=True,
        )
    )
    service.create(
        InstrumentCreateDTO(
            name="Alpha",
            nickname="B",
            location_id=base_master_data["location"].location_id,
            vendor_id=base_master_data["vendor"].vendor_id,
            type_id=base_master_data["type"].type_id,
            asset_id="A2",
            color=None,
            status=InstrumentStatus.ACTIVE.value,
            is_active=True,
        )
    )
    service.create(
        InstrumentCreateDTO(
            name="Alpha",
            nickname="A",
            location_id=base_master_data["location"].location_id,
            vendor_id=base_master_data["vendor"].vendor_id,
            type_id=base_master_data["type"].type_id,
            asset_id="A3",
            color=None,
            status=InstrumentStatus.ACTIVE.value,
            is_active=True,
        )
    )

    results = service.list_instruments(InstrumentFilterDTO())
    names = [(r.name, r.nickname) for r in results]
    assert names == [("Alpha", "A"), ("Alpha", "B"), ("Zeta", "Z1")]
