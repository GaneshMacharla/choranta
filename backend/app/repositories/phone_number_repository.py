from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.phone_number import PhoneNumber


class PhoneNumberRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, phone_number_id: str) -> Optional[PhoneNumber]:
        return self.db.query(PhoneNumber).filter(PhoneNumber.id == phone_number_id).first()

    def get_by_e164(self, e164_number: str) -> Optional[PhoneNumber]:
        normalized = e164_number.strip().replace(" ", "").replace("-", "")
        return self.db.query(PhoneNumber).filter(PhoneNumber.phone_number == normalized).first()

    def list_by_client(self, client_id: str, limit: int = 100) -> List[PhoneNumber]:
        return (
            self.db.query(PhoneNumber)
            .filter(PhoneNumber.client_id == client_id)
            .order_by(PhoneNumber.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_all(self, skip: int = 0, limit: int = 100, status: Optional[str] = None) -> List[PhoneNumber]:
        q = self.db.query(PhoneNumber)
        if status:
            q = q.filter(PhoneNumber.status == status)
        return q.order_by(PhoneNumber.created_at.desc()).offset(skip).limit(limit).all()

    def create(self, phone_number: PhoneNumber) -> PhoneNumber:
        self.db.add(phone_number)
        self.db.commit()
        self.db.refresh(phone_number)
        return phone_number

    def update(self, phone_number: PhoneNumber) -> PhoneNumber:
        self.db.commit()
        self.db.refresh(phone_number)
        return phone_number

    def delete(self, phone_number: PhoneNumber) -> None:
        self.db.delete(phone_number)
        self.db.commit()
