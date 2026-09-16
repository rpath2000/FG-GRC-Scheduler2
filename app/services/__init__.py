"""Business-logic services for instruments, reservations, master data, and audit logging.

This package exposes:
    - InstrumentService
    - ReservationService
    - MasterDataService
    - AuditService

Each service is constructed with a SQLAlchemy `Session` and performs all
database access through that session. Services raise the shared domain
exceptions declared in `app.contracts` (ValidationError, DuplicateError,
ConflictError, NotFoundError, InvalidStatusError) so that callers (REST
handlers) can translate them into appropriate HTTP responses.
"""

from app.services.instrument_service import InstrumentService
from app.services.reservation_service import ReservationService
from app.services.master_data_service import MasterDataService
from app.services.audit_service import AuditService

__all__ = [
    "InstrumentService",
    "ReservationService",
    "MasterDataService",
    "AuditService",
]
