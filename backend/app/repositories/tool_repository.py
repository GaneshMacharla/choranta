from typing import List, Optional
from sqlalchemy.orm import Session
from app.models.tool import Tool, agent_tools
from app.models.agent import Agent


class ToolRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_all(self) -> List[Tool]:
        return self.db.query(Tool).order_by(Tool.name.asc()).all()

    def get_by_id(self, tool_id: str) -> Optional[Tool]:
        return self.db.query(Tool).filter(Tool.id == tool_id).first()

    def get_for_agent(self, agent_id: str) -> List[Tool]:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        return agent.tools if agent else []

    def attach_to_agent(self, agent_id: str, tool_id: str) -> bool:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        tool = self.get_by_id(tool_id)
        if not agent or not tool:
            return False
        if tool not in agent.tools:
            agent.tools.append(tool)
            self.db.commit()
        return True

    def detach_from_agent(self, agent_id: str, tool_id: str) -> bool:
        agent = self.db.query(Agent).filter(Agent.id == agent_id).first()
        tool = self.get_by_id(tool_id)
        if not agent or not tool:
            return False
        if tool in agent.tools:
            agent.tools.remove(tool)
            self.db.commit()
        return True
