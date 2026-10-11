from typing import Any, Optional


class ChorantaException(Exception):
    """Base application exception."""
    def __init__(self, message: str, status_code: int = 400, details: Optional[Any] = None):
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundException(ChorantaException):
    def __init__(self, resource: str, identifier: str):
        super().__init__(f"{resource} with identifier '{identifier}' was not found.", status_code=404)


class ConflictException(ChorantaException):
    def __init__(self, message: str):
        super().__init__(message, status_code=409)


class ValidationException(ChorantaException):
    def __init__(self, message: str, details: Optional[Any] = None):
        super().__init__(message, status_code=422, details=details)


class AuthenticationException(ChorantaException):
    def __init__(self, message: str = "Invalid credentials or unauthorized access."):
        super().__init__(message, status_code=401)


class ForbiddenException(ChorantaException):
    def __init__(self, message: str = "Insufficient permissions to perform this operation."):
        super().__init__(message, status_code=403)
