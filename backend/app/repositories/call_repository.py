from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.call import Call


class CallRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, call_id: str) -> Optional[Call]:
        return self.db.query(Call).filter(Call.id == call_id).first()

    def get_by_provider_call_id(self, provider_call_id: str) -> Optional[Call]:
        return self.db.query(Call).filter(Call.provider_call_id == provider_call_id).first()

    def list_by_client(self, client_id: str, skip: int = 0, limit: int = 50) -> List[Call]:
        return (
            self.db.query(Call)
            .filter(Call.client_id == client_id)
            .order_by(Call.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_by_agent(self, agent_id: str, skip: int = 0, limit: int = 50) -> List[Call]:
        return (
            self.db.query(Call)
            .filter(Call.agent_id == agent_id)
            .order_by(Call.created_at.desc())
            .offset(skip)
            .limit(limit)
            .all()
        )

    def list_all(
        self,
        skip: int = 0,
        limit: int = 50,
        status: Optional[str] = None,
        direction: Optional[str] = None,
        client_id: Optional[str] = None
    ) -> List[Call]:
        q = self.db.query(Call)
        if client_id:
            q = q.filter(Call.client_id == client_id)
        if status:
            q = q.filter(Call.status == status)
        if direction:
            q = q.filter(Call.direction == direction)
        return q.order_by(Call.created_at.desc()).offset(skip).limit(limit).all()

    def create(self, call: Call) -> Call:
        self.db.add(call)
        self.db.commit()
        self.db.refresh(call)
        return call

    def update(self, call: Call) -> Call:
        self.db.commit()
        self.db.refresh(call)
        return call
