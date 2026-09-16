"""REST handlers exposing services under app/services.

Routes are namespaced under /api/services to avoid colliding with the
server-rendered page routes owned by app.web. This router provides a thin
JSON layer over InstrumentService, ReservationService, MasterDataService,
and AuditService for programmatic/API consumers (e.g. htmx partials or
external integrations), while page rendering itself remains app.web's
responsibility.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
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
from app.services import AuditService, InstrumentService, MasterDataService, ReservationService

router = APIRouter(prefix="/api/services", tags=["services"])


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


# -- Instruments --------------------------------------------------------------

@router.post("/instruments")
def create_instrument(data: InstrumentCreateDTO, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        return service.create(data)
    except (ValidationError, DuplicateError, NotFoundError, ConflictError, InvalidStatusError) as exc:
        raise _http_error(exc)


@router.put("/instruments/{instrument_id}")
def update_instrument(instrument_id: int, data: InstrumentUpdateDTO, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        return service.update(instrument_id, data)
    except (ValidationError, DuplicateError, NotFoundError, ConflictError, InvalidStatusError) as exc:
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
    nickname: str | None = Query(default=None),
    location_id: int | None = Query(default=None),
    vendor_id: int | None = Query(default=None),
    type_id: int | None = Query(default=None),
    favorites_only: bool | None = Query(default=None),
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
def change_instrument_status(instrument_id: int, status: str, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        return service.change_status(instrument_id, status)
    except (ValidationError, NotFoundError) as exc:
        raise _http_error(exc)


@router.delete("/instruments/{instrument_id}")
def delete_instrument(instrument_id: int, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        service.soft_delete(instrument_id)
        return {"status": "deleted"}
    except NotFoundError as exc:
        raise _http_error(exc)


@router.post("/instruments/{instrument_id}/favorite")
def toggle_instrument_favorite(instrument_id: int, db: Session = Depends(get_db)):
    service = InstrumentService(db)
    try:
        return service.toggle_favorite(instrument_id)
    except NotFoundError as exc:
        raise _http_error(exc)


# -- Reservations --------------------------------------------------------------

@router.post("/reservations")
def create_reservation(data: ReservationCreateDTO, db: Session = Depends(get_db)):
    service = ReservationService(db)
    try:
        return service.create(data)
    except (ValidationError, ConflictError, NotFoundError, InvalidStatusError) as exc:
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


# -- Master data -----------------------------------------------------------

@router.get("/locations")
def list_locations(active_only: bool = Query(default=True), db: Session = Depends(get_db)):
    return MasterDataService(db).list_locations(active_only)


@router.post("/locations")
def create_location(name: str, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).create_location(name)
    except (ValidationError, DuplicateError) as exc:
        raise _http_error(exc)


@router.put("/locations/{location_id}")
def update_location(location_id: int, name: str, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).update_location(location_id, name)
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        raise _http_error(exc)


@router.post("/locations/{location_id}/deactivate")
def deactivate_location(location_id: int, db: Session = Depends(get_db)):
    try:
        usage = MasterDataService(db).deactivate_location(location_id)
        return {"usage_count": usage}
    except NotFoundError as exc:
        raise _http_error(exc)


@router.post("/locations/{location_id}/reactivate")
def reactivate_location(location_id: int, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).reactivate_location(location_id)
    except NotFoundError as exc:
        raise _http_error(exc)


@router.get("/vendors")
def list_vendors(active_only: bool = Query(default=True), db: Session = Depends(get_db)):
    return MasterDataService(db).list_vendors(active_only)


@router.post("/vendors")
def create_vendor(name: str, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).create_vendor(name)
    except (ValidationError, DuplicateError) as exc:
        raise _http_error(exc)


@router.put("/vendors/{vendor_id}")
def update_vendor(vendor_id: int, name: str, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).update_vendor(vendor_id, name)
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        raise _http_error(exc)


@router.post("/vendors/{vendor_id}/deactivate")
def deactivate_vendor(vendor_id: int, db: Session = Depends(get_db)):
    try:
        usage = MasterDataService(db).deactivate_vendor(vendor_id)
        return {"usage_count": usage}
    except NotFoundError as exc:
        raise _http_error(exc)


@router.post("/vendors/{vendor_id}/reactivate")
def reactivate_vendor(vendor_id: int, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).reactivate_vendor(vendor_id)
    except NotFoundError as exc:
        raise _http_error(exc)


@router.get("/types")
def list_types(active_only: bool = Query(default=True), db: Session = Depends(get_db)):
    return MasterDataService(db).list_types(active_only)


@router.post("/types")
def create_type(name: str, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).create_type(name)
    except (ValidationError, DuplicateError) as exc:
        raise _http_error(exc)


@router.put("/types/{type_id}")
def update_type(type_id: int, name: str, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).update_type(type_id, name)
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        raise _http_error(exc)


@router.post("/types/{type_id}/deactivate")
def deactivate_type(type_id: int, db: Session = Depends(get_db)):
    try:
        usage = MasterDataService(db).deactivate_type(type_id)
        return {"usage_count": usage}
    except NotFoundError as exc:
        raise _http_error(exc)


@router.post("/types/{type_id}/reactivate")
def reactivate_type(type_id: int, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).reactivate_type(type_id)
    except NotFoundError as exc:
        raise _http_error(exc)


@router.get("/purposes")
def list_purposes(active_only: bool = Query(default=True), db: Session = Depends(get_db)):
    return MasterDataService(db).list_purposes(active_only)


@router.post("/purposes")
def create_purpose(name: str, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).create_purpose(name)
    except (ValidationError, DuplicateError) as exc:
        raise _http_error(exc)


@router.put("/purposes/{purpose_id}")
def update_purpose(purpose_id: int, name: str, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).update_purpose(purpose_id, name)
    except (ValidationError, DuplicateError, NotFoundError) as exc:
        raise _http_error(exc)


@router.post("/purposes/{purpose_id}/deactivate")
def deactivate_purpose(purpose_id: int, db: Session = Depends(get_db)):
    try:
        usage = MasterDataService(db).deactivate_purpose(purpose_id)
        return {"usage_count": usage}
    except NotFoundError as exc:
        raise _http_error(exc)


@router.post("/purposes/{purpose_id}/reactivate")
def reactivate_purpose(purpose_id: int, db: Session = Depends(get_db)):
    try:
        return MasterDataService(db).reactivate_purpose(purpose_id)
    except NotFoundError as exc:
        raise _http_error(exc)


# -- Audit -----------------------------------------------------------------

@router.get("/audit-log")
def list_audit_entries(db: Session = Depends(get_db)):
    return AuditService(db).list_entries()
