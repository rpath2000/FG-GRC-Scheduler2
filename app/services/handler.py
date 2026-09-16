"""REST handlers for instrument, master-data, reservation, audit-log, and
scheduler business operations exposed by app/services.

Only endpoints not already owned by app.web are declared here, under the
/api prefix, to avoid route collisions with the server-rendered page router.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.contracts import (
    DuplicateMasterDataError,
    InstrumentCreateDTO,
    InstrumentDTO,
    InstrumentFilterDTO,
    InstrumentUpdateDTO,
    InvalidInstrumentStatusError,
    NotFoundError,
    ReservationConflictError,
    ReservationCreateDTO,
    ReservationDTO,
    ReservationResultDTO,
    TimeBoundaryError,
)
from app.models import get_db
from app.services.audit_log import AuditLogService
from app.services.instrument import InstrumentService
from app.services.master_data import MasterDataService
from app.services.reservation import ReservationService
from app.services.scheduler import SchedulerService

router = APIRouter(prefix="/api/services", tags=["services"])


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------
@router.post("/instruments", response_model=None)
def create_instrument(data: InstrumentCreateDTO, db: Session = Depends(get_db)) -> InstrumentDTO:
    service = InstrumentService(db)
    try:
        return service.create(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/instruments/{instrument_id}", response_model=None)
def get_instrument(instrument_id: int, db: Session = Depends(get_db)) -> InstrumentDTO:
    service = InstrumentService(db)
    try:
        return service.get_instrument(instrument_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/instruments/{instrument_id}", response_model=None)
def update_instrument(
    instrument_id: int, data: InstrumentUpdateDTO, db: Session = Depends(get_db)
) -> InstrumentDTO:
    service = InstrumentService(db)
    try:
        return service.update(instrument_id, data)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/instruments/{instrument_id}", status_code=204)
def delete_instrument(instrument_id: int, db: Session = Depends(get_db)) -> None:
    service = InstrumentService(db)
    try:
        service.soft_delete(instrument_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------
@router.post("/reservations", response_model=None)
def create_reservation(data: ReservationCreateDTO, db: Session = Depends(get_db)) -> ReservationResultDTO:
    service = ReservationService(db)
    try:
        return service.create(data)
    except TimeBoundaryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ReservationConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except InvalidInstrumentStatusError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reservations", response_model=None)
def list_reservations(
    instrument_id: int,
    start_date: datetime,
    end_date: datetime,
    db: Session = Depends(get_db),
) -> list[ReservationDTO]:
    service = ReservationService(db)
    return service.list_reservations(instrument_id, start_date, end_date)


# ---------------------------------------------------------------------------
# Master data (create/update/deactivate only - list endpoints owned by app.web)
# ---------------------------------------------------------------------------
@router.post("/master-data/locations", response_model=None)
def create_location(name: str, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        return service.create_location(name)
    except DuplicateMasterDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/master-data/vendors", response_model=None)
def create_vendor(name: str, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        return service.create_vendor(name)
    except DuplicateMasterDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/master-data/types", response_model=None)
def create_type(name: str, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        return service.create_type(name)
    except DuplicateMasterDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/master-data/purposes", response_model=None)
def create_purpose(name: str, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        return service.create_purpose(name)
    except DuplicateMasterDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------
@router.get("/audit-log", response_model=None)
def list_audit_entries(db: Session = Depends(get_db)):
    service = AuditLogService(db)
    return service.list_entries()


# ---------------------------------------------------------------------------
# Scheduler timeline data
# ---------------------------------------------------------------------------
@router.get("/scheduler/timeline", response_model=None)
def get_timeline(date: datetime, view: str = "week", db: Session = Depends(get_db)):
    service = SchedulerService(db)
    try:
        return service.get_timeline(date, view)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
