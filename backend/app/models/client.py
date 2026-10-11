from datetime import datetime, timezone
from sqlalchemy import Column, String, Text, DateTime
from sqlalchemy.orm import relationship
from app.db.session import Base


class Client(Base):
    __tablename__ = "clients"

    id = Column(String(64), primary_key=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    business_type = Column(String(64), nullable=False, index=True)
    description = Column(Text, nullable=True)
    contact_name = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(64), nullable=True)
    timezone = Column(String(64), nullable=False, default="UTC")
    status = Column(String(32), nullable=False, default="ACTIVE", index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    agents = relationship("Agent", back_populates="client", cascade="all, delete-orphan", order_by="Agent.created_at.desc()")

    def __repr__(self) -> str:
        return f"<Client {self.name} ({self.business_type})>"
