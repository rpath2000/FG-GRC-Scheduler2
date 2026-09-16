"""Shared normalization helpers used across services for duplicate detection."""

from __future__ import annotations


def normalize_name(value: str | None) -> str:
    """Normalize a name for case/whitespace-insensitive comparison.

    Collapses surrounding whitespace and lowercases the value so that
    "ABC", " abc ", and "Abc" are all treated as duplicates.
    """
    if value is None:
        return ""
    return " ".join(value.strip().split()).lower()
