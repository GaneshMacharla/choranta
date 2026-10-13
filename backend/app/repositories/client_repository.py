from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from app.models.client import Client
from app.models.agent import Agent


class ClientRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, client_id: str) -> Optional[Client]:
        return self.db.query(Client).filter(Client.id == client_id).first()

    def get_by_name(self, name: str) -> Optional[Client]:
        return self.db.query(Client).filter(func.lower(Client.name) == name.strip().lower()).first()

    def list_all(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        business_type: Optional[str] = None,
        search: Optional[str] = None
    ) -> Tuple[List[Client], int]:
        query = self.db.query(Client)
        if status:
            query = query.filter(Client.status == status)
        if business_type:
            query = query.filter(Client.business_type == business_type)
        if search:
            term = f"%{search.strip()}%"
            query = query.filter(or_(Client.name.ilike(term), Client.client_code.ilike(term)))
        
        total = query.count()
        items = query.order_by(Client.created_at.desc()).offset(skip).limit(limit).all()
        return items, total

    def create(self, client: Client) -> Client:
        self.db.add(client)
        self.db.commit()
        self.db.refresh(client)
        return client

    def update(self, client: Client, data: dict) -> Client:
        for field, value in data.items():
            if value is not None and hasattr(client, field):
                setattr(client, field, value)
        self.db.commit()
        self.db.refresh(client)
        return client

    def count(self, status: Optional[str] = None) -> int:
        query = self.db.query(Client)
        if status:
            query = query.filter(Client.status == status)
        return query.count()

    def get_recent(self, limit: int = 5) -> List[Client]:
        return self.db.query(Client).order_by(Client.created_at.desc()).limit(limit).all()
