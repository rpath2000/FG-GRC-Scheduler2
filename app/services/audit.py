"""Business logic for recording and listing audit log entries."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts import AuditActionType, AuditEntityType, AuditLogData
from app.models import AuditLog


class AuditService:
    """Records audit entries for create/update/status-change/delete/reservation actions."""

    def __init__(self, db: Session):
        self.db = db

    def record_action(
        self,
        action_type: AuditActionType,
        entity_type: AuditEntityType,
        entity_id: int,
        actor: str,
        description: str,
    ) -> None:
        resolved_actor = actor.strip() if actor and actor.strip() else "Unknown"
        entry = AuditLog(
            actor=resolved_actor,
            timestamp=datetime.now(timezone.utc),
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            description=description,
        )
        self.db.add(entry)
        self.db.flush()

    def list_entries(self) -> list[AuditLogData]:
        stmt = select(AuditLog).order_by(AuditLog.timestamp.desc())
        rows = self.db.execute(stmt).scalars().all()
        return [
            AuditLogData(
                audit_log_id=r.audit_log_id,
                actor=r.actor,
                timestamp=r.timestamp,
                action_type=(
                    r.action_type.value
                    if isinstance(r.action_type, AuditActionType)
                    else r.action_type
                ),
                entity_type=(
                    r.entity_type.value
                    if isinstance(r.entity_type, AuditEntityType)
                    else r.entity_type
                ),
                entity_id=r.entity_id,
                description=r.description,
            )
            for r in rows
        ]
