from typing import Any, List, Optional
from sqlalchemy.orm import Session
from app.models.knowledge_source import KnowledgeSource
from app.models.agent import Agent
from app.services import knowledge_store


class KnowledgeRepository:
    """
    Knowledge an AI employee can use: the shared library and per-agent entries (SQL), and its client's
    knowledge base (MongoDB, app/services/knowledge_store.py). Both are attached and detached the same way.
    """

    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> List[KnowledgeSource]:
        return self.db.query(KnowledgeSource).order_by(KnowledgeSource.name.asc()).all()

    def get_by_id(self, source_id: str) -> Optional[Any]:
        return (self.db.query(KnowledgeSource).filter(KnowledgeSource.id == source_id).first()
                or knowledge_store.get_entry(source_id))

    def get_for_agent(self, agent_id: str) -> List[Any]:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        if not agent:
            return []
        return list(agent.knowledge_sources) + knowledge_store.entries_for_agent(agent_id)

    def attach_to_agent(self, agent_id: str, knowledge_id: str) -> bool:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        source = self.get_by_id(knowledge_id)
        if not agent or not source:
            return False
        if isinstance(source, knowledge_store.StoredKnowledge):
            knowledge_store.attach(agent_id, knowledge_id)
        elif source not in agent.knowledge_sources:
            agent.knowledge_sources.append(source)
            self.db.commit()
        return True

    def detach_from_agent(self, agent_id: str, knowledge_id: str) -> bool:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        source = self.get_by_id(knowledge_id)
        if not agent or not source:
            return False
        if isinstance(source, knowledge_store.StoredKnowledge):
            knowledge_store.detach(agent_id, knowledge_id)
        elif source in agent.knowledge_sources:
            agent.knowledge_sources.remove(source)
            self.db.commit()
        return True
