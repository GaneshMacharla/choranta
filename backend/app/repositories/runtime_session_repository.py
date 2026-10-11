from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.runtime_session import RuntimeSession


class RuntimeSessionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, session_id: str) -> Optional[RuntimeSession]:
        return self.db.query(RuntimeSession).filter(RuntimeSession.id == session_id).first()

    def create(self, session: RuntimeSession) -> RuntimeSession:
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        return session

    def update(self, session: RuntimeSession) -> RuntimeSession:
        self.db.commit()
        self.db.refresh(session)
        return session

    def list_by_agent(self, agent_id: str, limit: int = 50) -> List[RuntimeSession]:
        return (
            self.db.query(RuntimeSession)
            .filter(RuntimeSession.agent_id == agent_id)
            .order_by(RuntimeSession.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_by_client(self, client_id: str, limit: int = 50) -> List[RuntimeSession]:
        return (
            self.db.query(RuntimeSession)
            .filter(RuntimeSession.client_id == client_id)
            .order_by(RuntimeSession.created_at.desc())
            .limit(limit)
            .all()
        )
