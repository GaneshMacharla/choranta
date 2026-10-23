from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.client import ClientCreate, ClientUpdate, ClientResponse, ClientListResponse
from app.schemas.agent import AgentListResponse
from app.services.client_service import ClientService
from app.services.agent_service import AgentService

router = APIRouter(prefix="/clients", tags=["Clients"])


@router.get("", response_model=ClientListResponse)
def list_clients(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    status: Optional[str] = Query(None),
    business_type: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List business clients managed on Choranta."""
    service = ClientService(db)
    return service.list_clients(
        skip=skip,
        limit=limit,
        status=status,
        business_type=business_type,
        search=search
    )


@router.post("", response_model=ClientResponse, status_code=status.HTTP_201_CREATED)
def create_client(
    payload: ClientCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new client entity."""
    service = ClientService(db)
    return service.create_client(payload)


@router.get("/{client_id}", response_model=ClientResponse)
def get_client(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve details of a specific client."""
    service = ClientService(db)
    return service.get_client(client_id)


@router.patch("/{client_id}", response_model=ClientResponse)
def update_client(
    client_id: str,
    payload: ClientUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update client profile.
    Role check: Modifying client status (e.g. deactivation) requires ADMIN role.
    """
    if payload.status is not None and current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Modifying client account status requires administrator privileges."
        )

    service = ClientService(db)
    return service.update_client(client_id, payload)


@router.get("/{client_id}/agents", response_model=AgentListResponse)
def get_client_agents(
    client_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve AI Employees scoped to a specific client."""
    agent_service = AgentService(db)
    return agent_service.list_agents(skip=skip, limit=limit, client_id=client_id)
