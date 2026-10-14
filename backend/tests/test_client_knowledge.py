"""Each client has its own knowledge base; its AI employees answer from it."""
import io

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import generate_unique_id
from app.models.client import Client


def _client(db: Session, name: str) -> Client:
    c = Client(id=generate_unique_id("cli_"), name=name, business_type="COACHING")
    db.add(c)
    db.commit()
    return c


def test_admin_manages_a_clients_knowledge_base(client: TestClient, auth_headers: dict, db: Session):
    c = _client(db, "KB Academy")
    base = f"/api/clients/{c.id}/knowledge"
    created = client.post(base, headers=auth_headers, json={"name": "Fees", "type": "FAQ",
                                                           "content": "Q: Fee? A: 25,000 rupees."})
    assert created.status_code == 201, created.text
    entry = created.json()
    assert entry["client_id"] == c.id

    listed = client.get(base, headers=auth_headers).json()
    assert [k["name"] for k in listed] == ["Fees"]

    updated = client.put(f"{base}/{entry['id']}", headers=auth_headers,
                         json={"name": "Fees 2026", "type": "FAQ", "content": "Q: Fee? A: 30,000 rupees."})
    assert updated.json()["content"].endswith("30,000 rupees.")

    upload = client.post(f"{base}/upload", headers=auth_headers,
                         files={"file": ("batches.txt", io.BytesIO(b"Snowflake batch: Mon-Fri 7 PM."), "text/plain")})
    assert upload.status_code == 201, upload.text
    assert "Snowflake batch" in upload.json()["content"]
    bad = client.post(f"{base}/upload", headers=auth_headers,
                      files={"file": ("photo.png", io.BytesIO(b"\x89PNG"), "image/png")})
    assert bad.status_code == 422

    assert client.delete(f"{base}/{entry['id']}", headers=auth_headers).status_code == 204
    assert len(client.get(base, headers=auth_headers).json()) == 1


def test_knowledge_stays_with_its_client(client: TestClient, auth_headers: dict, db: Session):
    a, b = _client(db, "Client A"), _client(db, "Client B")
    entry = client.post(f"/api/clients/{a.id}/knowledge", headers=auth_headers,
                        json={"name": "A notes", "type": "NOTES", "content": "A only"}).json()
    assert client.get(f"/api/clients/{b.id}/knowledge", headers=auth_headers).json() == []
    assert client.delete(f"/api/clients/{b.id}/knowledge/{entry['id']}", headers=auth_headers).status_code == 404

    agent = client.post("/api/agents", headers=auth_headers,
                        json={"client_id": b.id, "name": "Priya", "role": "Receptionist"}).json()
    res = client.post(f"/api/agents/{agent['id']}/knowledge/{entry['id']}", headers=auth_headers)
    assert res.status_code == 400  # another client's knowledge can't be attached
