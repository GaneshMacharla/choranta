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


class InvalidAgentSpec(ChorantaException):
    def __init__(self, message: str, details=None):
        super().__init__(f"Invalid AgentSpec: {message}", status_code=422, details=details)


class ProviderUnavailable(ChorantaException):
    def __init__(self, provider_type: str, provider_name: str):
        super().__init__(f"Requested {provider_type} provider '{provider_name}' is not registered or unavailable.", status_code=503)


class ProviderInitializationError(ChorantaException):
    def __init__(self, provider_name: str, reason: str):
        super().__init__(f"Failed to initialize provider '{provider_name}': {reason}", status_code=500)


class ToolNotFound(ChorantaException):
    def __init__(self, tool_id: str):
        super().__init__(f"Tool '{tool_id}' is not registered or enabled for this runtime session.", status_code=404)


class ToolExecutionError(ChorantaException):
    def __init__(self, tool_id: str, reason: str):
        super().__init__(f"Execution of tool '{tool_id}' failed: {reason}", status_code=500)


class InvalidSessionTransition(ChorantaException):
    def __init__(self, current_status: str, target_status: str):
        super().__init__(
            f"Invalid session status transition from '{current_status}' to '{target_status}'.",
            status_code=400
        )


class RuntimeInitializationError(ChorantaException):
    def __init__(self, reason: str):
        super().__init__(f"Runtime initialization failed: {reason}", status_code=500)


class SessionNotActiveError(ChorantaException):
    def __init__(self, session_id: str, current_status: str):
        super().__init__(
            f"Session '{session_id}' is not in ACTIVE state (current: {current_status}). Cannot process interaction turn.",
            status_code=400
        )
