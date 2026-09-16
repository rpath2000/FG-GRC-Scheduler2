"""Append-only audit log service.

Every mutation across the application is recorded here with actor,
UTC timestamp, action type, entity type/id, and a human-readable
description. Entries are never updated or deleted.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.contracts import AuditLogDTO
from app.models import AuditActionType, AuditEntityType, AuditLog


class AuditLogService:
    """Service for writing and reading append-only audit log entries."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def log(
        self,
        actor: str,
        action_type: AuditActionType,
        entity_type: AuditEntityType,
        entity_id: int,
        description: str,
    ) -> None:
        """Create a single audit log entry with a UTC timestamp.

        Callers are responsible for committing (or letting the enclosing
        service commit) the surrounding transaction. This method flushes
        so entity_id ordering and audit_log_id assignment are visible
        within the same transaction.
        """
        actor_value = (actor or "").strip() or "Unknown"
        entry = AuditLog(
            actor=actor_value,
            timestamp=datetime.now(timezone.utc),
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
        )
        self._db.add(entry)
        self._db.flush()

    def list_entries(self) -> list[AuditLogDTO]:
        """Return all audit entries, newest first."""
        entries = self._db.query(AuditLog).order_by(AuditLog.timestamp.desc()).all()
        results = []
        for entry in entries:
            action = entry.action_type.value if hasattr(entry.action_type, "value") else entry.action_type
            entity = entry.entity_type.value if hasattr(entry.entity_type, "value") else entry.entity_type
            results.append(
                AuditLogDTO(
                    audit_log_id=entry.audit_log_id,
                    actor=entry.actor,
                    timestamp=entry.timestamp,
                    action_type=action,
                    entity_type=entity,
                    entity_id=entry.entity_id,
                    description=entry.description,
                )
            )
        return results
