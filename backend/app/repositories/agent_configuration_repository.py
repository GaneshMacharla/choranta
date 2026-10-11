from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.agent_configuration import AgentConfiguration
from app.core.security import generate_unique_id


class AgentConfigurationRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_agent_id(self, agent_id: str) -> Optional[AgentConfiguration]:
        return self.db.query(AgentConfiguration).filter(AgentConfiguration.agent_id == agent_id).first()

    def save_or_update(self, agent_id: str, data: Dict[str, Any]) -> AgentConfiguration:
        config = self.get_by_agent_id(agent_id)
        if config:
            config.configuration_data = data
        else:
            config = AgentConfiguration(
                id=generate_unique_id("cfg", 12),
                agent_id=agent_id,
                configuration_data=data
            )
            self.db.add(config)
        self.db.commit()
        self.db.refresh(config)
        return config
