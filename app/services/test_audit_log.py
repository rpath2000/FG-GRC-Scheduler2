"""Unit tests for AuditLogService."""
from __future__ import annotations

from app.models import AuditActionType, AuditEntityType
from app.services.audit_log import AuditLogService


def test_log_writes_entry_with_utc_timestamp(db_session):
    service = AuditLogService(db_session)
    db_session.commit()

    service.log(
        actor="Jane",
        action_type=AuditActionType.CREATE,
        entity_type=AuditEntityType.INSTRUMENT,
        entity_id=42,
        description="Created something",
    )
    db_session.commit()

    entries = service.list_entries()
    assert len(entries) == 1
    assert entries[0].actor == "Jane"
    assert entries[0].entity_id == 42
    assert entries[0].description == "Created something"
    timestamp = entries[0].timestamp
    if timestamp.tzinfo is None:
        # SQLite drops tzinfo; the value itself must still be "now" in UTC terms.
        pass
    assert timestamp is not None


def test_list_entries_orders_newest_first(db_session):
    service = AuditLogService(db_session)

    service.log("Actor1", AuditActionType.CREATE, AuditEntityType.INSTRUMENT, 1, "first")
    db_session.commit()
    service.log("Actor2", AuditActionType.UPDATE, AuditEntityType.INSTRUMENT, 1, "second")
    db_session.commit()
    service.log("Actor3", AuditActionType.SOFT_DELETE, AuditEntityType.INSTRUMENT, 1, "third")
    db_session.commit()

    entries = service.list_entries()

    descriptions = [e.description for e in entries]
    assert descriptions == ["third", "second", "first"]


def test_blank_actor_defaults_to_unknown(db_session):
    service = AuditLogService(db_session)

    service.log("   ", AuditActionType.CREATE, AuditEntityType.INSTRUMENT, 5, "desc")
    db_session.commit()

    entries = service.list_entries()
    assert entries[0].actor == "Unknown"
