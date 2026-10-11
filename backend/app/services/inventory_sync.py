"""
Keeps each client's property inventory current by syncing it from where the client already
maintains it (a Google Sheet or a CRM/website API) into the structured `properties` table that
the agent's search_properties tool queries live during calls.
"""
import csv
import hashlib
import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy.orm import Session

from app.models.inventory_source import InventorySource
from app.models.property import Property

logger = logging.getLogger("choranta.services.inventory_sync")

FETCH_TIMEOUT_S = 20.0
PREVIEW_ROWS = 10

# Property field -> normalized source column names that commonly hold it
FIELD_SYNONYMS: Dict[str, List[str]] = {
    "external_id": ["id", "propertyid", "unitid", "unitno", "unitnumber", "flatno", "flatnumber", "listingid", "code", "sku", "refno", "reference"],
    "project_name": ["project", "projectname", "property", "propertyname", "name", "building", "title", "society", "tower"],
    "location": ["location", "area", "locality", "address", "city", "sector", "micromarket", "neighbourhood", "neighborhood", "zone"],
    "price": ["price", "cost", "amount", "rate", "totalprice", "pricelakhs", "pricecr", "priceinr", "budget", "allinclusiveprice"],
    "bhk": ["bhk", "bedrooms", "beds", "bedroom", "configuration", "config", "unittype"],
    "status": ["status", "availability", "available", "inventorystatus", "unitstatus"],
    "property_type": ["propertytype", "type", "category", "unitcategory"],
    "amenities": ["amenities", "features", "facilities", "highlights"],
}
REQUIRED_FIELDS = ("project_name", "location", "price")

STATUS_MAP = {
    "AVAILABLE": ["available", "vacant", "open", "ready", "unsold", "yes", "active", "forsale"],
    "SOLD": ["sold", "soldout", "closed", "no", "registered"],
    "UNDER_OFFER": ["booked", "hold", "onhold", "blocked", "reserved", "underoffer", "token", "tokenreceived"],
}


class InventorySyncError(Exception):
    pass


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


# ----------------------------------------------------------------------
# Normalizers for messy real estate data
# ----------------------------------------------------------------------

