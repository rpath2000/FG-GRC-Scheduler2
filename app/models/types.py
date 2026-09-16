"""
Dialect-portable column type helpers used by the ORM models.

`UTCDateTime` guarantees timezone-aware UTC datetimes on every dialect,
including SQLite (which has no native timezone-aware type). It stores
values normalized to UTC and always returns them with tzinfo=UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    """A DateTime type that is always timezone-aware and stored as UTC."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, datetime):
            raise TypeError(f"Expected datetime, got {type(value)!r}")
        if value.tzinfo is None:
            # Naive datetimes are coerced to UTC rather than silently
            # accepted as some unspecified local time.
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        else:
            value = value.astimezone(timezone.utc)
        return value
