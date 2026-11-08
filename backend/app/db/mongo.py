"""
MongoDB connection for the knowledge base (clients' documents, notes, FAQs and business details).

Everything else lives in the SQL database; knowledge entries point at it by client_id and agent ids.
Collections:
- knowledge_entries: one per note, FAQ, uploaded document or business-details sheet (what AI employees read)
- knowledge_files:   the original bytes of each uploaded document, kept apart so listing entries stays light
"""
import logging
import threading
from typing import Any, Optional

from app.core.config import settings

logger = logging.getLogger("choranta.db.mongo")

ENTRIES = "knowledge_entries"
FILES = "knowledge_files"

_lock = threading.Lock()
_client: Optional[Any] = None


class KnowledgeStoreUnavailable(Exception):
    """MongoDB isn't configured or can't be reached."""


def configured() -> bool:
    return bool((settings.MONGODB_URI or "").strip())


def _connect() -> Any:
    uri = settings.MONGODB_URI.strip()
    if uri.startswith("mongomock://"):
        import mongomock
        return mongomock.MongoClient()
    from pymongo import MongoClient
    return MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000, appname="choranta")


def database() -> Any:
    """The knowledge database; indexes are created on first use."""
    global _client
    if not configured():
        raise KnowledgeStoreUnavailable("Knowledge storage isn't set up yet (MONGODB_URI is empty).")
    with _lock:
        if _client is None:
            client = _connect()
            db = client[settings.MONGODB_DB]
            try:
                db[ENTRIES].create_index([("client_id", 1), ("created_at", 1)])
                db[ENTRIES].create_index("agent_ids")
                db[FILES].create_index("entry_id")
                db[FILES].create_index("client_id")
            except Exception as exc:
                client.close()
                # This message reaches clients; the server names and network details stay in the log
                logger.error("Couldn't reach MongoDB: %s", exc)
                raise KnowledgeStoreUnavailable("Knowledge is temporarily unavailable. Please try again in a few minutes.") from exc
            _client = client
    return _client[settings.MONGODB_DB]


def reset() -> None:
    """Drops the cached connection (tests, or after MONGODB_URI changes)."""
    global _client
    with _lock:
        if _client is not None:
            _client.close()
        _client = None
