"""Server-rendered pages for the instrument scheduling application.

All routes are GET page renders (Jinja2) or POST form handlers that call the
backend services in-process via app.contracts / app.services. No React, no
build step, no self-HTTP calls.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone, date as date_cls
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.templating import Jinja2Templates
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
from app.models.database import get_db
from app.services import (
    AuditService,
    InstrumentService,
    MasterDataService,
    ReservationService,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/web/templates")

STATIC_USER = "Hamelin, Alex"
MID_BLUE = "#3b6fd6"


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_bool(value: Optional[str]) -> bool:
    if value is None:
        return False
    return str(value).lower() in ("1", "true", "on", "yes")


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_local_datetime(value: str) -> datetime:
    # value from <input type="datetime-local"> e.g. "2024-01-01T09:00"
    dt = datetime.fromisoformat(value)
    return _to_utc(dt)


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@router.get("/scheduler")
def scheduler_page(
    request: Request,
    date: Optional[str] = None,
    view: str = "week",
    db: Session = Depends(get_db),
):
    view = (view or "week").lower()
    if view not in ("day", "week"):
        view = "week"

    if date:
        try:
            selected_date = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            selected_date = datetime.now(timezone.utc).date()
    else:
        selected_date = datetime.now(timezone.utc).date()

    if view == "day":
        range_start = datetime.combine(selected_date, datetime.min.time(), tzinfo=timezone.utc)
        range_end = range_start + timedelta(days=1)
        num_days = 1
    else:
        # week starting on selected_date
        range_start = datetime.combine(selected_date, datetime.min.time(), tzinfo=timezone.utc)
        range_end = range_start + timedelta(days=7)
        num_days = 7

    instrument_service = InstrumentService(db)
    reservation_service = ReservationService(db)

    error_message = ""
    success_message = ""
    resources = []
    days = []
    time_headers = []

    try:
        instruments = instrument_service.list_schedulable()
    except Exception as exc:  # pragma: no cover - defensive
        instruments = []
        error_message = str(exc)

    instruments_sorted = sorted(instruments, key=lambda i: (i.name or "", i.nickname or ""))
    instrument_ids = [i.instrument_id for i in instruments_sorted]

    reservations_by_instrument: dict[int, list] = {i: [] for i in instrument_ids}
    if instrument_ids:
        try:
            reservations = reservation_service.list_by_instrument_and_range(
                instrument_ids, range_start, range_end
            )
        except Exception as exc:  # pragma: no cover - defensive
            reservations = []
            if not error_message:
                error_message = str(exc)
        for r in reservations:
            reservations_by_instrument.setdefault(r.instrument_id, []).append(r)

    for instrument in instruments_sorted:
        items = []
        for r in reservations_by_instrument.get(instrument.instrument_id, []):
            color = instrument.color or MID_BLUE
            items.append(
                {
                    "reservation_id": r.reservation_id,
                    "instrument_id": r.instrument_id,
                    "start_datetime": _to_utc(r.start_datetime).isoformat(),
                    "end_datetime": _to_utc(r.end_datetime).isoformat(),
                    "purpose_name": r.purpose_name,
                    "requested_by": r.requested_by,
                    "color": color,
                }
            )
        resources.append(
            {
                "instrument_id": instrument.instrument_id,
                "name": instrument.name,
                "nickname": instrument.nickname,
                "asset_id": instrument.asset_id or "",
                "label": f"{instrument.name} ({instrument.nickname}) - {instrument.asset_id or ''}",
                "color": instrument.color or MID_BLUE,
                "reservations": items,
            }
        )

    for d in range(num_days):
        day_date = (range_start + timedelta(days=d)).date()
        days.append(day_date.isoformat())

    for h in range(0, 24, 3):
        time_headers.append(f"{h:02d}:00")

    if view == "week":
        end_display = range_end - timedelta(days=1)
        if range_start.month == end_display.month:
            date_range_label = f"{range_start.strftime('%b %-d')} \u2013 {end_display.strftime('%-d, %Y')}"
        else:
            date_range_label = f"{range_start.strftime('%b %-d')} \u2013 {end_display.strftime('%b %-d, %Y')}"
    else:
        date_range_label = range_start.strftime("%b %-d, %Y")

    return templates.TemplateResponse(
        request,
        "scheduler.html",
        {
            "current_view": view,
            "date_range_label": date_range_label,
            "days": days,
            "error_message": error_message,
            "resources": resources,
            "selected_date": selected_date.isoformat(),
            "success_message": success_message,
            "time_headers": time_headers,
            "user": STATIC_USER,
        },
    )


@router.get("/")
def index_page(request: Request, db: Session = Depends(get_db)):
    today = datetime.now(timezone.utc).date()
    range_start = today
    range_end = range_start + timedelta(days=6)
    if range_start.month == range_end.month:
        range_label = f"{range_start.strftime('%b %-d')} \u2013 {range_end.strftime('%-d, %Y')}"
    else:
        range_label = f"{range_start.strftime('%b %-d')} \u2013 {range_end.strftime('%b %-d, %Y')}"
    return templates.TemplateResponse(request, "index.html", {"range_label": range_label})


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

def _instrument_context(
    db: Session,
    nickname: Optional[str],
    location: Optional[str],
    vendor: Optional[str],
    type_: Optional[str],
    favorites: Optional[str],
):
    instrument_service = InstrumentService(db)
    master_service = MasterDataService(db)

    filters = InstrumentFilterDTO(
        nickname=nickname or None,
        location_id=_parse_int(location),
        vendor_id=_parse_int(vendor),
        type_id=_parse_int(type_),
        favorites_only=_parse_bool(favorites) if favorites is not None else None,
    )
    instruments = instrument_service.list_active(filters)
    locations = master_service.list_locations(active_only=True)
    vendors = master_service.list_vendors(active_only=True)
    types = master_service.list_types(active_only=True)

    filters_ctx = {
        "nickname": nickname or "",
        "location": location or "",
        "vendor": vendor or "",
        "type": type_ or "",
        "favorites": "on" if _parse_bool(favorites) else "",
    }
    return instruments, locations, vendors, types, filters_ctx


@router.get("/instruments")
def instruments_page(
    request: Request,
    nickname: Optional[str] = None,
    location: Optional[str] = None,
    vendor: Optional[str] = None,
    type: Optional[str] = None,
    favorites: Optional[str] = None,
    db: Session = Depends(get_db),
):
    instruments, locations, vendors, types, filters_ctx = _instrument_context(
        db, nickname, location, vendor, type, favorites
    )
    return templates.TemplateResponse(
        request,
        "instruments.html",
        {
            "error_message": "",
            "filters": filters_ctx,
            "instruments": instruments,
            "locations": locations,
            "success_message": "",
            "types": types,
            "vendors": vendors,
        },
    )


@router.get("/instruments/favorites")
def instruments_favorites_page(
    request: Request,
    nickname: Optional[str] = None,
    location: Optional[str] = None,
    vendor: Optional[str] = None,
    type: Optional[str] = None,
    favorites: Optional[str] = None,
    db: Session = Depends(get_db),
):
    instruments, locations, vendors, types, filters_ctx = _instrument_context(
        db, nickname, location, vendor, type, favorites
    )
    return templates.TemplateResponse(
        request,
        "instruments.html",
        {
            "error_message": "",
            "filters": filters_ctx,
            "instruments": instruments,
            "locations": locations,
            "success_message": "",
            "types": types,
            "vendors": vendors,
        },
    )


@router.post("/instruments/favorites")
def toggle_favorite(
    request: Request,
    instrument_id: int = Form(...),
    db: Session = Depends(get_db),
):
    instrument_service = InstrumentService(db)
    audit_service = AuditService(db)
    error_message = ""
    try:
        updated = instrument_service.toggle_favorite(instrument_id)
        audit_service.log_action(
            actor="Unknown",
            action_type="Update",
            entity_type="Instrument",
            entity_id=instrument_id,
            description=f"IsFavorite changed to {updated.is_favorite}",
        )
    except NotFoundError as exc:
        error_message = str(exc)

    instruments, locations, vendors, types, filters_ctx = _instrument_context(
        db, None, None, None, None, None
    )
    return templates.TemplateResponse(
        request,
        "instruments.html",
        {
            "error_message": error_message,
            "filters": filters_ctx,
            "instruments": instruments,
            "locations": locations,
            "success_message": "" if error_message else "Favorite updated.",
            "types": types,
            "vendors": vendors,
        },
    )


@router.get("/instruments/form")
def instrument_form_page(
    request: Request,
    instrument_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    locations = master_service.list_locations(active_only=True)
    vendors = master_service.list_vendors(active_only=True)
    types = master_service.list_types(active_only=True)

    instrument = None
    if instrument_id:
        instrument_service = InstrumentService(db)
        try:
            instrument = instrument_service.get_by_id(instrument_id)
        except NotFoundError:
            instrument = None

    return templates.TemplateResponse(
        request,
        "instruments.html",
        {
            "error_message": "",
            "filters": {"nickname": "", "location": "", "vendor": "", "type": "", "favorites": ""},
            "instruments": InstrumentService(db).list_active(InstrumentFilterDTO()),
            "locations": locations,
            "success_message": "",
            "types": types,
            "vendors": vendors,
            "instrument": instrument,
        },
    )


@router.post("/instruments/form")
def instrument_form_submit(
    request: Request,
    instrument_id: str = Form(""),
    nickname: str = Form(...),
    asset_id: str = Form(""),
    name: str = Form(...),
    location: str = Form(...),
    vendor: str = Form(...),
    type: str = Form(...),
    color: str = Form(""),
    is_active: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    instrument_service = InstrumentService(db)
    audit_service = AuditService(db)

    location_id = _parse_int(location)
    vendor_id = _parse_int(vendor)
    type_id = _parse_int(type)
    is_active_bool = _parse_bool(is_active)

    error_message = ""
    success_message = ""

    inst_id = _parse_int(instrument_id)

    try:
        if inst_id:
            before = instrument_service.get_by_id(inst_id)
            data = InstrumentUpdateDTO(
                name=name,
                nickname=nickname,
                location_id=location_id,
                vendor_id=vendor_id,
                type_id=type_id,
                asset_id=asset_id or None,
                color=color or None,
                is_active=is_active_bool,
            )
            updated = instrument_service.update(inst_id, data)
            changes = []
            if before.name != updated.name:
                changes.append(f"name: '{before.name}' -> '{updated.name}'")
            if before.nickname != updated.nickname:
                changes.append(f"nickname: '{before.nickname}' -> '{updated.nickname}'")
            if before.location_id != updated.location_id:
                changes.append(f"location_id: {before.location_id} -> {updated.location_id}")
            if before.vendor_id != updated.vendor_id:
                changes.append(f"vendor_id: {before.vendor_id} -> {updated.vendor_id}")
            if before.type_id != updated.type_id:
                changes.append(f"type_id: {before.type_id} -> {updated.type_id}")
            if before.asset_id != updated.asset_id:
                changes.append(f"asset_id: '{before.asset_id}' -> '{updated.asset_id}'")
            if before.color != updated.color:
                changes.append(f"color: '{before.color}' -> '{updated.color}'")
            description = "Updated fields: " + "; ".join(changes) if changes else "No field changes"
            audit_service.log_action(
                actor="Unknown",
                action_type="Update",
                entity_type="Instrument",
                entity_id=updated.instrument_id,
                description=description,
            )
            success_message = "Instrument updated successfully."
        else:
            data = InstrumentCreateDTO(
                name=name,
                nickname=nickname,
                location_id=location_id,
                vendor_id=vendor_id,
                type_id=type_id,
                asset_id=asset_id or None,
                color=color or None,
            )
            created = instrument_service.create(data)
            audit_service.log_action(
                actor="Unknown",
                action_type="Create",
                entity_type="Instrument",
                entity_id=created.instrument_id,
                description=f"Created instrument '{created.name}' ({created.nickname})",
            )
            success_message = "Instrument created successfully."
    except (ValidationError, DuplicateError, NotFoundError, InvalidStatusError) as exc:
        error_message = str(exc)

    instruments, locations, vendors, types, filters_ctx = _instrument_context(
        db, None, None, None, None, None
    )
    return templates.TemplateResponse(
        request,
        "instruments.html",
        {
            "error_message": error_message,
            "filters": filters_ctx,
            "instruments": instruments,
            "locations": locations,
            "success_message": success_message,
            "types": types,
            "vendors": vendors,
        },
    )


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------

@router.get("/reservations/new")
def reservation_form_page(request: Request, db: Session = Depends(get_db)):
    instrument_service = InstrumentService(db)
    master_service = MasterDataService(db)

    instruments = instrument_service.list_schedulable()
    instruments_sorted = sorted(instruments, key=lambda i: (i.name or "", i.nickname or ""))
    purposes = master_service.list_purposes(active_only=True)

    return templates.TemplateResponse(
        request,
        "reservations-new.html",
        {
            "instruments": instruments_sorted,
            "purposes": purposes,
            "error_message": "",
            "success_message": "",
            "field_errors": {},
            "instrument_id": "",
            "start_time": "",
            "end_time": "",
            "purpose_id": "",
            "requested_by": "",
            "can_be_overridden": "",
        },
    )


@router.post("/reservations/new")
def reservation_form_submit(
    request: Request,
    instrument_id: str = Form(...),
    start_time: str = Form(...),
    end_time: str = Form(...),
    purpose_id: str = Form(...),
    requested_by: str = Form(""),
    can_be_overridden: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    reservation_service = ReservationService(db)
    instrument_service = InstrumentService(db)
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    field_errors: dict[str, str] = {}
    error_message = ""
    success_message = ""

    requested_by_trimmed = requested_by.strip() if requested_by else ""
    actor = requested_by_trimmed if requested_by_trimmed else "Unknown"

    inst_id = _parse_int(instrument_id)
    purp_id = _parse_int(purpose_id)
    can_override = _parse_bool(can_be_overridden)

    start_dt = None
    end_dt = None
    try:
        start_dt = _parse_local_datetime(start_time)
    except (ValueError, TypeError):
        field_errors["start_time"] = "Invalid start time."
    try:
        end_dt = _parse_local_datetime(end_time)
    except (ValueError, TypeError):
        field_errors["end_time"] = "Invalid end time."

    if start_dt and end_dt and end_dt <= start_dt:
        field_errors["end_time"] = "End time must be after the start time."

    result = None
    if not field_errors and inst_id and purp_id and start_dt and end_dt:
        try:
            data = ReservationCreateDTO(
                instrument_id=inst_id,
                start_datetime=start_dt,
                end_datetime=end_dt,
                reservation_purpose_id=purp_id,
                requested_by=actor,
                can_be_overridden=can_override,
            )
            result = reservation_service.create(data)
        except ValidationError as exc:
            error_message = str(exc)
        except ConflictError as exc:
            error_message = str(exc)
        except InvalidStatusError as exc:
            error_message = str(exc)
        except NotFoundError as exc:
            error_message = str(exc)
    elif not field_errors:
        error_message = "Please complete all required fields."

    if result is not None:
        audit_service.log_action(
            actor=actor,
            action_type="Create",
            entity_type="Reservation",
            entity_id=result.reservation.reservation_id,
            description=(
                f"Created reservation for instrument {result.reservation.instrument_id} "
                f"from {result.reservation.start_datetime} to {result.reservation.end_datetime}"
            ),
        )
        for overridden_id in result.overridden_ids:
            audit_service.log_action(
                actor=actor,
                action_type="Update",
                entity_type="Reservation",
                entity_id=overridden_id,
                description=(
                    f"Reservation {overridden_id} replaced by new reservation "
                    f"{result.reservation.reservation_id}"
                ),
            )
        if result.overridden_ids:
            success_message = (
                "Reservation created successfully. This reservation replaced the "
                f"following: {result.overridden_ids}."
            )
        else:
            success_message = "Reservation created successfully."

    instruments = instrument_service.list_schedulable()
    instruments_sorted = sorted(instruments, key=lambda i: (i.name or "", i.nickname or ""))
    purposes = master_service.list_purposes(active_only=True)

    return templates.TemplateResponse(
        request,
        "reservations-new.html",
        {
            "instruments": instruments_sorted,
            "purposes": purposes,
            "error_message": error_message,
            "success_message": success_message,
            "field_errors": field_errors,
            "instrument_id": instrument_id,
            "start_time": start_time,
            "end_time": end_time,
            "purpose_id": purpose_id,
            "requested_by": requested_by,
            "can_be_overridden": "on" if can_override else "",
        },
        status_code=400 if (field_errors or error_message) else 200,
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------

@router.get("/audit")
def audit_page(request: Request, db: Session = Depends(get_db)):
    audit_service = AuditService(db)
    entries = audit_service.list_entries()
    entries_sorted = sorted(entries, key=lambda e: e.timestamp, reverse=True)
    return templates.TemplateResponse(
        request,
        "audit.html",
        {
            "audit_entries": entries_sorted,
            "error_message": "",
            "success_message": "",
        },
    )


# ---------------------------------------------------------------------------
# Admin: Locations
# ---------------------------------------------------------------------------

def _locations_ctx(db: Session, success_message="", error_message="", warning_message=""):
    master_service = MasterDataService(db)
    locations = master_service.list_locations(active_only=False)
    return {
        "locations": locations,
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": warning_message,
        "field_errors": {},
    }


@router.get("/admin/locations")
def admin_locations_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "admin-locations.html", _locations_ctx(db))


@router.post("/admin/locations")
def admin_locations_submit(
    request: Request,
    id: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""
    warning_message = ""

    loc_id = _parse_int(id)
    try:
        if loc_id and name:
            updated = master_service.update_location(loc_id, name)
            audit_service.log_action(
                actor="Unknown",
                action_type="Update",
                entity_type="Location",
                entity_id=updated.location_id,
                description=f"Location renamed to '{updated.name}'",
            )
            success_message = "Location updated successfully."
        elif loc_id and not name:
            master_service.deactivate_location(loc_id)
            audit_service.log_action(
                actor="Unknown",
                action_type="Deactivate",
                entity_type="Location",
                entity_id=loc_id,
                description="Location deactivated",
            )
            success_message = "Location deactivated."
        elif name:
            created = master_service.create_location(name)
            audit_service.log_action(
                actor="Unknown",
                action_type="Create",
                entity_type="Location",
                entity_id=created.location_id,
                description=f"Created location '{created.name}'",
            )
            success_message = "Location created successfully."
    except DuplicateError as exc:
        error_message = str(exc)
    except NotFoundError as exc:
        error_message = str(exc)
    except ValidationError as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-locations.html",
        _locations_ctx(db, success_message, error_message, warning_message),
    )


@router.post("/admin/locations/create")
def admin_locations_create(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""
    try:
        created = master_service.create_location(name)
        audit_service.log_action(
            actor="Unknown",
            action_type="Create",
            entity_type="Location",
            entity_id=created.location_id,
            description=f"Created location '{created.name}'",
        )
        success_message = "Location created successfully."
    except DuplicateError as exc:
        error_message = str(exc)
    except ValidationError as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-locations.html",
        _locations_ctx(db, success_message, error_message),
    )


@router.post("/admin/locations/update")
def admin_locations_update(
    request: Request,
    id: int = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""
    try:
        updated = master_service.update_location(id, name)
        audit_service.log_action(
            actor="Unknown",
            action_type="Update",
            entity_type="Location",
            entity_id=updated.location_id,
            description=f"Location renamed to '{updated.name}'",
        )
        success_message = "Location updated successfully."
    except (DuplicateError, NotFoundError, ValidationError) as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-locations.html",
        _locations_ctx(db, success_message, error_message),
    )


@router.post("/admin/locations/{location_id}/delete")
def admin_locations_delete(
    request: Request,
    location_id: int,
    id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""
    warning_message = ""
    target_id = _parse_int(id) or location_id
    try:
        count = master_service.deactivate_location(target_id)
        audit_service.log_action(
            actor="Unknown",
            action_type="Deactivate",
            entity_type="Location",
            entity_id=target_id,
            description="Location deactivated",
        )
        success_message = "Location deactivated."
        if count:
            warning_message = f"{count} active instrument(s) reference this location."
    except NotFoundError as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-locations.html",
        _locations_ctx(db, success_message, error_message, warning_message),
    )


@router.post("/admin/locations/{location_id}/reactivate")
def admin_locations_reactivate(
    request: Request,
    location_id: int,
    id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""
    target_id = _parse_int(id) or location_id
    try:
        updated = master_service.reactivate_location(target_id)
        audit_service.log_action(
            actor="Unknown",
            action_type="Reactivate",
            entity_type="Location",
            entity_id=updated.location_id,
            description="Location reactivated",
        )
        success_message = "Location reactivated."
    except NotFoundError as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-locations.html",
        _locations_ctx(db, success_message, error_message),
    )


# ---------------------------------------------------------------------------
# Admin: Vendors
# ---------------------------------------------------------------------------

def _vendors_ctx(db: Session, success_message="", error_message="", warning_message=""):
    master_service = MasterDataService(db)
    vendors = master_service.list_vendors(active_only=False)
    return {
        "vendors": vendors,
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": warning_message,
    }


@router.get("/admin/vendors")
def admin_vendors_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "admin-vendors.html", _vendors_ctx(db))


@router.post("/admin/vendors")
def admin_vendors_submit(
    request: Request,
    name: str = Form(...),
    isActive: Optional[str] = Form(None),
    vendor_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""
    warning_message = ""

    v_id = _parse_int(vendor_id)
    is_active = _parse_bool(isActive)

    try:
        if v_id:
            updated = master_service.update_vendor(v_id, name)
            audit_service.log_action(
                actor="Unknown",
                action_type="Update",
                entity_type="Vendor",
                entity_id=updated.vendor_id,
                description=f"Vendor renamed to '{updated.name}'",
            )
            if not is_active:
                count = master_service.deactivate_vendor(v_id)
                audit_service.log_action(
                    actor="Unknown",
                    action_type="Deactivate",
                    entity_type="Vendor",
                    entity_id=v_id,
                    description="Vendor deactivated",
                )
                if count:
                    warning_message = f"{count} active instrument(s) reference this vendor."
            success_message = "Vendor updated successfully."
        else:
            created = master_service.create_vendor(name)
            audit_service.log_action(
                actor="Unknown",
                action_type="Create",
                entity_type="Vendor",
                entity_id=created.vendor_id,
                description=f"Created vendor '{created.name}'",
            )
            success_message = "Vendor created successfully."
    except (DuplicateError, NotFoundError, ValidationError) as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-vendors.html",
        _vendors_ctx(db, success_message, error_message, warning_message),
    )


# ---------------------------------------------------------------------------
# Admin: Types
# ---------------------------------------------------------------------------

def _types_ctx(db: Session, success_message="", error_message="", warning_message=""):
    master_service = MasterDataService(db)
    types = master_service.list_types(active_only=False)
    return {
        "types": types,
        "success_message": success_message,
        "error_message": error_message,
        "warning_message": warning_message,
    }


@router.get("/admin/types")
def admin_types_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "admin-types.html", _types_ctx(db))


@router.post("/admin/types/create")
def admin_types_create(
    request: Request,
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""
    try:
        created = master_service.create_type(name)
        audit_service.log_action(
            actor="Unknown",
            action_type="Create",
            entity_type="InstrumentType",
            entity_id=created.type_id,
            description=f"Created type '{created.name}'",
        )
        success_message = "Type created successfully."
    except (DuplicateError, ValidationError) as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-types.html",
        _types_ctx(db, success_message, error_message),
    )


@router.post("/admin/types/update")
def admin_types_update(
    request: Request,
    id: int = Form(...),
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""
    try:
        updated = master_service.update_type(id, name)
        audit_service.log_action(
            actor="Unknown",
            action_type="Update",
            entity_type="InstrumentType",
            entity_id=updated.type_id,
            description=f"Type renamed to '{updated.name}'",
        )
        success_message = "Type updated successfully."
    except (DuplicateError, NotFoundError, ValidationError) as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-types.html",
        _types_ctx(db, success_message, error_message),
    )


@router.post("/admin/types/edit")
def admin_types_edit(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    # "Edit" simply loads the current list; no mutation occurs (view/select action).
    return templates.TemplateResponse(request, "admin-types.html", _types_ctx(db))


@router.post("/admin/types/delete")
def admin_types_delete(
    request: Request,
    id: int = Form(...),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""
    warning_message = ""
    try:
        count = master_service.deactivate_type(id)
        audit_service.log_action(
            actor="Unknown",
            action_type="Deactivate",
            entity_type="InstrumentType",
            entity_id=id,
            description="Type deactivated",
        )
        success_message = "Type deactivated."
        if count:
            warning_message = f"{count} active instrument(s) reference this type."
    except NotFoundError as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-types.html",
        _types_ctx(db, success_message, error_message, warning_message),
    )


@router.post("/admin/types")
def admin_types_submit(
    request: Request,
    id: Optional[str] = Form(None),
    name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    error_message = ""

    type_id = _parse_int(id)
    try:
        if type_id and name:
            updated = master_service.update_type(type_id, name)
            audit_service.log_action(
                actor="Unknown",
                action_type="Update",
                entity_type="InstrumentType",
                entity_id=updated.type_id,
                description=f"Type renamed to '{updated.name}'",
            )
            success_message = "Type updated successfully."
        elif type_id and not name:
            master_service.deactivate_type(type_id)
            audit_service.log_action(
                actor="Unknown",
                action_type="Deactivate",
                entity_type="InstrumentType",
                entity_id=type_id,
                description="Type deactivated",
            )
            success_message = "Type deactivated."
        elif name:
            created = master_service.create_type(name)
            audit_service.log_action(
                actor="Unknown",
                action_type="Create",
                entity_type="InstrumentType",
                entity_id=created.type_id,
                description=f"Created type '{created.name}'",
            )
            success_message = "Type created successfully."
    except (DuplicateError, NotFoundError, ValidationError) as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-types.html",
        _types_ctx(db, success_message, error_message),
    )


# ---------------------------------------------------------------------------
# Admin: Purposes
# ---------------------------------------------------------------------------

def _purposes_ctx(db: Session, success_message="", field_errors=None, purpose=None):
    master_service = MasterDataService(db)
    purposes = master_service.list_purposes(active_only=False)
    return {
        "purposes": purposes,
        "success_message": success_message,
        "field_errors": field_errors or {},
        "purpose": purpose,
    }


@router.get("/admin/purposes")
def admin_purposes_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "admin-purposes.html", _purposes_ctx(db))


@router.post("/admin/purposes")
def admin_purposes_submit(
    request: Request,
    purpose_id: Optional[str] = Form(None),
    name: str = Form(...),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    field_errors: dict[str, str] = {}

    p_id = _parse_int(purpose_id)
    try:
        if p_id:
            updated = master_service.update_purpose(p_id, name)
            audit_service.log_action(
                actor="Unknown",
                action_type="Update",
                entity_type="ReservationPurpose",
                entity_id=updated.reservation_purpose_id,
                description=f"Purpose renamed to '{updated.name}'",
            )
            success_message = "Purpose updated successfully."
        else:
            created = master_service.create_purpose(name)
            audit_service.log_action(
                actor="Unknown",
                action_type="Create",
                entity_type="ReservationPurpose",
                entity_id=created.reservation_purpose_id,
                description=f"Created purpose '{created.name}'",
            )
            success_message = "Purpose created successfully."
    except DuplicateError as exc:
        field_errors["name"] = str(exc)
    except (NotFoundError, ValidationError) as exc:
        field_errors["name"] = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-purposes.html",
        _purposes_ctx(db, success_message, field_errors, {"name": name, "purpose_id": purpose_id}),
    )


@router.post("/admin/purposes/edit")
def admin_purposes_edit(
    request: Request,
    purpose_id: int = Form(...),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    purposes = master_service.list_purposes(active_only=False)
    selected = next((p for p in purposes if p.reservation_purpose_id == purpose_id), None)
    return templates.TemplateResponse(
        request,
        "admin-purposes.html",
        _purposes_ctx(db, "", {}, selected),
    )


@router.post("/admin/purposes/delete")
def admin_purposes_delete(
    request: Request,
    purpose_id: int = Form(...),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    field_errors: dict[str, str] = {}
    try:
        count = master_service.deactivate_purpose(purpose_id)
        audit_service.log_action(
            actor="Unknown",
            action_type="Deactivate",
            entity_type="ReservationPurpose",
            entity_id=purpose_id,
            description="Purpose deactivated",
        )
        success_message = "Purpose deactivated."
        if count:
            success_message += f" {count} active reservation(s) reference this purpose."
    except NotFoundError as exc:
        field_errors["name"] = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-purposes.html",
        _purposes_ctx(db, success_message, field_errors),
    )


@router.post("/admin/purposes/restore")
def admin_purposes_restore(
    request: Request,
    purpose_id: int = Form(...),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)
    success_message = ""
    field_errors: dict[str, str] = {}
    try:
        updated = master_service.reactivate_purpose(purpose_id)
        audit_service.log_action(
            actor="Unknown",
            action_type="Reactivate",
            entity_type="ReservationPurpose",
            entity_id=updated.reservation_purpose_id,
            description="Purpose reactivated",
        )
        success_message = "Purpose reactivated."
    except NotFoundError as exc:
        field_errors["name"] = str(exc)

    return templates.TemplateResponse(
        request,
        "admin-purposes.html",
        _purposes_ctx(db, success_message, field_errors),
    )
