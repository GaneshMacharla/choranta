from app.core.exceptions import ChorantaException


class AgentVersionNotFound(ChorantaException):
    def __init__(self, version_id: str):
        super().__init__(f"Agent version '{version_id}' does not exist.", status_code=404)


class AgentVersionNotPublished(ChorantaException):
    def __init__(self, version_id: str, status: str):
        super().__init__(
            f"Cannot execute Agent version '{version_id}'. Version status is '{status}', but only PUBLISHED versions can be executed in runtime.",
            status_code=422
        )


class ProviderUnavailable(ChorantaException):
    def __init__(self, provider_type: str, provider_name: str):
        super().__init__(f"Requested {provider_type} provider '{provider_name}' is not registered or unavailable.", status_code=503)


class InvalidSessionTransition(ChorantaException):
    def __init__(self, current_status: str, target_status: str):
        super().__init__(
            f"Invalid session status transition from '{current_status}' to '{target_status}'.",
            status_code=400
        )


class SessionNotActiveError(ChorantaException):
    def __init__(self, session_id: str, current_status: str):
        super().__init__(
            f"Session '{session_id}' is not in ACTIVE state (current: {current_status}). Cannot process interaction turn.",
            status_code=400
        )
