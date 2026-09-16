"""AuditService: append-only audit log recording and retrieval."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import AuditLogDTO
from app.models import AuditActionType, AuditEntityType, AuditLog


def _coerce_action_type(action_type: str) -> AuditActionType:
    """Coerce a free-form action type string into the AuditActionType enum.

    Falls back to storing the raw value on the enum's value member if an
    exact match by name/value is not found, to avoid dropping audit data.
    """
    if isinstance(action_type, AuditActionType):
        return action_type
    candidate = str(action_type).strip()
    for member in AuditActionType:
        if member.value == candidate or member.name == candidate:
            return member
    # Try uppercase name match as a last resort.
    try:
        return AuditActionType[candidate.upper()]
    except KeyError:
        # As a safe fallback, use the first declared member is wrong; instead
        # raise a clear error so misuse is caught during development/tests.
        raise ValueError(f"Unknown audit action_type: {action_type!r}")


def _coerce_entity_type(entity_type: str) -> AuditEntityType:
    """Coerce a free-form entity type string into the AuditEntityType enum."""
    if isinstance(entity_type, AuditEntityType):
        return entity_type
    candidate = str(entity_type).strip()
    for member in AuditEntityType:
        if member.value == candidate or member.name == candidate:
            return member
    try:
        return AuditEntityType[candidate.upper()]
    except KeyError:
        raise ValueError(f"Unknown audit entity_type: {entity_type!r}")


class AuditService:
    """Records and retrieves append-only audit log entries."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def log_action(
        self,
        actor: str,
        action_type: str,
        entity_type: str,
        entity_id: int,
        description: str,
    ) -> None:
        """Write one AuditLog row.

        `actor` defaults to 'Unknown' when blank (None or whitespace-only).
        """
        resolved_actor = actor.strip() if actor and actor.strip() else "Unknown"

        entry = AuditLog(
            actor=resolved_actor,
            timestamp=datetime.now(timezone.utc),
            action_type=_coerce_action_type(action_type),
            entity_type=_coerce_entity_type(entity_type),
            entity_id=entity_id,
            description=description or "",
        )
        self._db.add(entry)
        self._db.commit()
        self._db.refresh(entry)

    def list_entries(self) -> list[AuditLogDTO]:
        """List all audit log entries, newest first."""
        stmt = select(AuditLog).order_by(AuditLog.timestamp.desc(), AuditLog.audit_log_id.desc())
        rows = self._db.execute(stmt).scalars().all()
        return [self._to_dto(row) for row in rows]

    @staticmethod
    def _to_dto(row: AuditLog) -> AuditLogDTO:
        action_value = row.action_type.value if hasattr(row.action_type, "value") else str(row.action_type)
        entity_value = row.entity_type.value if hasattr(row.entity_type, "value") else str(row.entity_type)
        return AuditLogDTO(
            audit_log_id=row.audit_log_id,
            actor=row.actor,
            timestamp=row.timestamp,
            action_type=action_value,
            entity_type=entity_value,
            entity_id=row.entity_id,
            description=row.description,
        )
