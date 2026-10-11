import asyncio
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin, require_operator
from app.models.client import Client
from app.models.inventory_source import InventorySource
from app.models.property import Property
from app.models.user import User
from app.services import inventory_sync
from app.services.inventory_sync import InventorySyncError

router = APIRouter(prefix="/clients/{client_id}", tags=["Property Inventory"])


class InventorySourceRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: Literal["GOOGLE_SHEET", "API"]
    config: Dict[str, Any] = Field(default_factory=dict, description="GOOGLE_SHEET: sheet_url; API: url, headers, items_path")
    field_mapping: Dict[str, str] = Field(default_factory=dict, description="Property field -> source column (empty = auto-detect)")
    sync_interval_minutes: int = Field(default=15, ge=5, le=1440)
    enabled: bool = True


class InventorySourceUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    field_mapping: Optional[Dict[str, str]] = None
    sync_interval_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    enabled: Optional[bool] = None


def _client_or_404(db: Session, client_id: str) -> Client:
    client = db.get(Client, client_id)
    if not client:
        raise HTTPException(status_code=404, detail=f"Client '{client_id}' not found.")
    return client


def _source_or_404(db: Session, client_id: str, source_id: str) -> InventorySource:
    source = db.get(InventorySource, source_id)
    if not source or source.client_id != client_id:
        raise HTTPException(status_code=404, detail=f"Inventory source '{source_id}' not found.")
    return source


def _validate_config(source_type: str, config: Dict[str, Any]) -> None:
    if source_type == "GOOGLE_SHEET":
        try:
            inventory_sync.google_sheet_csv_url(config.get("sheet_url", ""))
        except InventorySyncError as e:
            raise HTTPException(status_code=422, detail=str(e))
    elif not str(config.get("url", "")).startswith(("http://", "https://")):
        raise HTTPException(status_code=422, detail="API source needs a url starting with http:// or https://.")


def _source_out(source: InventorySource, db: Session) -> Dict[str, Any]:
    config = dict(source.config or {})
    if config.get("headers"):
        # Never send stored auth headers back to the browser
        config["headers"] = {k: "••••••" for k in config["headers"]}
    count = sum(
        1 for p in db.query(Property).filter(Property.client_id == source.client_id, Property.status != "UNAVAILABLE").all()
        if (p.meta or {}).get("source_id") == source.id
    )
    return {
        "id": source.id,
        "client_id": source.client_id,
        "name": source.name,
        "type": source.type,
        "config": config,
        "field_mapping": source.field_mapping or {},
        "sync_interval_minutes": source.sync_interval_minutes,
        "enabled": source.enabled,
        "last_synced_at": source.last_synced_at.isoformat() if source.last_synced_at else None,
        "last_status": source.last_status,
        "last_error": source.last_error,
        "last_result": source.last_result or {},
        "active_properties": count,
    }


@router.get("/inventory-sources")
def list_sources(client_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_operator)) -> List[Dict[str, Any]]:
    _client_or_404(db, client_id)
    sources = db.query(InventorySource).filter(InventorySource.client_id == client_id).order_by(InventorySource.created_at).all()
    return [_source_out(s, db) for s in sources]


@router.post("/inventory-sources", status_code=status.HTTP_201_CREATED)
def create_source(client_id: str, req: InventorySourceRequest, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    _client_or_404(db, client_id)
    _validate_config(req.type, req.config)
    source = InventorySource(
        client_id=client_id,
        name=req.name,
        type=req.type,
        config=req.config,
        field_mapping=req.field_mapping,
        sync_interval_minutes=req.sync_interval_minutes,
        enabled=req.enabled,
        last_result={},
    )
    db.add(source)
    db.commit()
    return _source_out(source, db)


@router.patch("/inventory-sources/{source_id}")
def update_source(client_id: str, source_id: str, req: InventorySourceUpdate, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    source = _source_or_404(db, client_id, source_id)
    if req.config is not None:
        config = dict(req.config)
        # Masked headers from the UI mean "keep the stored values"
        stored_headers = (source.config or {}).get("headers") or {}
        if isinstance(config.get("headers"), dict):
            config["headers"] = {k: (stored_headers.get(k, "") if v == "••••••" else v) for k, v in config["headers"].items()}
        _validate_config(source.type, config)
        source.config = config
    for field in ("name", "field_mapping", "sync_interval_minutes", "enabled"):
        value = getattr(req, field)
        if value is not None:
            setattr(source, field, value)
    db.commit()
    return _source_out(source, db)


@router.delete("/inventory-sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(client_id: str, source_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    source = _source_or_404(db, client_id, source_id)
    # Its listings stay but are no longer offered by the agent
    for prop in db.query(Property).filter(Property.client_id == client_id).all():
        if (prop.meta or {}).get("source_id") == source.id:
            prop.status = "UNAVAILABLE"
    db.delete(source)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/inventory-sources/{source_id}/preview")
async def preview_source(client_id: str, source_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    """Fetches and maps the first rows without saving anything, to check the column mapping."""
    source = _source_or_404(db, client_id, source_id)
    try:
        return await asyncio.to_thread(inventory_sync.preview, source)
    except InventorySyncError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't fetch the source: {type(e).__name__}")


@router.post("/inventory-sources/{source_id}/sync")
def sync_now(client_id: str, source_id: str, db: Session = Depends(get_db), current_user: User = Depends(require_admin)):
    source = _source_or_404(db, client_id, source_id)
    try:
        inventory_sync.sync_source(db, source)
    except InventorySyncError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _source_out(source, db)


@router.get("/properties")
def list_properties(
    client_id: str,
    include_unavailable: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator)
):
    _client_or_404(db, client_id)
    q = db.query(Property).filter(Property.client_id == client_id)
    if not include_unavailable:
        q = q.filter(Property.status != "UNAVAILABLE")
    props = q.order_by(Property.project_name).limit(500).all()
    return {
        "count": len(props),
        "last_synced_at": max((p.last_synced_at for p in props if p.last_synced_at), default=None),
        "properties": [
            {
                "id": p.id,
                "project_name": p.project_name,
                "location": p.location,
                "bhk": p.bhk,
                "price": p.price,
                "price_display": p.price_display,
                "property_type": p.property_type,
                "status": p.status,
                "amenities": p.amenities or [],
                "details": (p.meta or {}).get("extra", {}),
                "source_id": (p.meta or {}).get("source_id"),
                "last_synced_at": p.last_synced_at,
            }
            for p in props
        ],
    }
