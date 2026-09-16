"""
Database engine, declarative Base, and session factory for the application.

This module builds the SQLAlchemy engine from the shared app.db_url module
(which owns DATABASE_URL and its sqlite fallback), declares the declarative
Base used by every ORM model, and exposes get_db() as the FastAPI session
dependency.

No database connection is opened at import time: create_engine() only
prepares the engine and imports the driver named in the URL; the actual
connection happens lazily on first use (inside get_db(), or inside the
alembic migration runner).
"""
from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.db_url import DATABASE_URL

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models in this application."""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a database session and closes it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
