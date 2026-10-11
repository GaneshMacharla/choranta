from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey, JSON
from app.db.session import Base
from app.core.security import generate_unique_id


class InventorySource(Base):
    """
    Where a client maintains its property inventory (Google Sheet or CRM/website API).
    Choranta syncs it into the `properties` table on a schedule, so agents always quote
    current prices and availability without anyone editing the knowledge base.
    """
    __tablename__ = "inventory_sources"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("invsrc_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(32), nullable=False)  # GOOGLE_SHEET, API
    config = Column(JSON, nullable=False, default=dict)  # sheet_url | url, headers, items_path
    field_mapping = Column(JSON, nullable=False, default=dict)  # property field -> source column
    sync_interval_minutes = Column(Integer, nullable=False, default=15)
    enabled = Column(Boolean, nullable=False, default=True)
    last_synced_at = Column(DateTime, nullable=True)
    last_status = Column(String(16), nullable=True)  # OK, ERROR
    last_error = Column(Text, nullable=True)
    last_result = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
