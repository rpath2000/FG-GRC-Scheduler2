"""Server-rendered pages for the instrument scheduler application.

Serves the approved Jinja2/HTMX screens. All persistence is delegated
in-process to the shared services declared in app.contracts / app.services.
No database connection is opened at import time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
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

TIME_SLOT_MINUTES = 30
DEFAULT_COLOR = "#3366CC"  # mid-blue default

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_bool(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "on", "yes")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _day_bounds(day: datetime) -> tuple[datetime, datetime]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _week_bounds(day: datetime) -> tuple[datetime, datetime]:
    start_of_week = day - timedelta(days=day.weekday())
    start = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=7)


def _format_range_label(start: datetime, end: datetime, view: str) -> str:
    if view == "week":
        last_day = end - timedelta(days=1)
        if start.month == last_day.month:
            return f"{start.strftime('%b %-d')} \u2013 {last_day.strftime('%-d, %Y')}"
        return f"{start.strftime('%b %-d')} \u2013 {last_day.strftime('%b %-d, %Y')}"
    return start.strftime("%b %-d, %Y")


def _instrument_sort_key(inst):
    return ((inst.name or "").lower(), (inst.nickname or "").lower())


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
    view = view if view in ("day", "week") else "week"

    if date:
        try:
            selected_date = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            selected_date = datetime.now(timezone.utc)
    else:
        selected_date = datetime.now(timezone.utc)

    if view == "day":
        start, end = _day_bounds(selected_date)
    else:
        start, end = _week_bounds(selected_date)

    instrument_service = InstrumentService(db)
    reservation_service = ReservationService(db)

    instruments = sorted(instrument_service.list_schedulable(), key=_instrument_sort_key)
    instrument_ids = [inst.instrument_id for inst in instruments]

    reservations = []
    if instrument_ids:
        reservations = reservation_service.list_by_instrument_and_range(instrument_ids, start, end)

    resources = []
    for inst in instruments:
        items = []
        for res in reservations:
            if res.instrument_id != inst.instrument_id:
                continue
            items.append(
                {
                    "reservation_id": res.reservation_id,
                    "instrument_id": res.instrument_id,
                    "start_datetime": _as_utc(res.start_datetime).isoformat(),
                    "end_datetime": _as_utc(res.end_datetime).isoformat(),
                    "purpose_name": res.purpose_name,
                    "requested_by": res.requested_by,
                }
            )
        resources.append(
            {
                "instrument_id": inst.instrument_id,
                "name": inst.name,
                "nickname": inst.nickname,
                "asset_id": inst.asset_id or "",
                "label": f"{inst.name} ({inst.nickname}) - {inst.asset_id or ''}",
                "color": inst.color or DEFAULT_COLOR,
                "reservations": items,
            }
        )

    days = []
    cursor = start
    while cursor < end:
        days.append(cursor.strftime("%Y-%m-%d"))
        cursor += timedelta(days=1)

    time_labels = [f"{hour:02d}:00 UTC" for hour in range(0, 24, 3)]

    context = {
        "date_range_label": _format_range_label(start, end, view),
        "days": days,
        "error_message": "",
        "resources": resources,
        "selected_date": selected_date.strftime("%Y-%m-%d"),
        "success_message": "",
        "time_labels": time_labels,
        "user": STATIC_USER,
        "view": view,
    }
    return templates.TemplateResponse(request, "scheduler.html", context)


@router.get("/")
def index_page(
    request: Request,
    date: Optional[str] = None,
    view: str = "week",
    db: Session = Depends(get_db),
):
    return scheduler_page(request, date=date, view=view, db=db)


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------


def _instrument_filters_context(nickname, location, vendor, type_, favorites):
    return {
        "nickname": nickname or "",
        "location": location or "",
        "vendor": vendor or "",
        "type": type_ or "",
        "favorites": favorites,
    }


def _load_instruments_page(
    request: Request,
    db: Session,
    nickname: Optional[str],
    location: Optional[str],
    vendor: Optional[str],
    type_: Optional[str],
    favorites,
    template_name: str,
    error_message: str = "",
    success_message: str = "",
):
    instrument_service = InstrumentService(db)
    master_service = MasterDataService(db)

    favorites_only = _parse_bool(favorites)

    filter_dto = InstrumentFilterDTO(
        nickname=nickname or None,
        location_id=_parse_int(location),
        vendor_id=_parse_int(vendor),
        type_id=_parse_int(type_),
        favorites_only=favorites_only if favorites_only else None,
    )

    instruments = instrument_service.list_active(filter_dto)
    instruments = sorted(instruments, key=_instrument_sort_key)

    locations = master_service.list_locations(active_only=True)
    vendors = master_service.list_vendors(active_only=True)
    types = master_service.list_types(active_only=True)

    context = {
        "error_message": error_message,
        "filters": _instrument_filters_context(nickname, location, vendor, type_, favorites_only),
        "instruments": instruments,
        "locations": locations,
        "success_message": success_message,
        "types": types,
        "vendors": vendors,
    }
    return templates.TemplateResponse(request, template_name, context)


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
    return _load_instruments_page(
        request, db, nickname, location, vendor, type, favorites, "instruments.html"
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
    # This route uses the same filters but forces the favourites-only view
    # while still honouring any additional filters passed in the query.
    if favorites is None:
        favorites = "true"
    return _load_instruments_page(
        request, db, nickname, location, vendor, type, favorites, "instruments.html"
    )


@router.post("/instruments/favorites")
def toggle_favorite(
    request: Request,
    instrument_id: str = Form(...),
    db: Session = Depends(get_db),
):
    instrument_service = InstrumentService(db)
    audit_service = AuditService(db)

    inst_id = _parse_int(instrument_id)
    error_message = ""
    if inst_id is not None:
        try:
            updated = instrument_service.toggle_favorite(inst_id)
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Update",
                entity_type="Instrument",
                entity_id=updated.instrument_id,
                description=f"IsFavorite changed to {updated.is_favorite}",
            )
        except NotFoundError as exc:
            error_message = str(exc)
    else:
        error_message = "Invalid instrument."

    return _load_instruments_page(
        request, db, None, None, None, None, None, "instruments.html", error_message=error_message
    )


@router.get("/instruments/form")
def instrument_form_page(
    request: Request,
    instrument_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    instrument_service = InstrumentService(db)

    inst_id = _parse_int(instrument_id)
    instrument = None
    if inst_id is not None:
        try:
            instrument = instrument_service.get_by_id(inst_id)
        except NotFoundError:
            instrument = None

    locations = master_service.list_locations(active_only=True)
    vendors = master_service.list_vendors(active_only=True)
    types = master_service.list_types(active_only=True)

    context = {
        "success_message": "",
        "field_errors": {},
        "error_message": "",
        "instrument": instrument,
        "instrument_id": str(instrument.instrument_id) if instrument else "",
        "nickname": instrument.nickname if instrument else "",
        "asset_id": instrument.asset_id if instrument else "",
        "name": instrument.name if instrument else "",
        "location": str(instrument.location_id) if instrument else "",
        "vendor": str(instrument.vendor_id) if instrument else "",
        "type": str(instrument.type_id) if instrument else "",
        "color": instrument.color if instrument else "",
        "is_active": instrument.is_active if instrument else True,
        "locations": locations,
        "vendors": vendors,
        "types": types,
    }
    return templates.TemplateResponse(request, "instruments.html", context)


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

    field_errors: dict[str, str] = {}
    error_message = ""
    success_message = ""

    location_id = _parse_int(location)
    vendor_id = _parse_int(vendor)
    type_id = _parse_int(type)

    if not nickname or not nickname.strip():
        field_errors["nickname"] = "Nickname is required."
    if not name or not name.strip():
        field_errors["name"] = "Name is required."
    if location_id is None:
        field_errors["location"] = "Location is required."
    if vendor_id is None:
        field_errors["vendor"] = "Vendor is required."
    if type_id is None:
        field_errors["type"] = "Type is required."

    inst_id = _parse_int(instrument_id)
    is_active_bool = _parse_bool(is_active) if is_active is not None else True

    if not field_errors:
        try:
            if inst_id:
                before = instrument_service.get_by_id(inst_id)
                dto = InstrumentUpdateDTO(
                    name=name.strip(),
                    nickname=nickname.strip(),
                    location_id=location_id,
                    vendor_id=vendor_id,
                    type_id=type_id,
                    asset_id=asset_id or None,
                    color=color or None,
                    is_active=is_active_bool,
                )
                after = instrument_service.update(inst_id, dto)

                changes = []
                if before.name != after.name:
                    changes.append(f"name: '{before.name}' -> '{after.name}'")
                if before.nickname != after.nickname:
                    changes.append(f"nickname: '{before.nickname}' -> '{after.nickname}'")
                if before.location_id != after.location_id:
                    changes.append(f"location_id: {before.location_id} -> {after.location_id}")
                if before.vendor_id != after.vendor_id:
                    changes.append(f"vendor_id: {before.vendor_id} -> {after.vendor_id}")
                if before.type_id != after.type_id:
                    changes.append(f"type_id: {before.type_id} -> {after.type_id}")
                if before.asset_id != after.asset_id:
                    changes.append(f"asset_id: '{before.asset_id}' -> '{after.asset_id}'")
                if before.color != after.color:
                    changes.append(f"color: '{before.color}' -> '{after.color}'")
                if before.is_active != after.is_active:
                    changes.append(f"is_active: {before.is_active} -> {after.is_active}")

                description = "Updated fields: " + "; ".join(changes) if changes else "No field changes."
                audit_service.log_action(
                    actor=STATIC_USER,
                    action_type="Update",
                    entity_type="Instrument",
                    entity_id=after.instrument_id,
                    description=description,
                )
                success_message = "Instrument updated successfully."
            else:
                dto = InstrumentCreateDTO(
                    name=name.strip(),
                    nickname=nickname.strip(),
                    location_id=location_id,
                    vendor_id=vendor_id,
                    type_id=type_id,
                    asset_id=asset_id or None,
                    color=color or None,
                )
                created = instrument_service.create(dto)
                audit_service.log_action(
                    actor=STATIC_USER,
                    action_type="Create",
                    entity_type="Instrument",
                    entity_id=created.instrument_id,
                    description=f"Created instrument '{created.name}' ({created.nickname})",
                )
                success_message = "Instrument created successfully."
                inst_id = created.instrument_id
        except DuplicateError as exc:
            field_errors["nickname"] = str(exc)
        except ValidationError as exc:
            error_message = str(exc)
        except NotFoundError as exc:
            error_message = str(exc)

    master_service = MasterDataService(db)
    locations = master_service.list_locations(active_only=True)
    vendors = master_service.list_vendors(active_only=True)
    types = master_service.list_types(active_only=True)

    context = {
        "success_message": success_message,
        "field_errors": field_errors,
        "error_message": error_message,
        "instrument_id": str(inst_id) if inst_id else "",
        "nickname": nickname,
        "asset_id": asset_id,
        "name": name,
        "location": location,
        "vendor": vendor,
        "type": type,
        "color": color,
        "is_active": is_active_bool,
        "locations": locations,
        "vendors": vendors,
        "types": types,
    }
    return templates.TemplateResponse(request, "instruments.html", context)


@router.post("/instruments/status")
def instrument_status_change(
    request: Request,
    instrument_id: str = Form(...),
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    instrument_service = InstrumentService(db)
    audit_service = AuditService(db)

    error_message = ""
    inst_id = _parse_int(instrument_id)
    if inst_id is not None:
        try:
            before = instrument_service.get_by_id(inst_id)
            after = instrument_service.change_status(inst_id, status)
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Update",
                entity_type="Instrument",
                entity_id=after.instrument_id,
                description=f"status: '{before.status}' -> '{after.status}'",
            )
        except (NotFoundError, ValidationError, InvalidStatusError) as exc:
            error_message = str(exc)

    return _load_instruments_page(
        request, db, None, None, None, None, None, "instruments.html", error_message=error_message
    )


@router.post("/instruments/delete")
def instrument_delete(
    request: Request,
    instrument_id: str = Form(...),
    db: Session = Depends(get_db),
):
    instrument_service = InstrumentService(db)
    audit_service = AuditService(db)

    error_message = ""
    inst_id = _parse_int(instrument_id)
    if inst_id is not None:
        try:
            before = instrument_service.get_by_id(inst_id)
            instrument_service.soft_delete(inst_id)
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Delete",
                entity_type="Instrument",
                entity_id=inst_id,
                description=f"Soft-deleted instrument '{before.name}' ({before.nickname})",
            )
        except NotFoundError as exc:
            error_message = str(exc)

    return _load_instruments_page(
        request, db, None, None, None, None, None, "instruments.html", error_message=error_message
    )


# ---------------------------------------------------------------------------
# Reservations
# ---------------------------------------------------------------------------


@router.get("/reservations/new")
def reservation_new_page(request: Request, db: Session = Depends(get_db)):
    instrument_service = InstrumentService(db)
    master_service = MasterDataService(db)

    instruments = sorted(instrument_service.list_schedulable(), key=_instrument_sort_key)
    purposes = master_service.list_purposes(active_only=True)

    context = {
        "success_message": "",
        "field_errors": {},
        "error_message": "",
        "instrument_id": "",
        "start_time": "",
        "end_time": "",
        "purpose_id": "",
        "requested_by": "",
        "can_be_overridden": False,
        "instruments": instruments,
        "purposes": purposes,
    }
    return templates.TemplateResponse(request, "reservations-new.html", context)


def _parse_datetime_local(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc)


@router.post("/reservations/new")
def reservation_new_submit(
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
    audit_service = AuditService(db)
    instrument_service = InstrumentService(db)
    master_service = MasterDataService(db)

    field_errors: dict[str, str] = {}
    error_message = ""
    success_message = ""

    inst_id = _parse_int(instrument_id)
    purp_id = _parse_int(purpose_id)
    start_dt = _parse_datetime_local(start_time)
    end_dt = _parse_datetime_local(end_time)
    overridden_flag = _parse_bool(can_be_overridden)
    requested_by_trimmed = requested_by.strip() if requested_by else ""
    actor = requested_by_trimmed if requested_by_trimmed else "Unknown"

    if inst_id is None:
        field_errors["instrument_id"] = "Instrument is required."
    if purp_id is None:
        field_errors["purpose_id"] = "Purpose is required."
    if start_dt is None:
        field_errors["start_time"] = "Start time is required."
    if end_dt is None:
        field_errors["end_time"] = "End time is required."
    if len(requested_by) > 120:
        field_errors["requested_by"] = "Requested by must be 120 characters or fewer."

    if not field_errors and start_dt is not None and end_dt is not None:
        if end_dt <= start_dt:
            field_errors["end_time"] = "End time must be after the start time."

    status_code = 200
    if not field_errors:
        try:
            dto = ReservationCreateDTO(
                instrument_id=inst_id,
                start_datetime=start_dt,
                end_datetime=end_dt,
                reservation_purpose_id=purp_id,
                requested_by=requested_by_trimmed or None,
                can_be_overridden=overridden_flag,
            )
            result = reservation_service.create(dto)

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

            if result.overridden_ids:
                for overridden_id in result.overridden_ids:
                    audit_service.log_action(
                        actor=actor,
                        action_type="Delete",
                        entity_type="Reservation",
                        entity_id=overridden_id,
                        description=f"Replaced by reservation {result.reservation.reservation_id}",
                    )
                ids_list = ", ".join(str(i) for i in result.overridden_ids)
                success_message = (
                    "Reservation created successfully. This reservation replaced the "
                    f"following: [{ids_list}]."
                )
            else:
                success_message = "Reservation created successfully."

            instrument_id = ""
            start_time = ""
            end_time = ""
            purpose_id = ""
            requested_by = ""
            can_be_overridden = None
        except ValidationError as exc:
            error_message = str(exc)
            status_code = 400
        except InvalidStatusError as exc:
            error_message = str(exc)
            status_code = 400
        except ConflictError as exc:
            error_message = str(exc)
            status_code = 400
        except NotFoundError as exc:
            error_message = str(exc)
            status_code = 400
    else:
        status_code = 400

    instruments = sorted(instrument_service.list_schedulable(), key=_instrument_sort_key)
    purposes = master_service.list_purposes(active_only=True)

    context = {
        "success_message": success_message,
        "field_errors": field_errors,
        "error_message": error_message,
        "instrument_id": instrument_id,
        "start_time": start_time,
        "end_time": end_time,
        "purpose_id": purpose_id,
        "requested_by": requested_by,
        "can_be_overridden": _parse_bool(can_be_overridden),
        "instruments": instruments,
        "purposes": purposes,
    }
    return templates.TemplateResponse(
        request, "reservations-new.html", context, status_code=status_code
    )


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


@router.get("/audit")
def audit_page(request: Request, db: Session = Depends(get_db)):
    audit_service = AuditService(db)
    entries = audit_service.list_entries()
    entries = sorted(entries, key=lambda e: e.timestamp, reverse=True)

    context = {
        "audit_entries": entries,
        "error_message": "",
        "success_message": "",
    }
    return templates.TemplateResponse(request, "audit.html", context)


# ---------------------------------------------------------------------------
# Admin: Locations
# ---------------------------------------------------------------------------


def _render_locations(request: Request, db: Session, success="", error="", warning="", field_errors=None):
    master_service = MasterDataService(db)
    locations = master_service.list_locations(active_only=False)
    context = {
        "success_message": success,
        "error_message": error,
        "warning_message": warning,
        "field_errors": field_errors or {},
        "locations": locations,
    }
    return templates.TemplateResponse(request, "admin-locations.html", context)


@router.post("/admin/locations")
def admin_locations_submit(
    request: Request,
    id: str = Form(""),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    loc_id = _parse_int(id)
    success = ""
    error = ""
    field_errors: dict[str, str] = {}

    try:
        if loc_id and name:
            before_list = master_service.list_locations(active_only=False)
            before = next((l for l in before_list if l.location_id == loc_id), None)
            updated = master_service.update_location(loc_id, name.strip())
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Update",
                entity_type="Location",
                entity_id=updated.location_id,
                description=f"name: '{before.name if before else ''}' -> '{updated.name}'",
            )
            success = "Location updated successfully."
        elif loc_id and not name:
            updated = master_service.reactivate_location(loc_id)
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Update",
                entity_type="Location",
                entity_id=updated.location_id,
                description="Reactivated location.",
            )
            success = "Location reactivated successfully."
        elif name:
            created = master_service.create_location(name.strip())
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Create",
                entity_type="Location",
                entity_id=created.location_id,
                description=f"Created location '{created.name}'",
            )
            success = "Location created successfully."
    except DuplicateError as exc:
        field_errors["name"] = str(exc)
    except NotFoundError as exc:
        error = str(exc)
    except ValidationError as exc:
        field_errors["name"] = str(exc)

    return _render_locations(request, db, success=success, error=error, field_errors=field_errors)


@router.post("/admin/locations/create")
def admin_locations_create(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    return admin_locations_submit(request, id="", name=name, db=db)


@router.post("/admin/locations/update")
def admin_locations_update(
    request: Request, id: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)
):
    return admin_locations_submit(request, id=id, name=name, db=db)


@router.post("/admin/locations/{loc_id}/delete")
def admin_locations_delete(
    request: Request, loc_id: int, id: str = Form(...), db: Session = Depends(get_db)
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    location_id = _parse_int(id) or loc_id
    warning = ""
    error = ""
    try:
        before_list = master_service.list_locations(active_only=False)
        before = next((l for l in before_list if l.location_id == location_id), None)
        usage_count = master_service.deactivate_location(location_id)
        audit_service.log_action(
            actor=STATIC_USER,
            action_type="Delete",
            entity_type="Location",
            entity_id=location_id,
            description=f"Deactivated location '{before.name if before else ''}'",
        )
        if usage_count:
            warning = f"{usage_count} active instrument(s) reference this location."
    except NotFoundError as exc:
        error = str(exc)

    return _render_locations(request, db, warning=warning, error=error)


@router.post("/admin/locations/{loc_id}/reactivate")
def admin_locations_reactivate(
    request: Request, loc_id: int, id: str = Form(...), db: Session = Depends(get_db)
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    location_id = _parse_int(id) or loc_id
    error = ""
    success = ""
    try:
        updated = master_service.reactivate_location(location_id)
        audit_service.log_action(
            actor=STATIC_USER,
            action_type="Update",
            entity_type="Location",
            entity_id=updated.location_id,
            description="Reactivated location.",
        )
        success = "Location reactivated successfully."
    except NotFoundError as exc:
        error = str(exc)

    return _render_locations(request, db, success=success, error=error)


# ---------------------------------------------------------------------------
# Admin: Vendors
# ---------------------------------------------------------------------------


def _render_vendors(request: Request, db: Session, success="", error="", warning=""):
    master_service = MasterDataService(db)
    vendors = master_service.list_vendors(active_only=False)
    context = {
        "error_message": error,
        "success_message": success,
        "vendors": vendors,
        "warning_message": warning,
    }
    return templates.TemplateResponse(request, "admin-vendors.html", context)


@router.post("/admin/vendors")
def admin_vendors_submit(
    request: Request,
    name: str = Form(""),
    isActive: Optional[str] = Form(None),
    id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    success = ""
    error = ""
    warning = ""
    vendor_id = _parse_int(id)
    is_active_flag = _parse_bool(isActive) if isActive is not None else True

    try:
        if vendor_id and name:
            before_list = master_service.list_vendors(active_only=False)
            before = next((v for v in before_list if v.vendor_id == vendor_id), None)
            updated = master_service.update_vendor(vendor_id, name.strip())
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Update",
                entity_type="Vendor",
                entity_id=updated.vendor_id,
                description=f"name: '{before.name if before else ''}' -> '{updated.name}'",
            )
            success = "Vendor updated successfully."
        elif vendor_id and not name:
            if is_active_flag:
                updated = master_service.reactivate_vendor(vendor_id)
                audit_service.log_action(
                    actor=STATIC_USER,
                    action_type="Update",
                    entity_type="Vendor",
                    entity_id=updated.vendor_id,
                    description="Reactivated vendor.",
                )
                success = "Vendor reactivated successfully."
            else:
                usage_count = master_service.deactivate_vendor(vendor_id)
                audit_service.log_action(
                    actor=STATIC_USER,
                    action_type="Delete",
                    entity_type="Vendor",
                    entity_id=vendor_id,
                    description="Deactivated vendor.",
                )
                if usage_count:
                    warning = f"{usage_count} active instrument(s) reference this vendor."
                success = "Vendor deactivated successfully."
        elif name:
            created = master_service.create_vendor(name.strip())
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Create",
                entity_type="Vendor",
                entity_id=created.vendor_id,
                description=f"Created vendor '{created.name}'",
            )
            success = "Vendor created successfully."
    except DuplicateError as exc:
        error = str(exc)
    except NotFoundError as exc:
        error = str(exc)
    except ValidationError as exc:
        error = str(exc)

    return _render_vendors(request, db, success=success, error=error, warning=warning)


# ---------------------------------------------------------------------------
# Admin: Types
# ---------------------------------------------------------------------------


def _render_types(request: Request, db: Session, success="", error="", warning="", edit_type=None, field_errors=None):
    master_service = MasterDataService(db)
    types = master_service.list_types(active_only=False)
    context = {
        "success_message": success,
        "error_message": error,
        "warning_message": warning,
        "field_errors": field_errors or {},
        "types": types,
        "edit_type": edit_type,
    }
    return templates.TemplateResponse(request, "admin-types.html", context)


@router.post("/admin/types/create")
def admin_types_create(request: Request, name: str = Form(...), db: Session = Depends(get_db)):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    success = ""
    error = ""
    field_errors: dict[str, str] = {}

    try:
        created = master_service.create_type(name.strip())
        audit_service.log_action(
            actor=STATIC_USER,
            action_type="Create",
            entity_type="InstrumentType",
            entity_id=created.type_id,
            description=f"Created type '{created.name}'",
        )
        success = "Type created successfully."
    except DuplicateError as exc:
        field_errors["name"] = str(exc)
    except ValidationError as exc:
        field_errors["name"] = str(exc)

    return _render_types(request, db, success=success, error=error, field_errors=field_errors)


@router.post("/admin/types/update")
def admin_types_update(
    request: Request, id: str = Form(...), name: str = Form(...), db: Session = Depends(get_db)
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    type_id = _parse_int(id)
    success = ""
    error = ""
    field_errors: dict[str, str] = {}

    try:
        before_list = master_service.list_types(active_only=False)
        before = next((t for t in before_list if t.type_id == type_id), None)
        updated = master_service.update_type(type_id, name.strip())
        audit_service.log_action(
            actor=STATIC_USER,
            action_type="Update",
            entity_type="InstrumentType",
            entity_id=updated.type_id,
            description=f"name: '{before.name if before else ''}' -> '{updated.name}'",
        )
        success = "Type updated successfully."
    except DuplicateError as exc:
        field_errors["name"] = str(exc)
    except NotFoundError as exc:
        error = str(exc)
    except ValidationError as exc:
        field_errors["name"] = str(exc)

    return _render_types(request, db, success=success, error=error, field_errors=field_errors)


@router.post("/admin/types/edit")
def admin_types_edit(request: Request, id: str = Form(...), db: Session = Depends(get_db)):
    master_service = MasterDataService(db)
    type_id = _parse_int(id)
    types = master_service.list_types(active_only=False)
    edit_type = next((t for t in types if t.type_id == type_id), None)
    return _render_types(request, db, edit_type=edit_type)


@router.post("/admin/types/delete")
def admin_types_delete(request: Request, id: str = Form(...), db: Session = Depends(get_db)):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    type_id = _parse_int(id)
    warning = ""
    error = ""
    success = ""

    try:
        before_list = master_service.list_types(active_only=False)
        before = next((t for t in before_list if t.type_id == type_id), None)
        usage_count = master_service.deactivate_type(type_id)
        audit_service.log_action(
            actor=STATIC_USER,
            action_type="Delete",
            entity_type="InstrumentType",
            entity_id=type_id,
            description=f"Deactivated type '{before.name if before else ''}'",
        )
        if usage_count:
            warning = f"{usage_count} active instrument(s) reference this type."
        success = "Type deactivated successfully."
    except NotFoundError as exc:
        error = str(exc)

    return _render_types(request, db, success=success, error=error, warning=warning)


# ---------------------------------------------------------------------------
# Admin: Purposes
# ---------------------------------------------------------------------------


def _render_purposes(request: Request, db: Session, success="", error="", field_errors=None, purpose=None):
    master_service = MasterDataService(db)
    purposes = master_service.list_purposes(active_only=False)
    context = {
        "error_message": error,
        "field_errors": field_errors or {},
        "purpose": purpose,
        "purposes": purposes,
        "success_message": success,
    }
    return templates.TemplateResponse(request, "admin-purposes.html", context)


@router.post("/admin/purposes")
def admin_purposes_submit(
    request: Request,
    purpose_id: str = Form(""),
    name: str = Form(""),
    db: Session = Depends(get_db),
):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    success = ""
    error = ""
    field_errors: dict[str, str] = {}

    p_id = _parse_int(purpose_id)

    try:
        if p_id and name:
            before_list = master_service.list_purposes(active_only=False)
            before = next((p for p in before_list if p.reservation_purpose_id == p_id), None)
            updated = master_service.update_purpose(p_id, name.strip())
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Update",
                entity_type="ReservationPurpose",
                entity_id=updated.reservation_purpose_id,
                description=f"name: '{before.name if before else ''}' -> '{updated.name}'",
            )
            success = "Purpose updated successfully."
        elif name:
            created = master_service.create_purpose(name.strip())
            audit_service.log_action(
                actor=STATIC_USER,
                action_type="Create",
                entity_type="ReservationPurpose",
                entity_id=created.reservation_purpose_id,
                description=f"Created purpose '{created.name}'",
            )
            success = "Purpose created successfully."
    except DuplicateError as exc:
        field_errors["name"] = str(exc)
    except NotFoundError as exc:
        error = str(exc)
    except ValidationError as exc:
        field_errors["name"] = str(exc)

    return _render_purposes(request, db, success=success, error=error, field_errors=field_errors)


@router.post("/admin/purposes/edit")
def admin_purposes_edit(request: Request, purpose_id: str = Form(...), db: Session = Depends(get_db)):
    master_service = MasterDataService(db)
    p_id = _parse_int(purpose_id)
    purposes = master_service.list_purposes(active_only=False)
    purpose = next((p for p in purposes if p.reservation_purpose_id == p_id), None)
    return _render_purposes(request, db, purpose=purpose)


@router.post("/admin/purposes/delete")
def admin_purposes_delete(request: Request, purpose_id: str = Form(...), db: Session = Depends(get_db)):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    p_id = _parse_int(purpose_id)
    error = ""
    success = ""

    try:
        before_list = master_service.list_purposes(active_only=False)
        before = next((p for p in before_list if p.reservation_purpose_id == p_id), None)
        usage_count = master_service.deactivate_purpose(p_id)
        audit_service.log_action(
            actor=STATIC_USER,
            action_type="Delete",
            entity_type="ReservationPurpose",
            entity_id=p_id,
            description=f"Deactivated purpose '{before.name if before else ''}'",
        )
        if usage_count:
            success = f"Purpose deactivated. {usage_count} active reservation(s) reference this purpose."
        else:
            success = "Purpose deactivated successfully."
    except NotFoundError as exc:
        error = str(exc)

    return _render_purposes(request, db, success=success, error=error)


@router.post("/admin/purposes/restore")
def admin_purposes_restore(request: Request, purpose_id: str = Form(...), db: Session = Depends(get_db)):
    master_service = MasterDataService(db)
    audit_service = AuditService(db)

    p_id = _parse_int(purpose_id)
    error = ""
    success = ""

    try:
        updated = master_service.reactivate_purpose(p_id)
        audit_service.log_action(
            actor=STATIC_USER,
            action_type="Update",
            entity_type="ReservationPurpose",
            entity_id=updated.reservation_purpose_id,
            description="Reactivated purpose.",
        )
        success = "Purpose reactivated successfully."
    except NotFoundError as exc:
        error = str(exc)

    return _render_purposes(request, db, success=success, error=error)
