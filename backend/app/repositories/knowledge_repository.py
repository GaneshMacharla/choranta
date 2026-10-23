from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.knowledge_source import KnowledgeSource
from app.models.agent import Agent


class KnowledgeRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> List[KnowledgeSource]:
        return self.db.query(KnowledgeSource).order_by(KnowledgeSource.name.asc()).all()

    def get_by_id(self, source_id: str) -> Optional[KnowledgeSource]:
        return self.db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()

    def get_for_agent(self, agent_id: str) -> List[KnowledgeSource]:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        return agent.knowledge_sources if agent else []

    def attach_to_agent(self, agent_id: str, knowledge_id: str) -> bool:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        source = self.get_by_id(knowledge_id)
        if not agent or not source:
            return False
        if source not in agent.knowledge_sources:
            agent.knowledge_sources.append(source)
            self.db.commit()
        return True

    def detach_from_agent(self, agent_id: str, knowledge_id: str) -> bool:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        source = self.get_by_id(knowledge_id)
        if not agent or not source:
            return False
        if source in agent.knowledge_sources:
            agent.knowledge_sources.remove(source)
            self.db.commit()
        return True
