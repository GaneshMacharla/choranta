from sqlalchemy.orm import Session
from app.repositories.client_repository import ClientRepository
from app.repositories.agent_repository import AgentRepository
from app.schemas.dashboard import DashboardSummaryResponse, RecentClientItem, RecentAgentItem


class DashboardService:
    def __init__(self, db: Session):
        self.db = db
        self.client_repo = ClientRepository(db)
        self.agent_repo = AgentRepository(db)

    def get_dashboard_summary(self) -> DashboardSummaryResponse:
        total_clients = self.client_repo.count()
        active_clients = self.client_repo.count(status="ACTIVE")
        
        total_agents = self.agent_repo.count()
        # Active agents are READY or DEPLOYED
        active_agents = (
            self.agent_repo.count(status="READY") + 
            self.agent_repo.count(status="DEPLOYED")
        )

        recent_clients_raw = self.client_repo.get_recent(limit=5)
        recent_clients = [
            RecentClientItem(
                id=c.id,
                name=c.name,
                business_type=c.business_type,
                status=c.status,
                agent_count=self.agent_repo.count_by_client(c.id),
                created_at=c.created_at
            )
            for c in recent_clients_raw
        ]

        recent_agents_raw = self.agent_repo.get_recent(limit=5)
        recent_agents = []
        for a in recent_agents_raw:
            client = self.client_repo.get_by_id(a.client_id)
            recent_agents.append(
                RecentAgentItem(
                    id=a.id,
                    client_id=a.client_id,
                    client_name=client.name if client else "Unknown Client",
                    name=a.name,
                    role=a.role,
                    status=a.status,
                    created_at=a.created_at
                )
            )

        return DashboardSummaryResponse(
            total_clients=total_clients,
            active_clients=active_clients,
            total_agents=total_agents,
            active_agents=active_agents,
            recent_clients=recent_clients,
            recent_agents=recent_agents
        )
