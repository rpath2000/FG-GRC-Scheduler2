"""REST handlers for instrument, master data, reservation, scheduler, and audit services.

These endpoints are served under the /api prefix and do not overlap with any
server-rendered page route owned by app/web.
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.contracts import (
    AuditActionType,
    AuditEntityType,
    ConflictError,
    DuplicateError,
    InstrumentCreateData,
    InstrumentFilterData,
    InstrumentUpdateData,
    InvalidStatusError,
    NotFoundError,
    ReservationCreateData,
    ValidationError,
)
from app.models.database import get_db

from app.services.audit import AuditService
from app.services.instrument import InstrumentService
from app.services.master_data import MasterDataService
from app.services.reservation import ReservationService
from app.services.scheduler import SchedulerService
from app.services.seed import SeedService

router = APIRouter(prefix="/api", tags=["services"])


# --------------------------------------------------------------------------- schemas

class InstrumentCreateRequest(BaseModel):
    nickname: str
    name: str
    location_id: int
    vendor_id: int
    type_id: int
    asset_id: str | None = None
    color: str | None = None
    status: str
    is_active: bool = True
    actor: str | None = None


class InstrumentUpdateRequest(BaseModel):
    nickname: str | None = None
    name: str | None = None
    location_id: int | None = None
    vendor_id: int | None = None
    type_id: int | None = None
    asset_id: str | None = None
    color: str | None = None
    status: str | None = None
    is_active: bool | None = None
    actor: str | None = None


class MasterDataNameRequest(BaseModel):
    name: str
    actor: str | None = None


class ReservationCreateRequest(BaseModel):
    instrument_id: int
    start_time: datetime
    end_time: datetime
    purpose_id: int
    requested_by: str | None = None
    can_be_overridden: bool = True


# --------------------------------------------------------------------------- instruments

@router.post("/instruments")
def create_instrument(payload: InstrumentCreateRequest, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    data = InstrumentCreateData(
        nickname=payload.nickname,
        name=payload.name,
        location_id=payload.location_id,
        vendor_id=payload.vendor_id,
        type_id=payload.type_id,
        asset_id=payload.asset_id,
        color=payload.color,
        status=payload.status,
        is_active=payload.is_active,
        actor=payload.actor or "Unknown",
    )
    try:
        result = service.create_instrument(data)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result


@router.get("/instruments/{instrument_id}")
def get_instrument(instrument_id: int, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        return service.get_instrument(instrument_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/instruments/{instrument_id}")
def update_instrument(
    instrument_id: int, payload: InstrumentUpdateRequest, db: Session = Depends(get_db)
):
    service = InstrumentService(db)
    data = InstrumentUpdateData(
        nickname=payload.nickname,
        name=payload.name,
        location_id=payload.location_id,
        vendor_id=payload.vendor_id,
        type_id=payload.type_id,
        asset_id=payload.asset_id,
        color=payload.color,
        status=payload.status,
        is_active=payload.is_active,
        actor=payload.actor or "Unknown",
    )
    try:
        return service.update_instrument(instrument_id, data)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/instruments/{instrument_id}")
def delete_instrument(
    instrument_id: int, actor: str = Query(default="Unknown"), db: Session = Depends(get_db)
):
    service = InstrumentService(db)
    try:
        service.soft_delete_instrument(instrument_id, actor)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted"}


@router.get("/instruments")
def list_instruments(
    nickname: str | None = None,
    location_id: int | None = None,
    vendor_id: int | None = None,
    type_id: int | None = None,
    favorites: bool | None = None,
    sort_by: str | None = None,
    db: Session = Depends(get_db),
):
    service = InstrumentService(db)
    filters = InstrumentFilterData(
        nickname=nickname,
        location_id=location_id,
        vendor_id=vendor_id,
        type_id=type_id,
        favorites=favorites,
        sort_by=sort_by,
    )
    return service.list_instruments(filters)


@router.get("/instruments/schedulable/list")
def list_schedulable_instruments(db: Session = Depends(get_db)):
    service = InstrumentService(db)
    return service.list_schedulable_instruments()


# --------------------------------------------------------------------------- master data

@router.post("/master-data/locations")
def create_location(payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        return service.create_location(payload.name, payload.actor or "Unknown")
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/master-data/locations")
def list_locations(include_inactive: bool = False, db: Session = Depends(get_db)):
    return MasterDataService(db).list_locations(include_inactive)


@router.post("/master-data/vendors")
def create_vendor(payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        return service.create_vendor(payload.name, payload.actor or "Unknown")
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/master-data/vendors")
def list_vendors(include_inactive: bool = False, db: Session = Depends(get_db)):
    return MasterDataService(db).list_vendors(include_inactive)


@router.post("/master-data/types")
def create_type(payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        return service.create_type(payload.name, payload.actor or "Unknown")
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/master-data/types")
def list_types(include_inactive: bool = False, db: Session = Depends(get_db)):
    return MasterDataService(db).list_types(include_inactive)


@router.post("/master-data/purposes")
def create_purpose(payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        return service.create_purpose(payload.name, payload.actor or "Unknown")
    except DuplicateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/master-data/purposes")
def list_purposes(include_inactive: bool = False, db: Session = Depends(get_db)):
    return MasterDataService(db).list_purposes(include_inactive)


# --------------------------------------------------------------------------- reservations

@router.post("/reservations")
def create_reservation(payload: ReservationCreateRequest, db: Session = Depends(get_db)):
    service = ReservationService(db)
    data = ReservationCreateData(
        instrument_id=payload.instrument_id,
        start_time=payload.start_time,
        end_time=payload.end_time,
        purpose_id=payload.purpose_id,
        requested_by=payload.requested_by or "Unknown",
        can_be_overridden=payload.can_be_overridden,
    )
    try:
        return service.create_reservation(data)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except InvalidStatusError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --------------------------------------------------------------------------- scheduler

@router.get("/scheduler/timeline")
def get_timeline_data(
    target_date: date = Query(alias="date"),
    view: str = Query(default="day"),
    db: Session = Depends(get_db),
):
    service = SchedulerService(db)
    return service.get_timeline_data(target_date, view)


# --------------------------------------------------------------------------- audit

@router.get("/audit-log")
def list_audit_entries(db: Session = Depends(get_db)):
    return AuditService(db).list_entries()


# --------------------------------------------------------------------------- seed

@router.post("/seed")
def load_seed_data(db: Session = Depends(get_db)):
    SeedService(db).load_seed_data()
    return {"status": "seeded"}
