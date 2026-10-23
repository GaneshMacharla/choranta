from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.integration import Integration
from app.models.agent import Agent


class IntegrationRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> List[Integration]:
        return self.db.query(Integration).order_by(Integration.name.asc()).all()

    def get_by_id(self, integration_id: str) -> Optional[Integration]:
        return self.db.query(Integration).filter(Integration.id == integration_id).first()

    def get_for_agent(self, agent_id: str) -> List[Integration]:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        return agent.integrations if agent else []

    def attach_to_agent(self, agent_id: str, integration_id: str) -> bool:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        integration = self.get_by_id(integration_id)
        if not agent or not integration:
            return False
        if integration not in agent.integrations:
            agent.integrations.append(integration)
            self.db.commit()
        return True

    def detach_from_agent(self, agent_id: str, integration_id: str) -> bool:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        integration = self.get_by_id(integration_id)
        if not agent or not integration:
            return False
        if integration in agent.integrations:
            agent.integrations.remove(integration)
            self.db.commit()
        return True
