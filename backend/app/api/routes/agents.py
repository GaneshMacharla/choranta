from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user, require_admin
from app.models.user import User
from app.schemas.agent import AgentCreate, AgentUpdate, AgentResponse, AgentListResponse, AgentStatusEnum
from app.schemas.agent_spec import AgentVersionResponse, VersionComparisonResponse
from app.services.agent_service import AgentService
from app.services.agent_version_service import AgentVersionService

router = APIRouter(prefix="/agents", tags=["AI Employees"])


@router.get("", response_model=AgentListResponse)
def list_agents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List AI Employees configured across clients."""
    service = AgentService(db)
    return service.list_agents(
        skip=skip,
        limit=limit,
        client_id=client_id,
        status=status,
        search=search
    )


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
def create_agent(
    payload: AgentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new AI Employee for a specific client."""
    service = AgentService(db)
    return service.create_agent(payload, creator_id=current_user.id)


@router.get("/{agent_id}", response_model=AgentResponse)
def get_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve details of a specific AI Employee."""
    service = AgentService(db)
    return service.get_agent(agent_id)


@router.patch("/{agent_id}", response_model=AgentResponse)
def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Update role, name, description or status of an AI Employee.
    Role check: Transitioning to DEPLOYED or ARCHIVED requires ADMIN privileges.
    """
    if payload.status in (AgentStatusEnum.DEPLOYED, AgentStatusEnum.ARCHIVED) and current_user.role != "ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: Transitioning agent to {payload.status.value} requires administrator privileges."
        )

    service = AgentService(db)
    return service.update_agent(agent_id, payload)


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an AI Employee and all associated versions, tests, and sessions."""
    service = AgentService(db)
    service.delete_agent(agent_id)
    return None


@router.delete("", status_code=status.HTTP_200_OK)
def delete_all_agents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete all AI Employees across the platform."""
    from app.models.agent import Agent
    service = AgentService(db)
    all_agents = db.query(Agent).all()
    count = len(all_agents)
    for a in all_agents:
        service.delete_agent(a.id)
    return {"message": f"Successfully deleted {count} AI employee(s).", "count": count}


# ==========================================
# AGENT VERSIONS
# ==========================================

@router.get("/{agent_id}/versions", response_model=List[AgentVersionResponse])
def get_agent_versions(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve immutable version history for an AI Employee."""
    v_service = AgentVersionService(db)
    return v_service.list_versions(agent_id)


@router.post("/{agent_id}/versions", response_model=AgentVersionResponse, status_code=status.HTTP_201_CREATED)
def create_agent_version(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Freeze current validated draft configuration into an immutable version snapshot.
    """
    v_service = AgentVersionService(db)
    return v_service.create_version(agent_id, creator_id=current_user.id)


@router.get("/{agent_id}/versions/compare", response_model=VersionComparisonResponse)
def compare_agent_versions(
    agent_id: str,
    base_version: int = Query(..., ge=1),
    compare_version: int = Query(..., ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Compare two version snapshots of an AI Employee."""
    v_service = AgentVersionService(db)
    return v_service.compare_versions(agent_id, base_version, compare_version)


@router.get("/{agent_id}/versions/{version_id}", response_model=AgentVersionResponse)
def get_agent_version_detail(
    agent_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Inspect full specification of a previous immutable version."""
    v_service = AgentVersionService(db)
    return v_service.get_version(agent_id, version_id)


@router.post("/{agent_id}/versions/{version_id}/restore")
def restore_agent_version(
    agent_id: str,
    version_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Rollback: Load an old immutable version into the current editable draft.
    Does not mutate or delete the source version snapshot.
    """
    v_service = AgentVersionService(db)
    return v_service.restore_version_to_draft(agent_id, version_id)
