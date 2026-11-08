"""When MongoDB can't be reached, clients get a plain message and server details stay in the log."""
import logging

import pytest

from app.core.config import settings
from app.db import mongo
from app.services import agent_requests
from test_portal import _client_headers

SERVER_DETAILS = "SSL handshake failed: ac-secret-shard-00-00.example.mongodb.net:27017"


class UnreachableMongo:
    def __getitem__(self, _name):
        return self

    def create_index(self, *_args, **_kwargs):
        raise RuntimeError(SERVER_DETAILS)

    def close(self):
        pass


def test_unreachable_database_hides_server_details_from_the_message(monkeypatch, caplog):
    monkeypatch.setattr(mongo, "_client", None)
    monkeypatch.setattr(mongo, "_connect", UnreachableMongo)
    with caplog.at_level(logging.ERROR, logger="choranta.db.mongo"), pytest.raises(mongo.KnowledgeStoreUnavailable) as failure:
        mongo.database()
    assert "temporarily unavailable" in str(failure.value)
    assert "mongodb.net" not in str(failure.value)
    assert SERVER_DETAILS in caplog.text


def test_connection_is_tried_again_after_a_failure(monkeypatch):
    """Once Atlas lets the server in, knowledge works again without a restart."""
    monkeypatch.setattr(mongo, "_client", None)
    monkeypatch.setattr(mongo, "_connect", UnreachableMongo)
    with pytest.raises(mongo.KnowledgeStoreUnavailable):
        mongo.database()
    assert mongo._client is None


def test_employees_page_still_loads_and_sending_the_form_explains(client, auth_headers, monkeypatch):
    """The create form's options must not fail with MongoDB down; sending the form gets a plain 503, not a 500."""
    company = client.post("/api/clients", headers=auth_headers, json={"name": "Mongo Down Dental", "business_type": "OTHER"})
    assert company.status_code == 201, company.text
    portal = _client_headers(client, auth_headers, company.json()["id"], "owner@mongo-down.example.com")
    monkeypatch.setattr(settings, "AGENT_REQUEST_REQUIRES_DOCUMENTS", True)
    monkeypatch.setattr(settings, "MONGODB_URI", "mongodb://unreachable.example.com")
    monkeypatch.setattr(mongo, "_client", None)
    monkeypatch.setattr(mongo, "_connect", UnreachableMongo)
    monkeypatch.setattr(agent_requests, "has_paid", lambda db, client_id: True)

    options = client.get("/api/portal/agent-requests/options", headers=portal)
    assert options.status_code == 200, options.text
    assert options.json()["needs_documents"] is False

    created = client.post("/api/portal/agent-requests", headers=portal, json={
        "company_name": "Mongo Down Dental", "business_type": "CLINIC", "languages": ["en-IN"], "name": "Meera"})
    assert created.status_code == 503, created.text
    assert "temporarily unavailable" in created.json()["error"]
    assert "mongodb.net" not in created.text


def test_files_are_not_required_while_the_requirement_is_off(client, auth_headers, monkeypatch):
    """Switched off, a first request needs no files and doesn't touch MongoDB, so an outage can't block it."""
    company = client.post("/api/clients", headers=auth_headers, json={"name": "No Files Dental", "business_type": "OTHER"})
    assert company.status_code == 201, company.text
    portal = _client_headers(client, auth_headers, company.json()["id"], "owner@no-files.example.com")
    monkeypatch.setattr(settings, "AGENT_REQUEST_REQUIRES_DOCUMENTS", False)
    monkeypatch.setattr(settings, "MONGODB_URI", "mongodb://unreachable.example.com")
    monkeypatch.setattr(mongo, "_client", None)
    monkeypatch.setattr(mongo, "_connect", UnreachableMongo)
    monkeypatch.setattr(agent_requests, "has_paid", lambda db, client_id: True)

    assert client.get("/api/portal/agent-requests/options", headers=portal).json()["needs_documents"] is False
    created = client.post("/api/portal/agent-requests", headers=portal, json={
        "company_name": "No Files Dental", "business_type": "CLINIC", "languages": ["en-IN"], "name": "Meera"})
    assert created.status_code == 201, created.text
