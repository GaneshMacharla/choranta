from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.deps import get_db, get_current_user
from app.models.user import User
from app.schemas.agent_spec import (
    AgentConfigurationData,
    AgentConfigurationResponse,
    ValidationResult
)
from app.services.agent_configuration_service import AgentConfigurationService

router = APIRouter(prefix="/agents", tags=["Agent Configuration"])


@router.get("/{agent_id}/configuration", response_model=AgentConfigurationResponse)
def get_agent_configuration(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Retrieve editable draft configuration for an AI Employee."""
    service = AgentConfigurationService(db)
    return service.get_configuration(agent_id)


@router.put("/{agent_id}/configuration", response_model=AgentConfigurationResponse)
def update_agent_configuration(
    agent_id: str,
    payload: AgentConfigurationData,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Save changes to the draft configuration of an AI Employee."""
    service = AgentConfigurationService(db)
    return service.update_configuration(agent_id, payload)


@router.post("/{agent_id}/configuration/validate", response_model=ValidationResult)
def validate_agent_configuration(
    agent_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Validate draft configuration against canonical specification requirements."""
    service = AgentConfigurationService(db)
    return service.validate_configuration(agent_id)