def parse_price(value: Any, column_hint: str = "") -> Optional[int]:
    """
    "₹85 Lakhs", "85L", "1.2 Cr", "1,20,00,000", "85-90 L" -> rupees (int).
    A bare small number is read in the unit named by the column ("Price (Lakhs)", "Price Cr"),
    otherwise as lakhs if under 1,000 (Indian listing convention).
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        number, unit = float(value), ""
    else:
        text = str(value).lower().replace(",", "").replace("₹", "").replace("rs.", "").replace("rs", "").replace("inr", "").strip()
        match = re.search(r"(\d+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lacs?|lac|l|k|thousand)?", text)
        if not match:
            return None
        number, unit = float(match.group(1)), (match.group(2) or "")
    hint = column_hint.lower()
    if unit.startswith("cr"):
        multiplier = 1e7
    elif unit.startswith("la") or unit == "l":
        multiplier = 1e5
    elif unit in ("k", "thousand"):
        multiplier = 1e3
    elif "cr" in hint:
        multiplier = 1e7
    elif "lakh" in hint or "lac" in hint:
        multiplier = 1e5
    elif number < 1000:
        multiplier = 1e5
    else:
        multiplier = 1
    rupees = int(round(number * multiplier))
    return rupees if rupees > 0 else None


def format_price(rupees: int) -> str:
    if rupees >= 10_000_000:
        return f"₹{rupees / 10_000_000:.2f}".rstrip("0").rstrip(".") + " Cr"
    return f"₹{rupees / 100_000:.2f}".rstrip("0").rstrip(".") + " Lakhs"


def parse_bhk(value: Any) -> int:
    text = str(value or "").lower()
    if any(k in text for k in ("studio", "1rk", "1 rk")):
        return 1
    match = re.search(r"\d+(?:\.\d+)?", text)
    return int(float(match.group(0))) if match else 0


def parse_status(value: Any) -> str:
    key = _norm(value)
    if not key:
        return "AVAILABLE"
    for status, words in STATUS_MAP.items():
        if key in words or any(key.startswith(w) for w in words if len(w) > 3):
            return status
    return "AVAILABLE"


def parse_amenities(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [part.strip() for part in re.split(r"[,;|\n]", str(value or "")) if part.strip()]


# ----------------------------------------------------------------------
# Mapping
# ----------------------------------------------------------------------

def detect_mapping(columns: List[str]) -> Dict[str, str]:
    """Guesses which source column holds each property field from the column names."""
    normalized = {col: _norm(col) for col in columns}
    mapping: Dict[str, str] = {}
    used = set()
    for field, synonyms in FIELD_SYNONYMS.items():
        exact = [c for c, n in normalized.items() if n in synonyms and c not in used]
        partial = [c for c, n in normalized.items() if c not in used and any(s in n for s in synonyms if len(s) > 3)]
        choice = (exact or partial or [None])[0]
        if choice:
            mapping[field] = choice
            used.add(choice)
    return mapping


def map_row(row: Dict[str, Any], mapping: Dict[str, str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Returns (property fields, None) or (None, reason it was skipped)."""
    def get(field):
        column = mapping.get(field)
        return row.get(column) if column else None

    project = str(get("project_name") or "").strip()
    location = str(get("location") or "").strip()
    price = parse_price(get("price"), mapping.get("price", ""))
    missing = [f for f, v in (("project_name", project), ("location", location), ("price", price)) if not v]
    if missing:
        return None, f"missing {', '.join(missing)}"

    bhk = parse_bhk(get("bhk"))
    external_id = str(get("external_id") or "").strip()
    if not external_id:
        # No ID column: identify the listing by its descriptive fields
        external_id = "auto_" + hashlib.sha1(f"{_norm(project)}|{_norm(location)}|{bhk}".encode()).hexdigest()[:16]

    mapped_columns = {c for c in mapping.values() if c}
    extra = {k: v for k, v in row.items() if k not in mapped_columns and v not in (None, "")}
    return {
        "external_id": external_id,
        "project_name": project,
        "location": location,
        "price": price,
        "price_display": format_price(price),
        "bhk": bhk,
        "property_type": str(get("property_type") or "").strip() or "Apartment",
        "status": parse_status(get("status")),
        "amenities": parse_amenities(get("amenities")),
        "extra": extra,
    }, None


# ----------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------

def google_sheet_csv_url(sheet_url: str) -> str:
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", sheet_url or "")
    if not match:
        raise InventorySyncError("That doesn't look like a Google Sheets link.")
    gid = re.search(r"[#&?]gid=(\d+)", sheet_url)
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv&gid={gid.group(1) if gid else '0'}"


def _flatten(item: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key, value in item.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, f"{name}."))
        else:
            flat[name] = value
    return flat


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=FETCH_TIMEOUT_S, follow_redirects=True)


def fetch_rows(source: InventorySource) -> List[Dict[str, Any]]:
    config = source.config or {}
    with _http_client() as client:
        if source.type == "GOOGLE_SHEET":
            response = client.get(google_sheet_csv_url(config.get("sheet_url", "")))
            if response.status_code >= 400 or "text/html" in response.headers.get("content-type", ""):
                raise InventorySyncError(
                    "Couldn't read the sheet. Share it as 'Anyone with the link can view' and use the sheet's link."
                )
            reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
            return [{(k or "").strip(): (v or "").strip() for k, v in row.items() if k} for row in reader]

        if source.type == "API":
            response = client.get(config.get("url", ""), headers=config.get("headers") or {})
            if response.status_code >= 400:
                raise InventorySyncError(f"API returned HTTP {response.status_code}.")
            try:
                data: Any = response.json()
            except ValueError:
                raise InventorySyncError("API response isn't JSON.")
            for part in [p for p in (config.get("items_path") or "").split(".") if p]:
                data = data.get(part) if isinstance(data, dict) else None
            if not isinstance(data, list):
                raise InventorySyncError("Couldn't find a list of properties in the API response (check items path).")
            return [_flatten(item) for item in data if isinstance(item, dict)]

    raise InventorySyncError(f"Unknown inventory source type '{source.type}'.")


