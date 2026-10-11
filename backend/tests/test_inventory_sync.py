import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import generate_unique_id
from app.models.client import Client
from app.models.inventory_source import InventorySource
from app.models.property import Property
from app.runtime.tools.executor import ToolExecutor
from app.services import inventory_sync
from app.services.inventory_sync import (
    InventorySyncError, detect_mapping, format_price, google_sheet_csv_url, parse_bhk, parse_price, parse_status,
    sync_source,
)

SHEET_URL = "https://docs.google.com/spreadsheets/d/1AbC_dEf-123/edit#gid=456"


# ---------------------------------------------------------------- normalizers

@pytest.mark.parametrize("value,hint,expected", [
    ("₹85 Lakhs", "", 8_500_000),
    ("85L", "", 8_500_000),
    ("1.2 Cr", "", 12_000_000),
    ("1.25 crores", "", 12_500_000),
    ("1,20,00,000", "", 12_000_000),
    ("85-90 L", "", 8_500_000),
    ("85", "", 8_500_000),             # bare small number = lakhs
    ("1.1", "Price (Cr)", 11_000_000),  # unit from the column name
    (9500000, "", 9_500_000),
    ("on request", "", None),
])
def test_parse_price(value, hint, expected):
    assert parse_price(value, hint) == expected


def test_format_parse_bhk_status():
    assert format_price(8_500_000) == "₹85 Lakhs"
    assert format_price(12_500_000) == "₹1.25 Cr"
    assert parse_bhk("2 BHK") == 2 and parse_bhk("3.5") == 3 and parse_bhk("Studio") == 1 and parse_bhk("") == 0
    assert parse_status("Available") == "AVAILABLE"
    assert parse_status("Sold Out") == "SOLD"
    assert parse_status("On Hold") == "UNDER_OFFER"
    assert parse_status("") == "AVAILABLE"


def test_detect_mapping_from_typical_sheet_headers():
    mapping = detect_mapping(["Unit No", "Project Name", "Locality", "Price (Lakhs)", "Configuration", "Availability", "Possession"])
    assert mapping == {
        "external_id": "Unit No",
        "project_name": "Project Name",
        "location": "Locality",
        "price": "Price (Lakhs)",
        "bhk": "Configuration",
        "status": "Availability",
    }


def test_google_sheet_link_becomes_csv_export():
    assert google_sheet_csv_url(SHEET_URL) == "https://docs.google.com/spreadsheets/d/1AbC_dEf-123/export?format=csv&gid=456"
    with pytest.raises(InventorySyncError):
        google_sheet_csv_url("https://example.com/sheet")


# ---------------------------------------------------------------- sync

@pytest.fixture
def client_rec(db: Session) -> Client:
    client = Client(id=generate_unique_id("cli_"), name="Skyline Realty", business_type="REAL_ESTATE")
    db.add(client)
    db.commit()
    return client


def _serve(monkeypatch, handler):
    monkeypatch.setattr(
        inventory_sync, "_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True),
    )


def _csv_response(text: str) -> httpx.Response:
    return httpx.Response(200, content=text.encode(), headers={"content-type": "text/csv"})


def _sheet_source(db: Session, client: Client) -> InventorySource:
    source = InventorySource(client_id=client.id, name="Inventory sheet", type="GOOGLE_SHEET",
                             config={"sheet_url": SHEET_URL}, field_mapping={}, last_result={})
    db.add(source)
    db.commit()
    return source


def _props(db: Session, client: Client):
    return {p.meta["external_id"]: p for p in db.query(Property).filter(Property.client_id == client.id).all()}


def test_sheet_sync_adds_updates_and_retires_listings(db: Session, client_rec, monkeypatch):
    sheet = {"csv": (
        "Unit No,Project,Location,Price,BHK,Status,Possession\n"
        "A-101,Skyline Heights,Whitefield,85 L,2 BHK,Available,Dec 2027\n"
        "B-202,Skyline Heights,Whitefield,1.2 Cr,3 BHK,Available,Ready\n"
    )}
    _serve(monkeypatch, lambda request: _csv_response(sheet["csv"]))
    source = _sheet_source(db, client_rec)

    assert sync_source(db, source) == {"rows": 2, "added": 2, "updated": 0, "unavailable": 0, "skipped": 0}
    props = _props(db, client_rec)
    assert props["A-101"].price == 8_500_000 and props["A-101"].bhk == 2
    assert props["A-101"].meta["extra"] == {"Possession": "Dec 2027"}
    assert source.last_status == "OK" and source.field_mapping["external_id"] == "Unit No"

    # Next day: A-101 price changes, B-202 is removed from the sheet
    sheet["csv"] = "Unit No,Project,Location,Price,BHK,Status,Possession\nA-101,Skyline Heights,Whitefield,88 L,2 BHK,Available,Dec 2027\n"
    assert sync_source(db, source) == {"rows": 1, "added": 0, "updated": 1, "unavailable": 1, "skipped": 0}
    props = _props(db, client_rec)
    assert props["A-101"].price == 8_800_000 and props["A-101"].price_display == "₹88 Lakhs"
    assert props["B-202"].status == "UNAVAILABLE"


