from typing import List
from sqlalchemy.orm import Session
from app.models.runtime_event import RuntimeEvent


class RuntimeEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, event: RuntimeEvent) -> RuntimeEvent:
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def list_by_session(self, session_id: str) -> List[RuntimeEvent]:
        return (
            self.db.query(RuntimeEvent)
            .filter(RuntimeEvent.session_id == session_id)
            .order_by(RuntimeEvent.timestamp.asc())
            .all()
        )
