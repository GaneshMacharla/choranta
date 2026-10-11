from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.agent_version import AgentVersion


class AgentVersionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, version_id: str) -> Optional[AgentVersion]:
        return self.db.query(AgentVersion).filter(AgentVersion.id == version_id).first()

    def list_by_agent(self, agent_id: str) -> List[AgentVersion]:
        return (
            self.db.query(AgentVersion)
            .filter(AgentVersion.agent_id == agent_id)
            .order_by(AgentVersion.version_number.desc())
            .all()
        )

    def get_latest_version_number(self, agent_id: str) -> int:
        result = (
            self.db.query(func.max(AgentVersion.version_number))
            .filter(AgentVersion.agent_id == agent_id)
            .scalar()
        )
        return result or 0

    def create(self, version: AgentVersion) -> AgentVersion:
        self.db.add(version)
        self.db.commit()
        self.db.refresh(version)
        return version