def test_private_sheet_or_failure_keeps_existing_inventory(db: Session, client_rec, monkeypatch):
    _serve(monkeypatch, lambda request: _csv_response("Project,Location,Price\nSkyline,HSR Layout,95 L\n"))
    source = _sheet_source(db, client_rec)
    sync_source(db, source)

    # Sheet made private: Google returns an HTML sign-in page
    _serve(monkeypatch, lambda request: httpx.Response(200, content=b"<html>", headers={"content-type": "text/html"}))
    with pytest.raises(InventorySyncError, match="Anyone with the link"):
        sync_source(db, source)
    db.refresh(source)
    assert source.last_status == "ERROR"
    assert [p.status for p in _props(db, client_rec).values()] == ["AVAILABLE"]


def test_api_sync_with_items_path_and_auth(db: Session, client_rec, monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": {"listings": [
            {"id": 7, "name": "Lake View", "address": {"area": "Hebbal"}, "price": 15000000, "bhk": 3, "status": "Sold"},
        ]}})

    _serve(monkeypatch, handler)
    source = InventorySource(client_id=client_rec.id, name="CRM", type="API", last_result={},
                             config={"url": "https://crm.example.com/listings", "headers": {"Authorization": "Bearer t0k"},
                                     "items_path": "data.listings"},
                             field_mapping={"external_id": "id", "project_name": "name", "location": "address.area",
                                            "price": "price", "bhk": "bhk", "status": "status"})
    db.add(source)
    db.commit()
    sync_source(db, source)
    prop = _props(db, client_rec)["7"]
    assert seen["auth"] == "Bearer t0k"
    assert (prop.project_name, prop.location, prop.price_display, prop.status) == ("Lake View", "Hebbal", "₹1.5 Cr", "SOLD")


# ---------------------------------------------------------------- agent tool

def test_search_properties_only_returns_the_callers_inventory(db: Session, client_rec, monkeypatch):
    import app.db.session as db_session
    # The tool opens its own session; bind it to the test's connection so it sees the test data
    monkeypatch.setattr(db_session, "SessionLocal", lambda: Session(bind=db.get_bind()))

    other = Client(id=generate_unique_id("cli_"), name="Other Realty", business_type="REAL_ESTATE")
    db.add(other)
    db.add(Property(client_id=client_rec.id, project_name="Ours", location="Whitefield", price=8_000_000,
                    price_display="₹80 Lakhs", bhk=2, status="AVAILABLE", amenities=[], meta={}))
    db.add(Property(client_id=other.id, project_name="Theirs", location="Whitefield", price=7_000_000,
                    price_display="₹70 Lakhs", bhk=2, status="AVAILABLE", amenities=[], meta={}))
    db.commit()

    executor = ToolExecutor()
    result = executor.execute_tool("c1", "search_properties", {"location": "Whitefield"}, ["search_properties"], client_id=client_rec.id)
    names = [p["project_name"] for p in result.data["properties"]]
    assert names == ["Ours"]
    assert "as_of" in result.data

    # A client with inventory but no match gets an honest empty result, not demo listings
    none = executor.execute_tool("c2", "search_properties", {"location": "Mysuru"}, ["search_properties"], client_id=client_rec.id)
    assert none.data == {"count": 0, "properties": []}


# ---------------------------------------------------------------- API

def test_inventory_api_permissions_and_preview(client: TestClient, auth_headers: dict, operator_headers: dict, client_rec, monkeypatch):
    _serve(monkeypatch, lambda request: _csv_response("Project,Location,Price\nSkyline,HSR Layout,95 L\n"))
    body = {"name": "Sheet", "type": "GOOGLE_SHEET", "config": {"sheet_url": SHEET_URL}}

    assert client.post(f"/api/clients/{client_rec.id}/inventory-sources", headers=operator_headers, json=body).status_code == 403
    bad = {**body, "config": {"sheet_url": "https://example.com"}}
    assert client.post(f"/api/clients/{client_rec.id}/inventory-sources", headers=auth_headers, json=bad).status_code == 422

    created = client.post(f"/api/clients/{client_rec.id}/inventory-sources", headers=auth_headers, json=body).json()
    preview = client.post(f"/api/clients/{client_rec.id}/inventory-sources/{created['id']}/preview", headers=auth_headers).json()
    assert preview["rows"][0]["property"]["price"] == 9_500_000
    assert client.get(f"/api/clients/{client_rec.id}/properties", headers=operator_headers).json()["count"] == 0  # preview saved nothing

    synced = client.post(f"/api/clients/{client_rec.id}/inventory-sources/{created['id']}/sync", headers=auth_headers).json()
    assert synced["last_status"] == "OK" and synced["active_properties"] == 1
    listed = client.get(f"/api/clients/{client_rec.id}/inventory-sources", headers=operator_headers).json()
    assert listed[0]["last_result"]["added"] == 1
