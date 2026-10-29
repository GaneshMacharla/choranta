"""Each client has its own knowledge base (MongoDB); its AI employees answer from it."""
import io
from types import SimpleNamespace

import docx
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.client import Client
from app.models.knowledge_source import KnowledgeSource
from app.runtime.knowledge import build_knowledge
from app.services import knowledge_store
from test_portal import _client_headers


def _client(db: Session, name: str, business_type: str = "COACHING") -> Client:
    c = Client(id=generate_unique_id("cli_"), name=name, business_type=business_type)
    db.add(c)
    db.commit()
    return c


def _docx(text: str) -> bytes:
    document = docx.Document()
    document.add_paragraph(text)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _portal(client: TestClient, auth_headers: dict, c: Client) -> dict:
    return _client_headers(client, auth_headers, c.id, f"owner-{c.id}@example.com")


def test_client_adds_knowledge_and_the_team_reviews_it(client: TestClient, auth_headers: dict, db: Session):
    c = _client(db, "KB Academy")
    h = _portal(client, auth_headers, c)
    base, admin = "/api/portal/knowledge", f"/api/clients/{c.id}/knowledge"
    created = client.post(base, headers=h, json={"name": "Fees", "type": "FAQ", "content": "Q: Fee? A: 25,000 rupees."})
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["client_id"] == c.id and entry["metadata"]["added_by"]["role"] == "CLIENT"

    updated = client.put(f"{base}/{entry['id']}", headers=h,
                         json={"name": "Fees 2026", "type": "FAQ", "content": "Q: Fee? A: 30,000 rupees."})
    assert updated.json()["content"].endswith("30,000 rupees.")

    upload = client.post(f"{base}/upload", headers=h, files=[
        ("files", ("batches.txt", io.BytesIO(b"Snowflake batch: Mon-Fri 7 PM."), "text/plain")),
        ("files", ("brochure.docx", io.BytesIO(_docx("Located near Ameerpet metro.")),
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
        ("files", ("fee-chart.png", io.BytesIO(b"\x89PNG fake"), "image/png")),
    ])
    assert upload.status_code == 201, upload.text
    docs = {d["name"]: d for d in upload.json()}
    # Any file is kept as it is; nothing is read from it (the team reads it themselves)
    assert all(d["content"] == "" and "text_status" not in d["metadata"] for d in docs.values())

    # The team sees it all, downloads documents and deletes what's wrong
    assert [k["name"] for k in client.get(admin, headers=auth_headers).json()] == ["Fees 2026", "batches.txt", "brochure.docx", "fee-chart.png"]
    download = client.get(f"{admin}/{docs['fee-chart.png']['id']}/download", headers=auth_headers)
    assert download.status_code == 200 and download.content == b"\x89PNG fake"
    assert "fee-chart.png" in download.headers["content-disposition"]
    assert client.get(f"{admin}/{entry['id']}/download", headers=auth_headers).status_code == 404  # notes have no file

    assert client.delete(f"{admin}/{entry['id']}", headers=auth_headers).status_code == 204
    assert client.delete(f"{admin}/{docs['fee-chart.png']['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"{admin}/{docs['fee-chart.png']['id']}/download", headers=auth_headers).status_code == 404
    assert len(client.get(base, headers=h).json()) == 2


def test_only_the_client_adds_knowledge(client: TestClient, auth_headers: dict, db: Session):
    c = _client(db, "Review Only")
    admin = f"/api/clients/{c.id}/knowledge"
    assert client.post(admin, headers=auth_headers, json={"name": "x", "type": "NOTES", "content": "y"}).status_code == 405
    assert client.put(f"{admin}/details", headers=auth_headers, json={"fields": {}}).status_code == 405
    up = client.post(f"{admin}/upload", headers=auth_headers, files=[("files", ("a.txt", io.BytesIO(b"a"), "text/plain"))])
    assert up.status_code in (404, 405)


def test_upload_limits(client: TestClient, auth_headers: dict, db: Session, monkeypatch):
    c = _client(db, "Small Storage")
    base, auth_headers = "/api/portal/knowledge/upload", _portal(client, auth_headers, c)
    monkeypatch.setattr(settings, "KNOWLEDGE_MAX_FILE_MB", 1)
    big = client.post(base, headers=auth_headers, files=[("files", ("big.pdf", io.BytesIO(b"x" * (1024 * 1024 + 1)), "application/pdf"))])
    assert big.status_code == 413
    monkeypatch.setattr(settings, "KNOWLEDGE_CLIENT_QUOTA_MB", 1)
    ok = client.post(base, headers=auth_headers, files=[("files", ("a.txt", io.BytesIO(b"a" * 600_000), "text/plain"))])
    assert ok.status_code == 201
    over = client.post(base, headers=auth_headers, files=[("files", ("b.txt", io.BytesIO(b"b" * 600_000), "text/plain"))])
    assert over.status_code == 413


def test_client_fills_details_and_team_sees_the_gaps(client: TestClient, auth_headers: dict, db: Session):
    c = _client(db, "Smile Dental", business_type="CLINIC")
    h = _client_headers(client, auth_headers, c.id, f"owner-{c.id}@dental.example.com")

    sheet = client.get("/api/portal/knowledge/overview", headers=h).json()
    keys = [f["key"] for f in sheet["fields"]]
    assert {"address", "owner", "hours", "doctors", "consultation_fee"} <= set(keys)
    assert "courses" not in keys  # coaching fields aren't asked of a clinic
    assert "Full address & landmark" in sheet["gaps"]

    saved = client.put("/api/portal/knowledge/details", headers=h, json={"fields": {
        "business_name": {"value": "Smile Dental Care"},
        "address": {"value": "Road 12, Kukatpally, Hyderabad 500072, opp. Metro pillar 801"},
        "doctors": {"in_documents": True},
        "made_up": {"value": "dropped"},
    }})
    assert saved.status_code == 200, saved.text
    assert "Full address & landmark: Road 12, Kukatpally" in saved.json()["content"]
    assert "dropped" not in saved.json()["content"]

    admin_view = client.get(f"/api/clients/{c.id}/knowledge/overview", headers=auth_headers).json()
    states = {f["key"]: f["state"] for f in admin_view["fields"]}
    assert states["address"] == "FILLED" and states["doctors"] == "IN_DOCUMENTS" and states["hours"] == "MISSING"
    assert "Full address & landmark" not in admin_view["gaps"] and "Working days & hours" in admin_view["gaps"]

    # The client adds a note and uploads a document; the team sees and can delete both
    note = client.post("/api/portal/knowledge", headers=h, json={"name": "Parking", "type": "NOTES", "content": "Basement parking."})
    assert note.status_code == 201
    up = client.post("/api/portal/knowledge/upload", headers=h,
                     files=[("files", ("timings.txt", io.BytesIO(b"Dr. Rao: 10am-2pm"), "text/plain"))])
    assert up.status_code == 201
    names = [e["name"] for e in client.get(f"/api/clients/{c.id}/knowledge/overview", headers=auth_headers).json()["entries"]]
    assert names == ["Parking", "timings.txt"]
    assert client.delete(f"/api/clients/{c.id}/knowledge/{note.json()['id']}", headers=auth_headers).status_code == 204


def test_knowledge_stays_with_its_client(client: TestClient, auth_headers: dict, db: Session):
    a, b = _client(db, "Client A"), _client(db, "Client B")
    entry = client.post("/api/portal/knowledge", headers=_portal(client, auth_headers, a),
                        json={"name": "A notes", "type": "NOTES", "content": "A only"}).json()
    assert client.get(f"/api/clients/{b.id}/knowledge", headers=auth_headers).json() == []
    assert client.delete(f"/api/clients/{b.id}/knowledge/{entry['id']}", headers=auth_headers).status_code == 404
    assert client.get(f"/api/clients/{b.id}/knowledge/{entry['id']}/download", headers=auth_headers).status_code == 404

    hb = _portal(client, auth_headers, b)
    assert client.delete(f"/api/portal/knowledge/{entry['id']}", headers=hb).status_code == 404

    agent = client.post("/api/agents", headers=auth_headers,
                        json={"client_id": b.id, "name": "Priya", "role": "Receptionist"}).json()
    res = client.post(f"/api/agents/{agent['id']}/knowledge/{entry['id']}", headers=auth_headers)
    assert res.status_code == 400  # another client's knowledge can't be attached


def test_new_knowledge_is_ticked_for_the_clients_ai_employees_and_used_on_calls(client: TestClient, auth_headers: dict,
                                                                                db: Session):
    c = _client(db, "Ticks Academy")
    agent = client.post("/api/agents", headers=auth_headers,
                        json={"client_id": c.id, "name": "Anjali", "role": "Receptionist"}).json()
    entry = client.post("/api/portal/knowledge", headers=_portal(client, auth_headers, c),
                        json={"name": "Fees", "type": "NOTES", "content": "Java course fee is 18,500 rupees."}).json()

    attached = client.get(f"/api/agents/{agent['id']}/knowledge", headers=auth_headers).json()
    assert entry["id"] in [k["id"] for k in attached]
    block, _ = build_knowledge(db, agent["id"], SimpleNamespace(knowledge=SimpleNamespace(sources=[])))
    assert "18,500 rupees" in block

    # Unticked in the Build tab: the AI employee stops using it
    assert client.delete(f"/api/agents/{agent['id']}/knowledge/{entry['id']}", headers=auth_headers).status_code == 200
    block, _ = build_knowledge(db, agent["id"], SimpleNamespace(knowledge=SimpleNamespace(sources=[])))
    assert "18,500 rupees" not in block
    assert knowledge_store.get_entry(entry["id"]) is not None  # still in the client's knowledge base


def test_documents_are_for_the_team_and_never_given_to_ai_employees(client: TestClient, auth_headers: dict, db: Session):
    c = _client(db, "Docs Academy")
    agent = client.post("/api/agents", headers=auth_headers,
                        json={"client_id": c.id, "name": "Kiran", "role": "Receptionist"}).json()
    doc = client.post("/api/portal/knowledge/upload", headers=_portal(client, auth_headers, c),
                      files=[("files", ("fees.txt", io.BytesIO(b"Java course fee is 18,500 rupees."), "text/plain"))]).json()[0]
    assert knowledge_store.get_entry(doc["id"]).agent_ids == []  # not ticked for the client's AI employees
    assert client.post(f"/api/agents/{agent['id']}/knowledge/{doc['id']}", headers=auth_headers).status_code >= 400

    # A document ticked before this rule is still not given to the AI employee
    knowledge_store.attach(agent["id"], doc["id"])
    assert doc["id"] not in [k["id"] for k in client.get(f"/api/agents/{agent['id']}/knowledge", headers=auth_headers).json()]
    block, _ = build_knowledge(db, agent["id"], SimpleNamespace(knowledge=SimpleNamespace(sources=[doc["id"]])))
    assert "18,500" not in block


def test_older_sql_client_knowledge_moves_to_mongo_with_its_ticks(client: TestClient, auth_headers: dict, db: Session):
    c = _client(db, "Legacy Academy")
    agent = client.post("/api/agents", headers=auth_headers,
                        json={"client_id": c.id, "name": "Old", "role": "Receptionist"}).json()
    old_id = generate_unique_id("knw", 12)
    db.add(KnowledgeSource(id=old_id, name="Old notes", type="NOTES", status="READY", content="Since 1999.",
                           client_id=c.id, meta={}))
    db.commit()
    client.post(f"/api/agents/{agent['id']}/knowledge/{old_id}", headers=auth_headers)

    assert knowledge_store.migrate_sql_client_knowledge(db) >= 1
    moved = knowledge_store.get_entry(old_id)
    assert moved.content == "Since 1999." and agent["id"] in moved.agent_ids
    assert db.get(KnowledgeSource, old_id) is None
