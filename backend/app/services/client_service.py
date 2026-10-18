from typing import Optional, List
from sqlalchemy.orm import Session
from app.core.exceptions import NotFoundException, ConflictException
from app.core.security import generate_unique_id
from app.models.client import Client
from app.repositories.client_repository import ClientRepository
from app.repositories.agent_repository import AgentRepository
from app.schemas.client import ClientCreate, ClientUpdate, ClientResponse, ClientListResponse


class ClientService:
    def __init__(self, db: Session):
        self.db = db
        self.client_repo = ClientRepository(db)
        self.agent_repo = AgentRepository(db)

    def create_client(self, data: ClientCreate) -> ClientResponse:
        existing = self.client_repo.get_by_name(data.name)
        if existing:
            raise ConflictException(f"A client with name '{data.name}' already exists.")

        client = Client(
            id=generate_unique_id("cli", 12),
            name=data.name.strip(),
            business_type=data.business_type.value,
            description=data.description.strip() if data.description else None,
            contact_name=data.contact_name.strip() if data.contact_name else None,
            contact_email=data.contact_email.strip() if data.contact_email else None,
            contact_phone=data.contact_phone.strip() if data.contact_phone else None,
            timezone=data.timezone.strip() if data.timezone else "UTC",
            status="ACTIVE"
        )
        saved = self.client_repo.create(client)
        return self._to_response(saved)

    def get_client(self, client_id: str) -> ClientResponse:
        client = self.client_repo.get_by_id(client_id)
        if not client:
            raise NotFoundException("Client", client_id)
        return self._to_response(client)

    def update_client(self, client_id: str, data: ClientUpdate) -> ClientResponse:
        client = self.client_repo.get_by_id(client_id)
        if not client:
            raise NotFoundException("Client", client_id)

        update_dict = {}
        if data.name is not None:
            existing = self.client_repo.get_by_name(data.name)
            if existing and existing.id != client_id:
                raise ConflictException(f"Another client with name '{data.name}' already exists.")
            update_dict["name"] = data.name.strip()
        if data.business_type is not None:
            update_dict["business_type"] = data.business_type.value
        if data.description is not None:
            update_dict["description"] = data.description.strip() if data.description else None
        if data.contact_name is not None:
            update_dict["contact_name"] = data.contact_name.strip() if data.contact_name else None
        if data.contact_email is not None:
            update_dict["contact_email"] = data.contact_email.strip() if data.contact_email else None
        if data.contact_phone is not None:
            update_dict["contact_phone"] = data.contact_phone.strip() if data.contact_phone else None
        if data.timezone is not None:
            update_dict["timezone"] = data.timezone.strip()
        if data.status is not None:
            update_dict["status"] = data.status.value

        updated = self.client_repo.update(client, update_dict)
        return self._to_response(updated)

    def list_clients(
        self,
        skip: int = 0,
        limit: int = 100,
        status: Optional[str] = None,
        business_type: Optional[str] = None,
        search: Optional[str] = None
    ) -> ClientListResponse:
        items, total = self.client_repo.list_all(
            skip=skip,
            limit=limit,
            status=status,
            business_type=business_type,
            search=search
        )
        responses = [self._to_response(c) for c in items]
        return ClientListResponse(items=responses, total=total)

    def _to_response(self, client: Client) -> ClientResponse:
        agent_count = self.agent_repo.count_by_client(client.id)
        return ClientResponse(
            id=client.id,
            client_code=client.client_code,
            name=client.name,
            business_type=client.business_type,
            description=client.description,
            contact_name=client.contact_name,
            contact_email=client.contact_email,
            contact_phone=client.contact_phone,
            timezone=client.timezone,
            status=client.status,
            agent_count=agent_count,
            created_at=client.created_at,
            updated_at=client.updated_at
        )