def preview(source: InventorySource) -> Dict[str, Any]:
    rows = fetch_rows(source)
    columns = list(rows[0].keys()) if rows else []
    mapping = source.field_mapping or detect_mapping(columns)
    mapped = []
    for row in rows[:PREVIEW_ROWS]:
        fields, reason = map_row(row, mapping)
        mapped.append({"row": row, "property": fields, "skipped_reason": reason})
    return {"columns": columns, "mapping": mapping, "detected_mapping": detect_mapping(columns), "total_rows": len(rows), "rows": mapped}


# ----------------------------------------------------------------------
# Sync
# ----------------------------------------------------------------------

def sync_source(db: Session, source: InventorySource, rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Upserts the source's rows into `properties` (matched by external id), marks listings that
    disappeared from the source as UNAVAILABLE, and records the outcome on the source.
    On any failure the existing inventory is left untouched.
    """
    now = datetime.now(timezone.utc)

    def fail(message: str, exc: Exception) -> None:
        source.last_status = "ERROR"
        source.last_error = message[:1000]
        source.last_synced_at = now
        db.commit()
        logger.warning(f"Inventory source {source.id} sync failed: {message}")
        raise InventorySyncError(message) from exc

    # 1. Fetch and map: nothing is written if this fails
    try:
        rows = fetch_rows(source) if rows is None else rows
        mapping = source.field_mapping or detect_mapping(list(rows[0].keys()) if rows else [])
        mapped: Dict[str, Dict[str, Any]] = {}
        skipped = 0
        for row in rows:
            fields, _ = map_row(row, mapping)
            if not fields or fields["external_id"] in mapped:
                skipped += 1
                continue
            mapped[fields["external_id"]] = fields
        if not mapped:
            raise InventorySyncError("No usable rows found (need at least project, location and price).")
    except Exception as e:
        fail(str(e) if isinstance(e, InventorySyncError) else f"{type(e).__name__}: {e}", e)

    # 2. Apply: all-or-nothing
    try:
        existing = {
            (p.meta or {}).get("external_id"): p
            for p in db.query(Property).filter(Property.client_id == source.client_id).all()
            if (p.meta or {}).get("source_id") == source.id
        }
        added = updated = unavailable = 0
        for external_id, fields in mapped.items():
            meta = {"external_id": external_id, "source_id": source.id, "extra": fields["extra"]}
            values = {k: fields[k] for k in ("project_name", "location", "price", "price_display", "bhk", "property_type", "status", "amenities")}
            prop = existing.get(external_id)
            if prop is None:
                db.add(Property(client_id=source.client_id, meta=meta, last_synced_at=now, **values))
                added += 1
                continue
            changed = any(getattr(prop, k) != v for k, v in values.items()) or (prop.meta or {}) != meta
            for k, v in values.items():
                setattr(prop, k, v)
            prop.meta = meta
            prop.last_synced_at = now
            updated += int(changed)
        for external_id, prop in existing.items():
            if external_id not in mapped and prop.status != "UNAVAILABLE":
                prop.status = "UNAVAILABLE"
                prop.last_synced_at = now
                unavailable += 1

        result = {"rows": len(rows), "added": added, "updated": updated, "unavailable": unavailable, "skipped": skipped}
        source.last_status = "OK"
        source.last_error = None
        source.last_result = result
        source.last_synced_at = now
        if not source.field_mapping:
            source.field_mapping = mapping
        db.commit()
        logger.info(f"Inventory source {source.id} synced: {result}")
        return result
    except Exception as e:
        db.rollback()
        fail(f"Saving inventory failed: {type(e).__name__}: {e}", e)


def due_sources(db: Session) -> List[InventorySource]:
    now = datetime.now(timezone.utc)
    due = []
    for source in db.query(InventorySource).filter(InventorySource.enabled == True).all():  # noqa: E712
        last = source.last_synced_at
        if last is not None and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last is None or (now - last).total_seconds() >= max(1, source.sync_interval_minutes) * 60:
            due.append(source)
    return due


def run_due_syncs(session_factory) -> None:
    """Syncs every enabled source whose interval has elapsed (called by the scheduler)."""
    db = session_factory()
    try:
        for source in due_sources(db):
            try:
                sync_source(db, source)
            except InventorySyncError:
                pass
    finally:
        db.close()
