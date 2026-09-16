"""
Dialect-portable helper types shared by the ORM models.

UTCDateTime stores timezone-aware UTC datetimes. On PostgreSQL it maps to
TIMESTAMP WITH TIME ZONE; on other dialects (e.g. SQLite, used by tests) it
maps to a plain DateTime column and the application normalizes naive values
to UTC on the way in, since SQLite has no native timezone-aware type.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """A timezone-aware UTC DateTime that coerces naive datetimes to UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
