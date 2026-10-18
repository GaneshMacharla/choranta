from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, event, text
from sqlalchemy.orm import relationship
from app.db.session import Base

CLIENT_CODE_PREFIX = "CL-"
FIRST_CLIENT_NUMBER = 10001


class Client(Base):
    __tablename__ = "clients"

    id = Column(String(64), primary_key=True, index=True)
    # Short, human-readable id shown to admins and the client (e.g. CL-10001); tells same-named clients apart
    client_code = Column(String(16), nullable=True, unique=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    business_type = Column(String(64), nullable=False, index=True)
    description = Column(Text, nullable=True)
    contact_name = Column(String(255), nullable=True)
    contact_email = Column(String(255), nullable=True)
    contact_phone = Column(String(64), nullable=True)
    timezone = Column(String(64), nullable=False, default="Asia/Kolkata")
    status = Column(String(32), nullable=False, default="ACTIVE", index=True)
    max_concurrent_calls = Column(Integer, nullable=True)  # unused: calls at a time follow the wallet
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    # Relationships
    agents = relationship("Agent", back_populates="client", cascade="all, delete-orphan", order_by="Agent.created_at.desc()")

    def __repr__(self) -> str:
        return f"<Client {self.name} ({self.business_type})>"


def next_client_code(connection) -> str:
    """Next sequential client code, e.g. CL-10001, CL-10002."""
    highest = connection.execute(text(
        "SELECT MAX(CAST(SUBSTR(client_code, 4) AS INTEGER)) FROM clients WHERE client_code LIKE 'CL-%'"
    )).scalar()
    return f"{CLIENT_CODE_PREFIX}{max(FIRST_CLIENT_NUMBER, (highest or 0) + 1)}"


@event.listens_for(Client, "before_insert")
def _assign_client_code(mapper, connection, client: Client) -> None:
    if not client.client_code:
        client.client_code = next_client_code(connection)
