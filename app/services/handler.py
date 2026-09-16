"""REST handlers for instruments, reservations, master data, and audit logging.

Routes are namespaced under ``/api`` to avoid collision with server-rendered
pages owned by other components (which serve human-facing routes such as
``/instruments`` and ``/scheduler``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.contracts import (
    ConflictError,
    DuplicateError,
    InstrumentCreateDTO,
    InstrumentFilterDTO,
    InstrumentUpdateDTO,
    InvalidStatusError,
    NotFoundError,
    ReservationCreateDTO,
    ValidationError,
)
from app.models import get_db
from app.services import (
    AuditService,
    InstrumentService,
    MasterDataService,
    ReservationService,
)

router = APIRouter(prefix="/api", tags=["instruments", "reservations", "master-data", "audit"])


class InstrumentCreateRequest(BaseModel):
    name: str
    nickname: str
    location_id: int
    vendor_id: int
    type_id: int
    asset_id: Optional[str] = None
    color: Optional[str] = None


class InstrumentUpdateRequest(BaseModel):
    name: str
    nickname: str
    location_id: int
    vendor_id: int
    type_id: int
    asset_id: Optional[str] = None
    color: Optional[str] = None
    is_active: bool


class StatusChangeRequest(BaseModel):
    status: str


class ReservationCreateRequest(BaseModel):
    instrument_id: int
    start_datetime: datetime
    end_datetime: datetime
    reservation_purpose_id: int
    requested_by: Optional[str] = None
    can_be_overridden: bool = False


class MasterDataNameRequest(BaseModel):
    name: str


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, DuplicateError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, InvalidStatusError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, ValidationError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="Internal server error")


# --------------------------------------------------------------------------- Instruments

@router.post("/instruments")
def create_instrument(payload: InstrumentCreateRequest, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        dto = service.create(InstrumentCreateDTO(**payload.model_dump()))
        db.commit()
        return dto
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.put("/instruments/{instrument_id}")
def update_instrument(instrument_id: int, payload: InstrumentUpdateRequest, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        dto = service.update(instrument_id, InstrumentUpdateDTO(**payload.model_dump()))
        db.commit()
        return dto
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.get("/instruments/{instrument_id}")
def get_instrument(instrument_id: int, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        return service.get_by_id(instrument_id)
    except NotFoundError as exc:
        raise _http_error(exc)


@router.get("/instruments")
def list_instruments(
    nickname: Optional[str] = Query(default=None),
    location_id: Optional[int] = Query(default=None),
    vendor_id: Optional[int] = Query(default=None),
    type_id: Optional[int] = Query(default=None),
    favorites_only: Optional[bool] = Query(default=None),
    db: Session = Depends(get_db),
):
    service = InstrumentService(db)
    filters = InstrumentFilterDTO(
        nickname=nickname,
        location_id=location_id,
        vendor_id=vendor_id,
        type_id=type_id,
        favorites_only=favorites_only,
    )
    return service.list_active(filters)


@router.get("/instruments/schedulable/list")
def list_schedulable_instruments(db: Session = Depends(get_db)):
    service = InstrumentService(db)
    return service.list_schedulable()


@router.post("/instruments/{instrument_id}/status")
def change_instrument_status(instrument_id: int, payload: StatusChangeRequest, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        dto = service.change_status(instrument_id, payload.status)
        db.commit()
        return dto
    except (ValidationError, NotFoundError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.delete("/instruments/{instrument_id}")
def delete_instrument(instrument_id: int, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        service.soft_delete(instrument_id)
        db.commit()
        return {"status": "deleted"}
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


@router.post("/instruments/{instrument_id}/favorite")
def toggle_instrument_favorite(instrument_id: int, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        dto = service.toggle_favorite(instrument_id)
        db.commit()
        return dto
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


# --------------------------------------------------------------------------- Reservations

@router.post("/reservations")
def create_reservation(payload: ReservationCreateRequest, db: Session = Depends(get_db)):
    service = ReservationService(db)
    try:
        result = service.create(ReservationCreateDTO(**payload.model_dump()))
        db.commit()
        return result
    except (ValidationError, ConflictError, NotFoundError, InvalidStatusError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.get("/reservations")
def list_reservations(
    instrument_ids: list[int] = Query(default=[]),
    start: datetime = Query(...),
    end: datetime = Query(...),
    db: Session = Depends(get_db),
):
    service = ReservationService(db)
    return service.list_by_instrument_and_range(instrument_ids, start, end)


# --------------------------------------------------------------------------- Master data: Locations

@router.post("/master-data/locations")
def create_location(payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.create_location(payload.name)
        db.commit()
        return dto
    except (ValidationError, DuplicateError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.put("/master-data/locations/{location_id}")
def update_location(location_id: int, payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.update_location(location_id, payload.name)
        db.commit()
        return dto
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.get("/master-data/locations")
def list_locations(active_only: bool = Query(default=True), db: Session = Depends(get_db)):
    service = MasterDataService(db)
    return service.list_locations(active_only)


@router.post("/master-data/locations/{location_id}/deactivate")
def deactivate_location(location_id: int, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        usage_count = service.deactivate_location(location_id)
        db.commit()
        return {"usage_count": usage_count}
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


@router.post("/master-data/locations/{location_id}/reactivate")
def reactivate_location(location_id: int, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.reactivate_location(location_id)
        db.commit()
        return dto
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


# --------------------------------------------------------------------------- Master data: Vendors

@router.post("/master-data/vendors")
def create_vendor(payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.create_vendor(payload.name)
        db.commit()
        return dto
    except (ValidationError, DuplicateError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.put("/master-data/vendors/{vendor_id}")
def update_vendor(vendor_id: int, payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.update_vendor(vendor_id, payload.name)
        db.commit()
        return dto
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.get("/master-data/vendors")
def list_vendors(active_only: bool = Query(default=True), db: Session = Depends(get_db)):
    service = MasterDataService(db)
    return service.list_vendors(active_only)


@router.post("/master-data/vendors/{vendor_id}/deactivate")
def deactivate_vendor(vendor_id: int, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        usage_count = service.deactivate_vendor(vendor_id)
        db.commit()
        return {"usage_count": usage_count}
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


@router.post("/master-data/vendors/{vendor_id}/reactivate")
def reactivate_vendor(vendor_id: int, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.reactivate_vendor(vendor_id)
        db.commit()
        return dto
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


# --------------------------------------------------------------------------- Master data: Types

@router.post("/master-data/types")
def create_type(payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.create_type(payload.name)
        db.commit()
        return dto
    except (ValidationError, DuplicateError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.put("/master-data/types/{type_id}")
def update_type(type_id: int, payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.update_type(type_id, payload.name)
        db.commit()
        return dto
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.get("/master-data/types")
def list_types(active_only: bool = Query(default=True), db: Session = Depends(get_db)):
    service = MasterDataService(db)
    return service.list_types(active_only)


@router.post("/master-data/types/{type_id}/deactivate")
def deactivate_type(type_id: int, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        usage_count = service.deactivate_type(type_id)
        db.commit()
        return {"usage_count": usage_count}
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


@router.post("/master-data/types/{type_id}/reactivate")
def reactivate_type(type_id: int, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.reactivate_type(type_id)
        db.commit()
        return dto
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


# --------------------------------------------------------------------------- Master data: Purposes

@router.post("/master-data/purposes")
def create_purpose(payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.create_purpose(payload.name)
        db.commit()
        return dto
    except (ValidationError, DuplicateError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.put("/master-data/purposes/{purpose_id}")
def update_purpose(purpose_id: int, payload: MasterDataNameRequest, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.update_purpose(purpose_id, payload.name)
        db.commit()
        return dto
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        db.rollback()
        raise _http_error(exc)


@router.get("/master-data/purposes")
def list_purposes(active_only: bool = Query(default=True), db: Session = Depends(get_db)):
    service = MasterDataService(db)
    return service.list_purposes(active_only)


@router.post("/master-data/purposes/{purpose_id}/deactivate")
def deactivate_purpose(purpose_id: int, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        usage_count = service.deactivate_purpose(purpose_id)
        db.commit()
        return {"usage_count": usage_count}
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


@router.post("/master-data/purposes/{purpose_id}/reactivate")
def reactivate_purpose(purpose_id: int, db: Session = Depends(get_db)):
    service = MasterDataService(db)
    try:
        dto = service.reactivate_purpose(purpose_id)
        db.commit()
        return dto
    except NotFoundError as exc:
        db.rollback()
        raise _http_error(exc)


# --------------------------------------------------------------------------- Audit log

@router.get("/audit-log")
def list_audit_entries(db: Session = Depends(get_db)):
    service = AuditService(db)
    return service.list_entries()
