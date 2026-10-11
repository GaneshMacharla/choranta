from typing import List, Optional, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from app.models.agent import Agent
from app.models.client import Client


class AgentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, agent_id: str) -> Optional[Agent]:
        return self.db.query(Agent).filter(Agent.id == agent_id).first()

    def list_all(
        self,
        skip: int = 0,
        limit: int = 100,
        client_id: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None
    ) -> Tuple[List[Agent], int]:
        query = self.db.query(Agent)
        if client_id:
            query = query.filter(Agent.client_id == client_id)
        if status:
            query = query.filter(Agent.status == status)
        if search:
            query = query.filter(
                (Agent.name.ilike(f"%{search.strip()}%")) | 
                (Agent.role.ilike(f"%{search.strip()}%"))
            )
        
        total = query.count()
        items = query.order_by(Agent.created_at.desc()).offset(skip).limit(limit).all()
        return items, total

    def create(self, agent: Agent) -> Agent:
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def update(self, agent: Agent, data: dict) -> Agent:
        for field, value in data.items():
            if value is not None and hasattr(agent, field):
                setattr(agent, field, value)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def count(self, status: Optional[str] = None) -> int:
        query = self.db.query(Agent)
        if status:
            query = query.filter(Agent.status == status)
        return query.count()

    def count_by_client(self, client_id: str) -> int:
        return self.db.query(Agent).filter(Agent.client_id == client_id).count()

    def get_recent(self, limit: int = 5) -> List[Agent]:
        return self.db.query(Agent).order_by(Agent.created_at.desc()).limit(limit).all()

    def delete(self, agent: Agent) -> None:
        from sqlalchemy import text
        agent_id = agent.id
        self.db.execute(text("DELETE FROM test_run_events WHERE run_id IN (SELECT id FROM test_runs WHERE agent_id = :aid)"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM test_runs WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM test_scenarios WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM runtime_events WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM runtime_sessions WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM calls WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM agent_tools WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM agent_integrations WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM agent_knowledge_sources WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM agent_configurations WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("DELETE FROM agent_versions WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.execute(text("UPDATE phone_numbers SET agent_id = NULL WHERE agent_id = :aid"), {"aid": agent_id})
        self.db.delete(agent)
        self.db.commit()
