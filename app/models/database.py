"""
Database engine, declarative Base, and session factory for the application.

This module is importable as `app.models.database` and is the single source
of truth for SQLAlchemy engine/session construction. All ORM models are
declared elsewhere in this package and import `Base` from here.
"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.db_url import DATABASE_URL

# `connect_args` is only meaningful for sqlite (allows use across threads in
# tests / dev). Postgres ignores it because we only pass it conditionally.
_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models in this application."""
    pass


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI-style dependency that yields a database session and guarantees
    it is closed after use, regardless of success or failure.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
