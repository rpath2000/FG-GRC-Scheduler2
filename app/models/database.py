"""
Shared SQLAlchemy engine, declarative Base and session dependency for the
whole application. Every other component imports from this module as
`app.models.database` (or via the `app.models` package re-exports).

The engine is built lazily from DATABASE_URL (via app.db_url) at import
time WITHOUT opening a connection - create_engine only prepares the
driver/pool, it does not connect. No database needs to be running for
this module to import successfully.
"""
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.engine import Engine

from app.db_url import DATABASE_URL

Base = declarative_base()

_connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    _connect_args = {"check_same_thread": False}

engine: Engine = create_engine(DATABASE_URL, connect_args=_connect_args, future=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


def get_db() -> Generator:
    """FastAPI dependency: yields a SQLAlchemy session and closes it after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
