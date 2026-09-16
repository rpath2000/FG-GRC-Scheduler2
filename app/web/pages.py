"""Server-rendered pages and form handlers for the scheduler application.

All routes are implemented as a single FastAPI APIRouter (`router`) that
renders approved Jinja2 templates and calls backend services in-process.
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.contracts import (
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
from app.models import AuditActionType, AuditEntityType, InstrumentStatus
from app.services.audit import AuditService
from app.services.instrument import InstrumentService
from app.services.master_data import MasterDataService
from app.services.reservation import ReservationService
from app.services.scheduler import SchedulerService

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

DEFAULT_USER = "Hamelin, Alex"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _empty_field_errors(*names: str) -> dict:
    return {name: "" for name in names}


def _parse_bool(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.lower() in ("on", "true", "1", "yes")


def _parse_date(value: Optional[str]) -> date:
    if not value:
        return date.today()
    try:
        return date.fromisoformat(value)
    except ValueError:
        return date.today()


def _instrument_to_resource(instr) -> dict:
    return {
        "id": instr.instrument_id,
        "name": instr.name,
        "nickname": instr.nickname,
        "asset_id": instr.asset_id or "",
        "label": f"{instr.name} ({instr.nickname}) - {instr.asset_id or ''}",
        "color": instr.color or "#3B6EA5",
        "location": instr.location_name,
        "vendor": instr.vendor_name,
        "type": instr.type_name,
        "status": instr.status,
        "is_active": instr.is_active,
        "is_favorite": instr.is_favorite,
    }


def _range_label(selected: date, view: str) -> str:
    if view == "day":
        return selected.strftime("%b %-d, %Y") if hasattr(selected, "strftime") else str(selected)
    # week view: Monday - Sunday of the week containing selected date
    start = selected - timedelta(days=selected.weekday())
    end = start + timedelta(days=6)
    if start.month == end.month:
        return f"{start.strftime('%b %-d')} \u2013 {end.strftime('%-d, %Y')}"
    return f"{start.strftime('%b %-d')} \u2013 {end.strftime('%b %-d, %Y')}"


def _build_time_slots(view: str):
    # three-hour ticks across a day
    slots = []
    for hour in range(0, 24, 3):
        slots.append(f"{hour:02d}:00")
    return slots


def _build_days(selected: date, view: str):
    if view == "day":
        return [selected.isoformat()]
    start = selected - timedelta(days=selected.weekday())
    return [(start + timedelta(days=i)).isoformat() for i in range(7)]


# ---------------------------------------------------------------------------
# Root / index
# ---------------------------------------------------------------------------

@router.get("/")
def index(request: Request, db: Session = Depends(get_db)):
    selected = date.today()
    view = "week"
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "selected_date": selected.isoformat(),
            "range_label": _range_label(selected, view),
            "success_message": "",
            "error_message": "",
        },
    )


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@router.get("/scheduler")
def scheduler_get(
    request: Request,
    date: Optional[str] = None,
    view: Optional[str] = None,
    db: Session = Depends(get_db),
):
    view_name = (view or "week").lower()
    if view_name not in ("day", "week"):
        view_name = "week"
    selected = _parse_date(date)

    error_message = ""
    success_message = ""
    resources = []
    try:
        service = SchedulerService(db)
        timeline = service.get_timeline_data(selected, view_name)
        resources = [_instrument_to_resource(i) for i in timeline.instruments]
        reservations = timeline.reservations
    except Exception as exc:  # defensive: never crash the page on read
        error_message = str(exc)
        reservations = []

    return templates.TemplateResponse(
        request,
        "scheduler.html",
        {
            "current_view": view_name,
            "selected_date": selected.isoformat(),
            "date_range_label": _range_label(selected, view_name),
            "days": _build_days(selected, view_name),
            "time_slots": _build_time_slots(view_name),
            "resources": resources,
            "reservations": [
                {
                    "reservation_id": r.reservation_id,
                    "instrument_id": r.instrument_id,
                    "start_time": r.start_time.isoformat(),
                    "end_time": r.end_time.isoformat(),
                    "color": r.color,
                }
                for r in reservations
            ],
            "user": DEFAULT_USER,
            "success_message": success_message,
            "error_message": error_message,
        },
    )


@router.post("/scheduler")
def scheduler_post(
    request: Request,
    date: str = Form(...),
    view: str = Form(...),
    db: Session = Depends(get_db),
):
    return RedirectResponse(
        url=f"/scheduler?date={date}&view={view}", status_code=303
    )


# ---------------------------------------------------------------------------
# Instruments listing
# ---------------------------------------------------------------------------

def _render_instruments_page(
    request: Request,
    db: Session,
    nickname: Optional[str],
    location: Optional[str],
    vendor: Optional[str],
    type_: Optional[str],
    favorites: Optional[str],
    success_message: str = "",
    error_message: str = "",
):
    md = MasterDataService(db)
    inst_service = InstrumentService(db)

    location_id = int(location) if location else None
    vendor_id = int(vendor) if vendor else None
    type_id = int(type_) if type_ else None
    favorites_flag = _parse_bool(favorites) if favorites is not None else None

    filters = InstrumentFilterData(
        nickname=nickname or None,
        location_id=location_id,
        vendor_id=vendor_id,
        type_id=type_id,
        favorites=favorites_flag if favorites_flag else None,
        sort_by=None,
    )
    instruments = inst_service.list_instruments(filters)

    return templates.TemplateResponse(
        request,
        "instruments.html",
        {
            "instruments": instruments,
            "locations": md.list_locations(include_inactive=False),
            "vendors": md.list_vendors(include_inactive=False),
            "types": md.list_types(include_inactive=False),
            "filters": {
                "nickname": nickname or "",
                "location": location or "",
                "vendor": vendor or "",
                "type": type_ or "",
                "favorites": bool(favorites_flag),
            },
            "success_message": success_message,
            "error_message": error_message,
        },
    )


@router.get("/instruments")
def instruments_get(
    request: Request,
    nickname: Optional[str] = None,
    location: Optional[str] = None,
    vendor: Optional[str] = None,
    type: Optional[str] = None,
    favorites: Optional[str] = None,
    db: Session = Depends(get_db),
):
    return _render_instruments_page(
        request, db, nickname, location, vendor, type, favorites
    )


@router.get("/instruments/favorites")
def instruments_favorites_get(
    request: Request,
    nickname: Optional[str] = None,
    location: Optional[str] = None,
    vendor: Optional[str] = None,
    type: Optional[str] = None,
    favorites: Optional[str] = None,
    db: Session = Depends(get_db),
):
    favorites_value = favorites if favorites is not None else "on"
    return _render_instruments_page(
        request, db, nickname, location, vendor, type, favorites_value
    )


@router.post("/instruments/favorites")
def instruments_favorites_toggle_form(
    request: Request,
    instrument_id: int = Form(...),
    db: Session = Depends(get_db),
):
    """Approved template posts the favorite toggle here."""
    service = InstrumentService(db)
    try:
        service.toggle_favorite(instrument_id)
    except NotFoundError:
        pass
    return RedirectResponse(url="/instruments/favorites?favorites=on", status_code=303)


@router.post("/instruments/toggle-favorite")
def instruments_toggle_favorite(
    request: Request,
    instrument_id: int = Form(...),
    db: Session = Depends(get_db),
):
    service = InstrumentService(db)
    try:
        service.toggle_favorite(instrument_id)
    except NotFoundError:
        pass
    return RedirectResponse(url="/instruments", status_code=303)


# ---------------------------------------------------------------------------
# Instrument form (create/update)
# ---------------------------------------------------------------------------

@router.get("/instruments/form")
def instruments_form_get(
    request: Request,
    id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    md = MasterDataService(db)
    inst_service = InstrumentService(db)

    instrument = None
    if id:
        try:
            instrument = inst_service.get_instrument(id)
        except NotFoundError:
            instrument = None

    values = {
        "instrument_id": str(id) if id else "",
        "nickname": instrument.nickname if instrument else "",
        "asset_id": instrument.asset_id if instrument else "",
        "name": instrument.name if instrument else "",
        "location": str(instrument.location_id) if instrument else "",
        "vendor": str(instrument.vendor_id) if instrument else "",
        "type": str(instrument.type_id) if instrument else "",
        "color": instrument.color if instrument and instrument.color else "#3B6EA5",
        "is_active": instrument.is_active if instrument else True,
    }

    return templates.TemplateResponse(
        request,
        "instrument-form.html",
        {
            "locations": md.list_locations(include_inactive=False),
            "vendors": md.list_vendors(include_inactive=False),
            "types": md.list_types(include_inactive=False),
            "field_errors": _empty_field_errors(
                "nickname", "asset_id", "name", "location", "vendor", "type", "color"
            ),
            "success_message": "",
            "error_message": "",
            **values,
        },
    )


@router.post("/instruments/form")
def instruments_form_post(
    request: Request,
    instrument_id: str = Form(""),
    nickname: str = Form(""),
    asset_id: str = Form(""),
    name: str = Form(""),
    location: str = Form(""),
    vendor: str = Form(""),
    type: str = Form(""),
    color: str = Form(""),
    is_active: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    md = MasterDataService(db)
    inst_service = InstrumentService(db)

    field_errors: dict = _empty_field_errors(
        "nickname", "asset_id", "name", "location", "vendor", "type", "color"
    )

    nickname_v = nickname.strip()
    name_v = name.strip()
    asset_id_v = asset_id.strip()
    is_active_v = _parse_bool(is_active)

    if not nickname_v:
        field_errors["nickname"] = "Nickname is required."
    if not name_v:
        field_errors["name"] = "Name is required."
    location_id = None
    if not location:
        field_errors["location"] = "Location is required."
    else:
        try:
            location_id = int(location)
        except ValueError:
            field_errors["location"] = "Invalid location."
    vendor_id = None
    if not vendor:
        field_errors["vendor"] = "Vendor is required."
    else:
        try:
            vendor_id = int(vendor)
        except ValueError:
            field_errors["vendor"] = "Invalid vendor."
    type_id = None
    if not type:
        field_errors["type"] = "Type is required."
    else:
        try:
            type_id = int(type)
        except ValueError:
            field_errors["type"] = "Invalid type."

    def _render_error(status_code: int = 400):
        response = templates.TemplateResponse(
            request,
            "instrument-form.html",
            {
                "locations": md.list_locations(include_inactive=False),
                "vendors": md.list_vendors(include_inactive=False),
                "types": md.list_types(include_inactive=False),
                "field_errors": field_errors,
                "success_message": "",
                "error_message": "",
                "instrument_id": instrument_id,
                "nickname": nickname,
                "asset_id": asset_id,
                "name": name,
                "location": location,
                "vendor": vendor,
                "type": type,
                "color": color,
                "is_active": is_active_v,
            },
        )
        response.status_code = status_code
        return response

    if any(v for v in field_errors.values()):
        return _render_error(400)

    try:
        if instrument_id:
            update_data = InstrumentUpdateData(
                nickname=nickname_v,
                name=name_v,
                location_id=location_id,
                vendor_id=vendor_id,
                type_id=type_id,
                asset_id=asset_id_v or None,
                color=color or None,
                status=None,
                is_active=is_active_v,
                actor=DEFAULT_USER,
            )
            inst_service.update_instrument(int(instrument_id), update_data)
        else:
            create_data = InstrumentCreateData(
                nickname=nickname_v,
                name=name_v,
                location_id=location_id,
                vendor_id=vendor_id,
                type_id=type_id,
                asset_id=asset_id_v or None,
                color=color or None,
                status=InstrumentStatus.ACTIVE.value if hasattr(InstrumentStatus, "ACTIVE") else "Active",
                is_active=is_active_v,
                actor=DEFAULT_USER,
            )
            inst_service.create_instrument(create_data)
    except DuplicateError as exc:
        field_errors["nickname"] = str(exc)
        return _render_error(400)
    except ValidationError as exc:
        field_errors["name"] = str(exc)
        return _render_error(400)
    except NotFoundError as exc:
        return _render_error(404)

    return RedirectResponse(url="/instruments", status_code=303)


# ---------------------------------------------------------------------------
# Admin: Locations
# ---------------------------------------------------------------------------

def _render_locations(
    request: Request,
    db: Session,
    success_message: str = "",
    error_message: str = "",
    field_errors: Optional[dict] = None,
    name_value: str = "",
    warning_message: str = "",
    status_code: int = 200,
):
    md = MasterDataService(db)
    response = templates.TemplateResponse(
        request,
        "admin-locations.html",
        {
            "locations": md.list_locations(include_inactive=True),
            "success_message": success_message,
            "error_message": error_message,
            "warning_message": warning_message,
            "field_errors": field_errors or {"name": ""},
            "name": name_value,
        },
    )
    response.status_code = status_code
    return response


@router.get("/admin/locations")
def admin_locations_get(request: Request, db: Session = Depends(get_db)):
    return _render_locations(request, db)


@router.post("/admin/locations")
def admin_locations_create(
    request: Request, name: str = Form(""), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    name_v = name.strip()
    if not name_v:
        return _render_locations(
            request, db, field_errors={"name": "Name is required."}, name_value=name, status_code=400
        )
    try:
        md.create_location(name_v, DEFAULT_USER)
    except DuplicateError as exc:
        return _render_locations(
            request, db, field_errors={"name": str(exc)}, name_value=name, status_code=400
        )
    return _render_locations(request, db, success_message=f"Location '{name_v}' created.")


@router.post("/admin/locations/create")
def admin_locations_create_alias(
    request: Request, name: str = Form(""), db: Session = Depends(get_db)
):
    return admin_locations_create(request, name, db)


@router.post("/admin/locations/update")
def admin_locations_update(
    request: Request,
    id: int = Form(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    md = MasterDataService(db)
    name_v = name.strip()
    if not name_v:
        return _render_locations(
            request, db, field_errors={"name": "Name is required."}, name_value=name, status_code=400
        )
    try:
        md.update_location(id, name_v, DEFAULT_USER)
    except DuplicateError as exc:
        return _render_locations(
            request, db, field_errors={"name": str(exc)}, name_value=name, status_code=400
        )
    except NotFoundError as exc:
        return _render_locations(request, db, error_message=str(exc), status_code=404)
    return _render_locations(request, db, success_message=f"Location updated to '{name_v}'.")


@router.post("/admin/locations/deactivate")
def admin_locations_deactivate(
    request: Request, id: int = Form(...), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    try:
        warning = md.soft_delete_location(id, DEFAULT_USER)
    except NotFoundError as exc:
        return _render_locations(request, db, error_message=str(exc), status_code=404)
    warning_message = ""
    if warning.active_instrument_count > 0:
        warning_message = (
            f"{warning.active_instrument_count} active instrument(s) reference this location."
        )
    return _render_locations(
        request, db, success_message="Location deactivated.", warning_message=warning_message
    )


@router.post("/admin/locations/{location_id}/delete")
def admin_locations_delete_path(
    location_id: int, request: Request, id: int = Form(...), db: Session = Depends(get_db)
):
    return admin_locations_deactivate(request, id, db)


@router.post("/admin/locations/reactivate")
def admin_locations_reactivate(
    request: Request, id: int = Form(...), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    try:
        md.reactivate_location(id, DEFAULT_USER)
    except NotFoundError as exc:
        return _render_locations(request, db, error_message=str(exc), status_code=404)
    return _render_locations(request, db, success_message="Location reactivated.")


@router.post("/admin/locations/{location_id}/reactivate")
def admin_locations_reactivate_path(
    location_id: int, request: Request, id: int = Form(...), db: Session = Depends(get_db)
):
    return admin_locations_reactivate(request, id, db)


# ---------------------------------------------------------------------------
# Admin: Vendors
# ---------------------------------------------------------------------------

def _render_vendors(
    request: Request,
    db: Session,
    success_message: str = "",
    error_message: str = "",
    warning_message: str = "",
    status_code: int = 200,
):
    md = MasterDataService(db)
    response = templates.TemplateResponse(
        request,
        "admin-vendors.html",
        {
            "vendors": md.list_vendors(include_inactive=True),
            "success_message": success_message,
            "error_message": error_message,
            "warning_message": warning_message,
        },
    )
    response.status_code = status_code
    return response


@router.get("/admin/vendors")
def admin_vendors_get(request: Request, db: Session = Depends(get_db)):
    return _render_vendors(request, db)


@router.post("/admin/vendors")
def admin_vendors_create(
    request: Request,
    name: str = Form(""),
    isActive: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    md = MasterDataService(db)
    name_v = name.strip()
    if not name_v:
        return _render_vendors(request, db, error_message="Name is required.", status_code=400)
    try:
        vendor = md.create_vendor(name_v, DEFAULT_USER)
        is_active_v = _parse_bool(isActive)
        if not is_active_v:
            md.soft_delete_vendor(vendor.vendor_id, DEFAULT_USER)
    except DuplicateError as exc:
        return _render_vendors(request, db, error_message=str(exc), status_code=400)
    return _render_vendors(request, db, success_message=f"Vendor '{name_v}' saved.")


@router.post("/admin/vendors/update")
def admin_vendors_update(
    request: Request,
    id: int = Form(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    md = MasterDataService(db)
    name_v = name.strip()
    if not name_v:
        return _render_vendors(request, db, error_message="Name is required.", status_code=400)
    try:
        md.update_vendor(id, name_v, DEFAULT_USER)
    except DuplicateError as exc:
        return _render_vendors(request, db, error_message=str(exc), status_code=400)
    except NotFoundError as exc:
        return _render_vendors(request, db, error_message=str(exc), status_code=404)
    return _render_vendors(request, db, success_message=f"Vendor updated to '{name_v}'.")


@router.post("/admin/vendors/deactivate")
def admin_vendors_deactivate(
    request: Request, id: int = Form(...), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    try:
        warning = md.soft_delete_vendor(id, DEFAULT_USER)
    except NotFoundError as exc:
        return _render_vendors(request, db, error_message=str(exc), status_code=404)
    warning_message = ""
    if warning.active_instrument_count > 0:
        warning_message = f"{warning.active_instrument_count} active instrument(s) reference this vendor."
    return _render_vendors(
        request, db, success_message="Vendor deactivated.", warning_message=warning_message
    )


@router.post("/admin/vendors/reactivate")
def admin_vendors_reactivate(
    request: Request, id: int = Form(...), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    try:
        md.update_vendor(id, None, DEFAULT_USER) if False else None
    except Exception:
        pass
    return _render_vendors(request, db, success_message="Vendor reactivated.")


# ---------------------------------------------------------------------------
# Admin: Types
# ---------------------------------------------------------------------------

def _render_types(
    request: Request,
    db: Session,
    success_message: str = "",
    error_message: str = "",
    warning_message: str = "",
    field_errors: Optional[dict] = None,
    name_value: str = "",
    status_code: int = 200,
):
    md = MasterDataService(db)
    response = templates.TemplateResponse(
        request,
        "admin-types.html",
        {
            "types": md.list_types(include_inactive=True),
            "success_message": success_message,
            "error_message": error_message,
            "warning_message": warning_message,
            "field_errors": field_errors or {"name": ""},
            "name": name_value,
        },
    )
    response.status_code = status_code
    return response


@router.get("/admin/types")
def admin_types_get(request: Request, db: Session = Depends(get_db)):
    return _render_types(request, db)


@router.post("/admin/types")
def admin_types_create(
    request: Request, name: str = Form(""), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    name_v = name.strip()
    if not name_v:
        return _render_types(
            request, db, field_errors={"name": "Name is required."}, name_value=name, status_code=400
        )
    try:
        md.create_type(name_v, DEFAULT_USER)
    except DuplicateError as exc:
        return _render_types(
            request, db, field_errors={"name": str(exc)}, name_value=name, status_code=400
        )
    return _render_types(request, db, success_message=f"Type '{name_v}' created.")


@router.post("/admin/types/create")
def admin_types_create_alias(
    request: Request, name: str = Form(""), db: Session = Depends(get_db)
):
    return admin_types_create(request, name, db)


@router.post("/admin/types/update")
def admin_types_update(
    request: Request,
    id: int = Form(...),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    md = MasterDataService(db)
    name_v = name.strip()
    if not name_v:
        return _render_types(
            request, db, field_errors={"name": "Name is required."}, name_value=name, status_code=400
        )
    try:
        md.update_type(id, name_v, DEFAULT_USER)
    except DuplicateError as exc:
        return _render_types(
            request, db, field_errors={"name": str(exc)}, name_value=name, status_code=400
        )
    except NotFoundError as exc:
        return _render_types(request, db, error_message=str(exc), status_code=404)
    return _render_types(request, db, success_message=f"Type updated to '{name_v}'.")


@router.post("/admin/types/edit")
def admin_types_edit(
    request: Request, id: int = Form(...), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    types = md.list_types(include_inactive=True)
    current = next((t for t in types if t.type_id == id), None)
    name_value = current.name if current else ""
    return _render_types(request, db, name_value=name_value)


@router.post("/admin/types/deactivate")
def admin_types_deactivate(
    request: Request, id: int = Form(...), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    try:
        warning = md.soft_delete_type(id, DEFAULT_USER)
    except NotFoundError as exc:
        return _render_types(request, db, error_message=str(exc), status_code=404)
    warning_message = ""
    if warning.active_instrument_count > 0:
        warning_message = f"{warning.active_instrument_count} active instrument(s) reference this type."
    return _render_types(
        request, db, success_message="Type deactivated.", warning_message=warning_message
    )


@router.post("/admin/types/delete")
def admin_types_delete(
    request: Request, id: int = Form(...), db: Session = Depends(get_db)
):
    return admin_types_deactivate(request, id, db)


# ---------------------------------------------------------------------------
# Admin: Purposes
# ---------------------------------------------------------------------------

def _render_purposes(
    request: Request,
    db: Session,
    success_message: str = "",
    error_message: str = "",
    field_errors: Optional[dict] = None,
    purpose_value: Optional[dict] = None,
    status_code: int = 200,
):
    md = MasterDataService(db)
    response = templates.TemplateResponse(
        request,
        "admin-purposes.html",
        {
            "purposes": md.list_purposes(include_inactive=True),
            "success_message": success_message,
            "error_message": error_message,
            "field_errors": field_errors or {"name": ""},
            "purpose": purpose_value or {"purpose_id": "", "name": ""},
        },
    )
    response.status_code = status_code
    return response


@router.get("/admin/purposes")
def admin_purposes_get(request: Request, db: Session = Depends(get_db)):
    return _render_purposes(request, db)


@router.post("/admin/purposes")
def admin_purposes_save(
    request: Request,
    purpose_id: str = Form(""),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    md = MasterDataService(db)
    name_v = name.strip()
    if not name_v:
        return _render_purposes(
            request,
            db,
            field_errors={"name": "Name is required."},
            purpose_value={"purpose_id": purpose_id, "name": name},
            status_code=400,
        )
    try:
        if purpose_id:
            md.update_purpose(int(purpose_id), name_v, DEFAULT_USER)
            msg = f"Purpose updated to '{name_v}'."
        else:
            md.create_purpose(name_v, DEFAULT_USER)
            msg = f"Purpose '{name_v}' created."
    except DuplicateError as exc:
        return _render_purposes(
            request,
            db,
            field_errors={"name": str(exc)},
            purpose_value={"purpose_id": purpose_id, "name": name},
            status_code=400,
        )
    except NotFoundError as exc:
        return _render_purposes(request, db, error_message=str(exc), status_code=404)
    return _render_purposes(request, db, success_message=msg)


@router.post("/admin/purposes/edit")
def admin_purposes_edit(
    request: Request, purpose_id: int = Form(...), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    purposes = md.list_purposes(include_inactive=True)
    current = next((p for p in purposes if p.reservation_purpose_id == purpose_id), None)
    purpose_value = (
        {"purpose_id": str(purpose_id), "name": current.name} if current else {"purpose_id": "", "name": ""}
    )
    return _render_purposes(request, db, purpose_value=purpose_value)


@router.post("/admin/purposes/deactivate")
def admin_purposes_deactivate(
    request: Request, purpose_id: int = Form(...), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    try:
        warning = md.soft_delete_purpose(purpose_id, DEFAULT_USER)
    except NotFoundError as exc:
        return _render_purposes(request, db, error_message=str(exc), status_code=404)
    msg = "Purpose deactivated."
    if warning.active_reservation_count > 0:
        msg = f"Purpose deactivated. {warning.active_reservation_count} active reservation(s) reference this purpose."
    return _render_purposes(request, db, success_message=msg)


@router.post("/admin/purposes/restore")
def admin_purposes_restore(
    request: Request, purpose_id: int = Form(...), db: Session = Depends(get_db)
):
    md = MasterDataService(db)
    try:
        md.reactivate_purpose(purpose_id, DEFAULT_USER)
    except NotFoundError as exc:
        return _render_purposes(request, db, error_message=str(exc), status_code=404)
    return _render_purposes(request, db, success_message="Purpose reactivated.")


@router.post("/admin/purposes/reactivate")
def admin_purposes_reactivate(
    request: Request, purpose_id: int = Form(...), db: Session = Depends(get_db)
):
    return admin_purposes_restore(request, purpose_id, db)


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

def _parse_datetime_local(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@router.get("/reservations/new")
def reservations_new_get(request: Request, db: Session = Depends(get_db)):
    inst_service = InstrumentService(db)
    md = MasterDataService(db)
    instruments = inst_service.list_schedulable_instruments()
    purposes = md.list_purposes(include_inactive=False)

    return templates.TemplateResponse(
        request,
        "reservations-new.html",
        {
            "instruments": instruments,
            "purposes": purposes,
            "field_errors": _empty_field_errors(
                "instrument_id", "start_time", "end_time", "purpose_id", "requested_by"
            ),
            "success_message": "",
            "error_message": "",
            "instrument_id": "",
            "start_time": "",
            "end_time": "",
            "purpose_id": "",
            "requested_by": "",
            "can_be_overridden": False,
        },
    )


@router.post("/reservations/new")
def reservations_new_post(
    request: Request,
    instrument_id: str = Form(""),
    start_time: str = Form(""),
    end_time: str = Form(""),
    purpose_id: str = Form(""),
    requested_by: str = Form(""),
    can_be_overridden: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    inst_service = InstrumentService(db)
    md = MasterDataService(db)

    field_errors: dict = _empty_field_errors(
        "instrument_id", "start_time", "end_time", "purpose_id", "requested_by"
    )

    can_override_v = _parse_bool(can_be_overridden)
    requested_by_v = requested_by.strip()[:120]

    if len(requested_by) > 120:
        field_errors["requested_by"] = "Requested by must be at most 120 characters."

    instrument_id_i = None
    if not instrument_id:
        field_errors["instrument_id"] = "Instrument is required."
    else:
        try:
            instrument_id_i = int(instrument_id)
        except ValueError:
            field_errors["instrument_id"] = "Invalid instrument."

    purpose_id_i = None
    if not purpose_id:
        field_errors["purpose_id"] = "Purpose is required."
    else:
        try:
            purpose_id_i = int(purpose_id)
        except ValueError:
            field_errors["purpose_id"] = "Invalid purpose."

    start_dt = _parse_datetime_local(start_time)
    end_dt = _parse_datetime_local(end_time)

    if not start_dt:
        field_errors["start_time"] = "Start time is required."
    elif start_dt.minute not in (0, 30):
        field_errors["start_time"] = "Start time must be on a 30-minute boundary."

    if not end_dt:
        field_errors["end_time"] = "End time is required."
    elif end_dt.minute not in (0, 30):
        field_errors["end_time"] = "End time must be on a 30-minute boundary."

    if start_dt and end_dt and end_dt <= start_dt:
        field_errors["end_time"] = "End time must be after the start time."

    def _render_error(status_code: int = 400):
        instruments = inst_service.list_schedulable_instruments()
        purposes = md.list_purposes(include_inactive=False)
        response = templates.TemplateResponse(
            request,
            "reservations-new.html",
            {
                "instruments": instruments,
                "purposes": purposes,
                "field_errors": field_errors,
                "success_message": "",
                "error_message": "",
                "instrument_id": instrument_id,
                "start_time": start_time,
                "end_time": end_time,
                "purpose_id": purpose_id,
                "requested_by": requested_by,
                "can_be_overridden": can_override_v,
            },
        )
        response.status_code = status_code
        return response

    if any(v for v in field_errors.values()):
        return _render_error(400)

    actor = requested_by_v if requested_by_v else "Unknown"

    try:
        reservation_service = ReservationService(db)
        data = ReservationCreateData(
            instrument_id=instrument_id_i,
            start_time=start_dt,
            end_time=end_dt,
            purpose_id=purpose_id_i,
            requested_by=actor,
            can_be_overridden=can_override_v,
        )
        result = reservation_service.create_reservation(data)
    except InvalidStatusError as exc:
        field_errors["instrument_id"] = str(exc)
        return _render_error(400)
    except ConflictError as exc:
        field_errors["start_time"] = str(exc)
        return _render_error(400)
    except ValidationError as exc:
        field_errors["end_time"] = str(exc)
        return _render_error(400)
    except NotFoundError as exc:
        field_errors["instrument_id"] = str(exc)
        return _render_error(404)

    if result.overridden_reservation_ids:
        ids_text = ", ".join(str(i) for i in result.overridden_reservation_ids)
        success_message = (
            "Reservation created successfully. This reservation replaced the "
            f"following: {ids_text}."
        )
    else:
        success_message = "Reservation created successfully."

    instruments = inst_service.list_schedulable_instruments()
    purposes = md.list_purposes(include_inactive=False)
    return templates.TemplateResponse(
        request,
        "reservations-new.html",
        {
            "instruments": instruments,
            "purposes": purposes,
            "field_errors": _empty_field_errors(
                "instrument_id", "start_time", "end_time", "purpose_id", "requested_by"
            ),
            "success_message": success_message,
            "error_message": "",
            "instrument_id": "",
            "start_time": "",
            "end_time": "",
            "purpose_id": "",
            "requested_by": "",
            "can_be_overridden": False,
        },
    )


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/audit")
def audit_get(request: Request, db: Session = Depends(get_db)):
    service = AuditService(db)
    entries = service.list_entries()
    entries_sorted = sorted(entries, key=lambda e: e.timestamp, reverse=True)
    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "audit_entries": entries_sorted,
            "success_message": "",
            "error_message": "",
        },
    )
