"""
Server-rendered web UI routes for the Instrument Scheduler application.

All eleven approved pages are served here. GET routes render the
already-approved Jinja2 templates (never modified by this module) with
real data pulled in-process from the backend services. POST routes
validate form data and call the corresponding service methods.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.contracts import (
    DuplicateMasterDataError,
    InstrumentCreateDTO,
    InstrumentFilterDTO,
    InstrumentUpdateDTO,
    InvalidInstrumentStatusError,
    NotFoundError,
    ReservationConflictError,
    ReservationCreateDTO,
    TimeBoundaryError,
)
from app.models import AuditActionType, AuditEntityType, InstrumentStatus, get_db
from app.services.audit_log import AuditLogService
from app.services.instrument import InstrumentService
from app.services.master_data import MasterDataService
from app.services.reservation import ReservationService
from app.services.scheduler import SchedulerService

router = APIRouter()

templates = Jinja2Templates(directory="app/web/templates")

DEFAULT_USER = "Hamelin, Alex"

ACTIVE_STATUSES = {InstrumentStatus.ACTIVE.value if hasattr(InstrumentStatus, "ACTIVE") else "Active"}


def _requested_by(value: Optional[str]) -> str:
    trimmed = (value or "").strip()
    return trimmed if trimmed else "Unknown"


def _status_value(status) -> str:
    return getattr(status, "value", status)


def _is_schedulable(status) -> bool:
    val = _status_value(status)
    return str(val) not in ("Decommissioned", "Under Maintenance")


# ---------------------------------------------------------------------------
# Scheduler / Home
# ---------------------------------------------------------------------------

def _build_timeline_context(request: Request, date: Optional[str], view: Optional[str], db: Session) -> dict:
    view_value = (view or "day").lower()
    if view_value not in ("day", "week"):
        view_value = "day"

    if date:
        try:
            selected_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            selected_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        selected_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    scheduler_service = SchedulerService(db)
    timeline = scheduler_service.get_timeline(selected_date, view_value)

    instruments = [
        i for i in timeline.instruments if i.is_active and _is_schedulable(i.status)
    ]
    instruments.sort(key=lambda i: (i.name or "", i.nickname or ""))

    resources = []
    for instr in instruments:
        resources.append(
            {
                "id": instr.instrument_id,
                "label": f"{instr.name} ({instr.nickname}) - {instr.asset_id or ''}",
                "color": instr.color or "#3B5FE0",
            }
        )

    reservations = [r for r in timeline.reservations if r.is_active]
    events = []
    for res in reservations:
        instrument_color = "#3B5FE0"
        for instr in instruments:
            if instr.instrument_id == res.instrument_id:
                instrument_color = instr.color or "#3B5FE0"
                break
        events.append(
            {
                "id": res.reservation_id,
                "resource_id": res.instrument_id,
                "instrument_id": res.instrument_id,
                "title": res.purpose_name,
                "start": res.start_datetime.isoformat(),
                "end": res.end_datetime.isoformat(),
                "color": instrument_color,
            }
        )

    if view_value == "week":
        start_of_range = selected_date
        end_of_range = selected_date + timedelta(days=7)
        range_label = f"{start_of_range.strftime('%b %-d')} \u2013 {(end_of_range - timedelta(days=1)).strftime('%-d, %Y')}"
    else:
        start_of_range = selected_date
        end_of_range = selected_date + timedelta(days=1)
        range_label = start_of_range.strftime("%b %-d, %Y")

    time_headers = []
    cursor = start_of_range
    while cursor < end_of_range:
        time_headers.append(cursor.strftime("%Y-%m-%dT%H:%M:%SZ"))
        cursor += timedelta(hours=3)

    days = []
    day_cursor = start_of_range
    while day_cursor < end_of_range:
        days.append(day_cursor.strftime("%Y-%m-%d"))
        day_cursor += timedelta(days=1)

    return {
        "current_view": view_value,
        "date_range_label": range_label,
        "range_label": range_label,
        "days": days,
        "resources": resources,
        "events": events,
        "active": resources,
        "selected_date": selected_date.strftime("%Y-%m-%d"),
        "time_headers": time_headers,
    }


@router.get("/scheduler")
async def scheduler_page(
    request: Request,
    date: Optional[str] = None,
    view: Optional[str] = None,
    db: Session = Depends(get_db),
):
    ctx = _build_timeline_context(request, date, view, db)
    context = {
        "current_view": ctx["current_view"],
        "date_range_label": ctx["date_range_label"],
        "days": ctx["days"],
        "error_message": "",
        "resources": ctx["resources"],
        "selected_date": ctx["selected_date"],
        "success_message": "",
        "time_headers": ctx["time_headers"],
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "scheduler.html", context)


@router.get("/")
async def index_page(
    request: Request,
    date: Optional[str] = None,
    view: Optional[str] = None,
    db: Session = Depends(get_db),
):
    ctx = _build_timeline_context(request, date, view, db)
    context = {
        "active": ctx["resources"],
        "error_message": "",
        "events": ctx["events"],
        "range_label": ctx["range_label"],
        "selected_date": ctx["selected_date"],
        "success_message": "",
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "index.html", context)


# ---------------------------------------------------------------------------
# Instruments listing / favorites
# ---------------------------------------------------------------------------

def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _list_instruments_filtered(
    db: Session,
    nickname: Optional[str],
    location: Optional[str],
    vendor: Optional[str],
    type_: Optional[str],
    favorites: Optional[str],
) -> list:
    filters = InstrumentFilterDTO(
        nickname=nickname or None,
        location_id=_parse_int(location),
        vendor_id=_parse_int(vendor),
        type_id=_parse_int(type_),
        favorites_only=bool(favorites),
    )
    service = InstrumentService(db)
    instruments = service.list_instruments(filters)
    instruments = [i for i in instruments if i.is_active]
    instruments.sort(key=lambda i: (i.name or "", i.nickname or ""))
    return instruments


@router.get("/instruments")
async def instruments_page(
    request: Request,
    nickname: Optional[str] = None,
    location: Optional[str] = None,
    vendor: Optional[str] = None,
    type: Optional[str] = None,
    favorites: Optional[str] = None,
    db: Session = Depends(get_db),
):
    instruments = _list_instruments_filtered(db, nickname, location, vendor, type, favorites)
    master = MasterDataService(db)
    context = {
        "instruments": instruments,
        "locations": master.list_locations(include_inactive=False),
        "vendors": master.list_vendors(include_inactive=False),
        "types": master.list_types(include_inactive=False),
        "filters": {
            "nickname": nickname or "",
            "location": location or "",
            "vendor": vendor or "",
            "type": type or "",
            "favorites": bool(favorites),
        },
        "success_message": "",
        "error_message": "",
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "instruments.html", context)


@router.get("/instruments/favorites")
async def instruments_favorites_page(
    request: Request,
    nickname: Optional[str] = None,
    location: Optional[str] = None,
    vendor: Optional[str] = None,
    type: Optional[str] = None,
    favorites: Optional[str] = None,
    db: Session = Depends(get_db),
):
    instruments = _list_instruments_filtered(db, nickname, location, vendor, type, favorites)
    instruments = [i for i in instruments if i.is_favorite]
    master = MasterDataService(db)
    context = {
        "instruments": instruments,
        "locations": master.list_locations(include_inactive=False),
        "vendors": master.list_vendors(include_inactive=False),
        "types": master.list_types(include_inactive=False),
        "filters": {
            "nickname": nickname or "",
            "location": location or "",
            "vendor": vendor or "",
            "type": type or "",
            "favorites": bool(favorites),
        },
        "success_message": "",
        "error_message": "",
    }
    return templates.TemplateResponse(request, "instruments-favorites.html", context)


@router.post("/instruments/toggle-favorite")
async def toggle_favorite(
    request: Request,
    instrument_id: int = Form(...),
    db: Session = Depends(get_db),
):
    service = InstrumentService(db)
    error_message = ""
    try:
        new_state = service.toggle_favorite(instrument_id)
        audit = AuditLogService(db)
        audit.log(
            actor=DEFAULT_USER,
            action_type=AuditActionType.UPDATE if hasattr(AuditActionType, "UPDATE") else list(AuditActionType)[0],
            entity_type=AuditEntityType.INSTRUMENT if hasattr(AuditEntityType, "INSTRUMENT") else list(AuditEntityType)[0],
            entity_id=instrument_id,
            description=f"IsFavorite changed to {new_state}",
        )
    except NotFoundError as exc:
        error_message = str(exc)

    instruments = _list_instruments_filtered(db, None, None, None, None, None)
    master = MasterDataService(db)
    context = {
        "instruments": instruments,
        "locations": master.list_locations(include_inactive=False),
        "vendors": master.list_vendors(include_inactive=False),
        "types": master.list_types(include_inactive=False),
        "filters": {"nickname": "", "location": "", "vendor": "", "type": "", "favorites": False},
        "success_message": "" if error_message else "Favorite updated.",
        "error_message": error_message,
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "instruments.html", context)


# ---------------------------------------------------------------------------
# Instrument create / edit form
# ---------------------------------------------------------------------------

def _instrument_form_context(
    request: Request,
    db: Session,
    instrument=None,
    field_errors: Optional[dict] = None,
    error_message: str = "",
    success_message: str = "",
):
    master = MasterDataService(db)
    return {
        "error_message": error_message,
        "field_errors": field_errors or {},
        "instrument": instrument,
        "locations": master.list_locations(include_inactive=False),
        "success_message": success_message,
        "types": master.list_types(include_inactive=False),
        "user": DEFAULT_USER,
        "vendors": master.list_vendors(include_inactive=False),
    }


@router.get("/instruments/form")
async def instrument_form_page(
    request: Request,
    instrument_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    instrument = None
    if instrument_id:
        try:
            service = InstrumentService(db)
            instrument = service.get_instrument(instrument_id)
        except NotFoundError:
            instrument = None
    context = _instrument_form_context(request, db, instrument=instrument)
    return templates.TemplateResponse(request, "instruments-form.html", context)


@router.post("/instruments/form")
async def instrument_form_submit(
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
    field_errors: dict = {}

    if not name.strip():
        field_errors["name"] = "Name is required."
    if not nickname.strip():
        field_errors["nickname"] = "Nickname is required."

    location_id = _parse_int(location)
    vendor_id = _parse_int(vendor)
    type_id = _parse_int(type)

    if location_id is None:
        field_errors["location"] = "Location is required."
    if vendor_id is None:
        field_errors["vendor"] = "Vendor is required."
    if type_id is None:
        field_errors["type"] = "Type is required."

    is_active_bool = is_active is not None

    # Build a partial instrument-like echo object for re-render on error
    echo_instrument = {
        "instrument_id": instrument_id,
        "name": name,
        "nickname": nickname,
        "asset_id": asset_id,
        "location_id": location_id,
        "vendor_id": vendor_id,
        "type_id": type_id,
        "color": color,
        "is_active": is_active_bool,
        "status": "Active",
    }

    if field_errors:
        context = _instrument_form_context(
            request, db, instrument=echo_instrument, field_errors=field_errors,
            error_message="Please correct the errors below.",
        )
        return templates.TemplateResponse(request, "instruments-form.html", context, status_code=422)

    service = InstrumentService(db)
    audit = AuditLogService(db)
    action_update = getattr(AuditActionType, "UPDATE", list(AuditActionType)[0])
    action_create = getattr(AuditActionType, "CREATE", list(AuditActionType)[0])
    entity_instrument = getattr(AuditEntityType, "INSTRUMENT", list(AuditEntityType)[0])

    try:
        if instrument_id:
            iid = int(instrument_id)
            before = service.get_instrument(iid)
            update_dto = InstrumentUpdateDTO(
                name=name.strip(),
                nickname=nickname.strip(),
                location_id=location_id,
                vendor_id=vendor_id,
                type_id=type_id,
                asset_id=asset_id.strip() or None,
                color=color or None,
                status=None,
                is_active=is_active_bool,
            )
            updated = service.update(iid, update_dto)
            changes = []
            if before.name != updated.name:
                changes.append(f"name: '{before.name}' -> '{updated.name}'")
            if before.nickname != updated.nickname:
                changes.append(f"nickname: '{before.nickname}' -> '{updated.nickname}'")
            if before.location_id != updated.location_id:
                changes.append(f"location_id: '{before.location_id}' -> '{updated.location_id}'")
            if before.vendor_id != updated.vendor_id:
                changes.append(f"vendor_id: '{before.vendor_id}' -> '{updated.vendor_id}'")
            if before.type_id != updated.type_id:
                changes.append(f"type_id: '{before.type_id}' -> '{updated.type_id}'")
            if before.asset_id != updated.asset_id:
                changes.append(f"asset_id: '{before.asset_id}' -> '{updated.asset_id}'")
            if before.color != updated.color:
                changes.append(f"color: '{before.color}' -> '{updated.color}'")
            description = "Updated fields: " + "; ".join(changes) if changes else "No field changes"
            audit.log(
                actor=DEFAULT_USER,
                action_type=action_update,
                entity_type=entity_instrument,
                entity_id=updated.instrument_id,
                description=description,
            )
            success_message = "Instrument updated successfully."
            instrument_result = updated
        else:
            create_dto = InstrumentCreateDTO(
                name=name.strip(),
                nickname=nickname.strip(),
                location_id=location_id,
                vendor_id=vendor_id,
                type_id=type_id,
                asset_id=asset_id.strip() or None,
                color=color or None,
                status="Active",
                is_active=is_active_bool if is_active is not None else True,
            )
            created = service.create(create_dto)
            audit.log(
                actor=DEFAULT_USER,
                action_type=action_create,
                entity_type=entity_instrument,
                entity_id=created.instrument_id,
                description=f"Created instrument '{created.name}'",
            )
            success_message = "Instrument created successfully."
            instrument_result = created
    except DuplicateMasterDataError as exc:
        context = _instrument_form_context(
            request, db, instrument=echo_instrument, field_errors={"name": str(exc)},
            error_message=str(exc),
        )
        return templates.TemplateResponse(request, "instruments-form.html", context, status_code=422)
    except NotFoundError as exc:
        context = _instrument_form_context(
            request, db, instrument=echo_instrument, error_message=str(exc),
        )
        return templates.TemplateResponse(request, "instruments-form.html", context, status_code=422)

    context = _instrument_form_context(
        request, db, instrument=instrument_result, success_message=success_message,
    )
    return templates.TemplateResponse(request, "instruments-form.html", context)


# ---------------------------------------------------------------------------
# Admin: Locations
# ---------------------------------------------------------------------------

@router.get("/admin/locations")
async def admin_locations_page(request: Request, db: Session = Depends(get_db)):
    master = MasterDataService(db)
    locations = master.list_locations(include_inactive=True)
    context = {
        "locations": locations,
        "success_message": "",
        "error_message": "",
        "warning_message": "",
        "field_errors": {},
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "admin-locations.html", context)


@router.post("/admin/locations/create")
async def admin_locations_create(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error_message = ""
    field_errors: dict = {}
    try:
        master.create_location(name.strip())
        success_message = f"Location '{name.strip()}' created."
    except DuplicateMasterDataError as exc:
        field_errors["name"] = str(exc)
        error_message = str(exc)
        success_message = ""
    locations = master.list_locations(include_inactive=True)
    context = {
        "locations": locations,
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": "",
        "field_errors": field_errors,
        "user": DEFAULT_USER,
    }
    status_code = 422 if field_errors else 200
    return templates.TemplateResponse(request, "admin-locations.html", context, status_code=status_code)


@router.post("/admin/locations/update")
async def admin_locations_update(
    request: Request,
    id: int = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error_message = ""
    field_errors: dict = {}
    success_message = ""
    try:
        master.update_location(id, name.strip())
        success_message = "Location updated."
    except DuplicateMasterDataError as exc:
        field_errors["name"] = str(exc)
        error_message = str(exc)
    except NotFoundError as exc:
        error_message = str(exc)
    locations = master.list_locations(include_inactive=True)
    context = {
        "locations": locations,
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": "",
        "field_errors": field_errors,
        "user": DEFAULT_USER,
    }
    status_code = 422 if field_errors else 200
    return templates.TemplateResponse(request, "admin-locations.html", context, status_code=status_code)


@router.post("/admin/locations/deactivate")
async def admin_locations_deactivate(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    warning_message = ""
    error_message = ""
    try:
        result = master.deactivate_location(id)
        warning_message = result.message
    except NotFoundError as exc:
        error_message = str(exc)
    locations = master.list_locations(include_inactive=True)
    context = {
        "locations": locations,
        "success_message": "",
        "error_message": error_message,
        "warning_message": warning_message,
        "field_errors": {},
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "admin-locations.html", context)


@router.post("/admin/locations/reactivate")
async def admin_locations_reactivate(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error_message = ""
    success_message = ""
    try:
        master.reactivate_location(id)
        success_message = "Location reactivated."
    except NotFoundError as exc:
        error_message = str(exc)
    locations = master.list_locations(include_inactive=True)
    context = {
        "locations": locations,
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": "",
        "field_errors": {},
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "admin-locations.html", context)


# Legacy path-parameterized delete/reactivate routes referenced by approved markup
@router.post("/admin/locations/{location_id}/delete")
async def admin_locations_delete_legacy(
    request: Request,
    location_id: int,
    id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    warning_message = ""
    error_message = ""
    target_id = id or location_id
    try:
        result = master.deactivate_location(target_id)
        warning_message = result.message
    except NotFoundError as exc:
        error_message = str(exc)
    locations = master.list_locations(include_inactive=True)
    context = {
        "locations": locations,
        "success_message": "",
        "error_message": error_message,
        "warning_message": warning_message,
        "field_errors": {},
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "admin-locations.html", context)


@router.post("/admin/locations/{location_id}/reactivate")
async def admin_locations_reactivate_legacy(
    request: Request,
    location_id: int,
    id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error_message = ""
    success_message = ""
    target_id = id or location_id
    try:
        master.reactivate_location(target_id)
        success_message = "Location reactivated."
    except NotFoundError as exc:
        error_message = str(exc)
    locations = master.list_locations(include_inactive=True)
    context = {
        "locations": locations,
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": "",
        "field_errors": {},
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "admin-locations.html", context)


# ---------------------------------------------------------------------------
# Admin: Vendors
# ---------------------------------------------------------------------------

@router.get("/admin/vendors")
async def admin_vendors_page(request: Request, db: Session = Depends(get_db)):
    master = MasterDataService(db)
    context = {
        "vendors": master.list_vendors(include_inactive=True),
        "success_message": "",
        "error_message": "",
        "warning_message": "",
    }
    return templates.TemplateResponse(request, "admin-vendors.html", context)


@router.post("/admin/vendors/save")
async def admin_vendors_save(
    request: Request,
    name: str = Form(...),
    isActive: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error_message = ""
    success_message = ""
    warning_message = ""
    try:
        existing = {v.name.strip().lower(): v for v in master.list_vendors(include_inactive=True)}
        match = existing.get(name.strip().lower())
        if match:
            master.update_vendor(match.vendor_id, name.strip())
            if not isActive and match.is_active:
                result = master.deactivate_vendor(match.vendor_id)
                warning_message = result.message
            success_message = "Vendor updated."
        else:
            master.create_vendor(name.strip())
            success_message = "Vendor created."
    except DuplicateMasterDataError as exc:
        error_message = str(exc)
    except NotFoundError as exc:
        error_message = str(exc)
    context = {
        "vendors": master.list_vendors(include_inactive=True),
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": warning_message,
    }
    status_code = 422 if error_message else 200
    return templates.TemplateResponse(request, "admin-vendors.html", context, status_code=status_code)


# ---------------------------------------------------------------------------
# Admin: Types
# ---------------------------------------------------------------------------

@router.get("/admin/types")
async def admin_types_page(request: Request, db: Session = Depends(get_db)):
    master = MasterDataService(db)
    context = {
        "types": master.list_types(include_inactive=True),
        "success_message": "",
        "error_message": "",
        "warning_message": "",
        "field_errors": {},
        "edit_type": None,
    }
    return templates.TemplateResponse(request, "admin-types.html", context)


@router.post("/admin/types/create")
async def admin_types_create(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error_message = ""
    field_errors: dict = {}
    success_message = ""
    try:
        master.create_type(name.strip())
        success_message = f"Type '{name.strip()}' created."
    except DuplicateMasterDataError as exc:
        field_errors["name"] = str(exc)
        error_message = str(exc)
    context = {
        "types": master.list_types(include_inactive=True),
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": "",
        "field_errors": field_errors,
        "edit_type": None,
    }
    status_code = 422 if field_errors else 200
    return templates.TemplateResponse(request, "admin-types.html", context, status_code=status_code)


@router.post("/admin/types/update")
async def admin_types_update(
    request: Request,
    id: int = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error_message = ""
    field_errors: dict = {}
    success_message = ""
    try:
        master.update_type(id, name.strip())
        success_message = "Type updated."
    except DuplicateMasterDataError as exc:
        field_errors["name"] = str(exc)
        error_message = str(exc)
    except NotFoundError as exc:
        error_message = str(exc)
    context = {
        "types": master.list_types(include_inactive=True),
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": "",
        "field_errors": field_errors,
        "edit_type": None,
    }
    status_code = 422 if field_errors else 200
    return templates.TemplateResponse(request, "admin-types.html", context, status_code=status_code)


@router.post("/admin/types/edit")
async def admin_types_edit(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    types = master.list_types(include_inactive=True)
    edit_type = next((t for t in types if t.type_id == id), None)
    context = {
        "types": types,
        "success_message": "",
        "error_message": "",
        "warning_message": "",
        "field_errors": {},
        "edit_type": edit_type,
    }
    return templates.TemplateResponse(request, "admin-types.html", context)


@router.post("/admin/types/deactivate")
async def admin_types_deactivate(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    warning_message = ""
    error_message = ""
    try:
        result = master.deactivate_type(id)
        warning_message = result.message
    except NotFoundError as exc:
        error_message = str(exc)
    context = {
        "types": master.list_types(include_inactive=True),
        "success_message": "",
        "error_message": error_message,
        "warning_message": warning_message,
        "field_errors": {},
        "edit_type": None,
    }
    return templates.TemplateResponse(request, "admin-types.html", context)


# ---------------------------------------------------------------------------
# Admin: Reservation Purposes
# ---------------------------------------------------------------------------

@router.get("/admin/purposes")
async def admin_purposes_page(request: Request, db: Session = Depends(get_db)):
    master = MasterDataService(db)
    context = {
        "error": "",
        "field_errors": {},
        "purpose": None,
        "purposes": master.list_purposes(include_inactive=True),
        "success_message": "",
    }
    return templates.TemplateResponse(request, "admin-purposes.html", context)


@router.post("/admin/purposes/create")
async def admin_purposes_create(
    request: Request,
    purpose_id: str = Form(""),
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error = ""
    field_errors: dict = {}
    success_message = ""
    try:
        if purpose_id:
            master.update_purpose(int(purpose_id), name.strip())
            success_message = "Purpose updated."
        else:
            master.create_purpose(name.strip())
            success_message = "Purpose created."
    except DuplicateMasterDataError as exc:
        field_errors["name"] = str(exc)
        error = str(exc)
    except NotFoundError as exc:
        error = str(exc)
    context = {
        "error": error,
        "field_errors": field_errors,
        "purpose": {"name": name} if field_errors else None,
        "purposes": master.list_purposes(include_inactive=True),
        "success_message": success_message,
    }
    status_code = 422 if field_errors else 200
    return templates.TemplateResponse(request, "admin-purposes.html", context, status_code=status_code)


@router.post("/admin/purposes/edit")
async def admin_purposes_edit(
    request: Request,
    purpose_id: int = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    purposes = master.list_purposes(include_inactive=True)
    purpose = next((p for p in purposes if p.reservation_purpose_id == purpose_id), None)
    context = {
        "error": "",
        "field_errors": {},
        "purpose": purpose,
        "purposes": purposes,
        "success_message": "",
    }
    return templates.TemplateResponse(request, "admin-purposes.html", context)


@router.post("/admin/purposes/deactivate")
async def admin_purposes_deactivate(
    request: Request,
    purpose_id: int = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error = ""
    success_message = ""
    try:
        result = master.deactivate_purpose(purpose_id)
        success_message = result.message
    except NotFoundError as exc:
        error = str(exc)
    context = {
        "error": error,
        "field_errors": {},
        "purpose": None,
        "purposes": master.list_purposes(include_inactive=True),
        "success_message": success_message,
    }
    return templates.TemplateResponse(request, "admin-purposes.html", context)


@router.post("/admin/purposes/restore")
async def admin_purposes_restore(
    request: Request,
    purpose_id: int = Form(...),
    db: Session = Depends(get_db),
):
    master = MasterDataService(db)
    error = ""
    success_message = ""
    try:
        master.reactivate_purpose(purpose_id)
        success_message = "Purpose reactivated."
    except NotFoundError as exc:
        error = str(exc)
    context = {
        "error": error,
        "field_errors": {},
        "purpose": None,
        "purposes": master.list_purposes(include_inactive=True),
        "success_message": success_message,
    }
    return templates.TemplateResponse(request, "admin-purposes.html", context)


@router.post("/admin/purposes/reactivate")
async def admin_purposes_reactivate(
    request: Request,
    purpose_id: int = Form(...),
    db: Session = Depends(get_db),
):
    return await admin_purposes_restore(request, purpose_id, db)


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

@router.get("/reservations/new")
async def reservations_new_page(request: Request, db: Session = Depends(get_db)):
    instrument_service = InstrumentService(db)
    master = MasterDataService(db)
    all_instruments = instrument_service.list_instruments(InstrumentFilterDTO())
    schedulable = [
        i for i in all_instruments if i.is_active and _is_schedulable(i.status)
    ]
    schedulable.sort(key=lambda i: (i.name or "", i.nickname or ""))
    context = {
        "instruments": schedulable,
        "purposes": master.list_purposes(include_inactive=False),
        "success_message": "",
        "error_message": "",
        "field_errors": {},
        "instrument_id": "",
        "start_time": "",
        "end_time": "",
        "purpose_id": "",
        "requested_by": "",
        "can_be_overridden": False,
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "reservations-new.html", context)


def _parse_datetime_local(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        try:
            dt = datetime.fromisoformat(value)
        except ValueError:
            return None
    return dt.replace(tzinfo=timezone.utc)


@router.post("/reservations/new")
async def reservations_new_submit(
    request: Request,
    instrument_id: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    purpose_id: str = Form(...),
    requested_by: str = Form(""),
    can_be_overridden: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    instrument_service = InstrumentService(db)
    master = MasterDataService(db)

    def render_form(error_message: str, field_errors: dict, status_code: int = 422):
        all_instruments = instrument_service.list_instruments(InstrumentFilterDTO())
        schedulable = [
            i for i in all_instruments if i.is_active and _is_schedulable(i.status)
        ]
        schedulable.sort(key=lambda i: (i.name or "", i.nickname or ""))
        context = {
            "instruments": schedulable,
            "purposes": master.list_purposes(include_inactive=False),
            "success_message": "",
            "error_message": error_message,
            "field_errors": field_errors,
            "instrument_id": instrument_id,
            "start_time": start_time,
            "end_time": end_time,
            "purpose_id": purpose_id,
            "requested_by": requested_by,
            "can_be_overridden": can_be_overridden is not None,
            "user": DEFAULT_USER,
        }
        return templates.TemplateResponse(request, "reservations-new.html", context, status_code=status_code)

    field_errors: dict = {}

    if len(requested_by) > 120:
        field_errors["requested_by"] = "Requested by must be at most 120 characters."

    instrument_id_int = _parse_int(instrument_id)
    purpose_id_int = _parse_int(purpose_id)

    if instrument_id_int is None:
        field_errors["instrument_id"] = "Instrument is required."
    if purpose_id_int is None:
        field_errors["purpose_id"] = "Purpose is required."

    start_dt = _parse_datetime_local(start_time)
    end_dt = _parse_datetime_local(end_time)

    if start_dt is None:
        field_errors["start_time"] = "Start time is required."
    if end_dt is None:
        field_errors["end_time"] = "End time is required."

    if field_errors:
        return render_form("Please correct the errors below.", field_errors)

    if end_dt <= start_dt:
        return render_form("End time must be after the start time.", {"end_time": "End time must be after the start time."})

    if start_dt.minute % 30 != 0 or end_dt.minute % 30 != 0:
        return render_form(
            "Times must fall on a 30-minute boundary.",
            {"start_time": "Times must fall on a 30-minute boundary."},
        )

    try:
        instrument = instrument_service.get_instrument(instrument_id_int)
    except NotFoundError as exc:
        return render_form(str(exc), {"instrument_id": str(exc)})

    if not _is_schedulable(instrument.status):
        message = f"Instrument {instrument.name} is not available for scheduling (status: {_status_value(instrument.status)})."
        return render_form(message, {"instrument_id": message})

    actor = _requested_by(requested_by)

    reservation_service = ReservationService(db)
    audit = AuditLogService(db)
    action_create = getattr(AuditActionType, "CREATE", list(AuditActionType)[0])
    entity_reservation = getattr(AuditEntityType, "RESERVATION", list(AuditEntityType)[0])

    create_dto = ReservationCreateDTO(
        instrument_id=instrument_id_int,
        start_datetime=start_dt,
        end_datetime=end_dt,
        reservation_purpose_id=purpose_id_int,
        requested_by=actor,
        can_be_overridden=can_be_overridden is not None,
    )

    try:
        result = reservation_service.create(create_dto)
    except ReservationConflictError as exc:
        return render_form(str(exc), {"start_time": str(exc)})
    except TimeBoundaryError as exc:
        return render_form(str(exc), {"start_time": str(exc)})
    except InvalidInstrumentStatusError as exc:
        return render_form(str(exc), {"instrument_id": str(exc)})
    except NotFoundError as exc:
        return render_form(str(exc), {"purpose_id": str(exc)})

    audit.log(
        actor=actor,
        action_type=action_create,
        entity_type=entity_reservation,
        entity_id=result.reservation.reservation_id,
        description=f"Created reservation for instrument {instrument.name} from {start_dt.isoformat()} to {end_dt.isoformat()}",
    )

    if result.overridden_ids:
        for overridden_id in result.overridden_ids:
            audit.log(
                actor=actor,
                action_type=getattr(AuditActionType, "DELETE", list(AuditActionType)[0]),
                entity_type=entity_reservation,
                entity_id=overridden_id,
                description=f"Reservation {overridden_id} replaced by new reservation {result.reservation.reservation_id}",
            )
        ids_list = ", ".join(str(i) for i in result.overridden_ids)
        success_message = (
            "Reservation created successfully. This reservation replaced the following: "
            f"[{ids_list}]."
        )
    else:
        success_message = "Reservation created successfully."

    all_instruments = instrument_service.list_instruments(InstrumentFilterDTO())
    schedulable = [
        i for i in all_instruments if i.is_active and _is_schedulable(i.status)
    ]
    schedulable.sort(key=lambda i: (i.name or "", i.nickname or ""))
    context = {
        "instruments": schedulable,
        "purposes": master.list_purposes(include_inactive=False),
        "success_message": success_message,
        "error_message": "",
        "field_errors": {},
        "instrument_id": "",
        "start_time": "",
        "end_time": "",
        "purpose_id": "",
        "requested_by": "",
        "can_be_overridden": False,
        "user": DEFAULT_USER,
    }
    return templates.TemplateResponse(request, "reservations-new.html", context)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@router.get("/audit")
async def audit_page(request: Request, db: Session = Depends(get_db)):
    audit = AuditLogService(db)
    error_message = ""
    entries = []
    try:
        entries = audit.list_entries()
        entries = sorted(entries, key=lambda e: e.timestamp, reverse=True)
    except Exception as exc:  # defensive: never crash the page on read failure
        error_message = str(exc)
    context = {
        "audit_entries": entries,
        "error_message": error_message,
    }
    return templates.TemplateResponse(request, "audit.html", context)
