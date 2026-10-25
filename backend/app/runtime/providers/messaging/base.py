import hashlib
import hmac
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class WhatsAppCredentials:
    waba_id: str
    phone_number_id: str
    access_token: str


class MessagingError(Exception):
    """A send or template call Meta refused. permanent=False means trying again later may work."""

    def __init__(self, message: str, code: Optional[int] = None, permanent: bool = False, auth: bool = False):
        super().__init__(message)
        self.code = code
        self.permanent = permanent
        self.auth = auth  # the access token itself was rejected


@dataclass
class TemplateStatus:
    name: str
    status: str                 # APPROVED / PENDING / REJECTED / PAUSED / DISABLED
    category: Optional[str] = None
    language: Optional[str] = None
    reason: Optional[str] = None


@dataclass
class TemplateSpec:
    name: str
    language: str
    body: str                   # with {{1}}, {{2}}... placeholders
    examples: List[str] = field(default_factory=list)
    button_text: Optional[str] = None
    button_url: Optional[str] = None
    category: str = "UTILITY"


class MessagingProvider(ABC):
    """WhatsApp Business messaging: send approved templates, submit templates for approval."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def verify_number(self, creds: WhatsAppCredentials) -> Dict[str, Any]:
        """{"display_phone": ..., "verified_name": ...}; MessagingError if the ids or token are wrong."""

    @abstractmethod
    def subscribe_app(self, creds: WhatsAppCredentials) -> None:
        """Subscribes the WABA to the token's Meta app, so the app's webhook receives its replies and statuses."""

    @abstractmethod
    def submit_template(self, creds: WhatsAppCredentials, spec: TemplateSpec) -> TemplateStatus: ...

    @abstractmethod
    def template_status(self, creds: WhatsAppCredentials, name: str) -> Optional[TemplateStatus]: ...

    @abstractmethod
    def send_template(self, creds: WhatsAppCredentials, to: str, name: str, language: str,
                      params: List[str]) -> str:
        """Sends the template; returns Meta's message id."""

    def verify_signature(self, raw_body: bytes, header: Optional[str], app_secret: Optional[str]) -> bool:
        """Meta signs webhook bodies with the app secret: X-Hub-Signature-256: sha256=<hex>."""
        if not app_secret or not header or not header.startswith("sha256="):
            return False
        expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header[len("sha256="):])
