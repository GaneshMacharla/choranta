import uuid
from typing import Any, Dict, List, Optional

from app.runtime.providers.messaging.base import (
    MessagingError, MessagingProvider, TemplateSpec, TemplateStatus, WhatsAppCredentials,
)


class MockMessagingProvider(MessagingProvider):
    """Records what would be sent. Templates are approved straight away so local follow-ups can be tried end to end."""

    def __init__(self, name: str = "mock_whatsapp"):
        super().__init__(name)
        self.sent: List[Dict[str, Any]] = []
        self.templates: Dict[str, TemplateStatus] = {}
        self.submitted: List[TemplateSpec] = []
        self.fail_next: List[MessagingError] = []   # tests queue errors for the next sends
        self.auto_approve = True

    def verify_number(self, creds: WhatsAppCredentials) -> Dict[str, Any]:
        if creds.access_token == "bad-token":
            raise MessagingError("Invalid OAuth access token.", code=190, permanent=True, auth=True)
        return {"display_phone": "+91 90000 00000", "verified_name": "Test Business"}

    def subscribe_app(self, creds: WhatsAppCredentials) -> None:
        return None

    def submit_template(self, creds: WhatsAppCredentials, spec: TemplateSpec) -> TemplateStatus:
        self.submitted.append(spec)
        status = TemplateStatus(name=spec.name, status="APPROVED" if self.auto_approve else "PENDING",
                                category=spec.category, language=spec.language)
        self.templates[spec.name] = status
        return status

    def template_status(self, creds: WhatsAppCredentials, name: str) -> Optional[TemplateStatus]:
        return self.templates.get(name)

    def send_template(self, creds: WhatsAppCredentials, to: str, name: str, language: str,
                      params: List[str]) -> str:
        if self.fail_next:
            raise self.fail_next.pop(0)
        message_id = f"wamid.mock{uuid.uuid4().hex[:16]}"
        self.sent.append({"id": message_id, "to": to, "template": name, "language": language, "params": list(params),
                          "phone_number_id": creds.phone_number_id})
        return message_id

    def reset(self) -> None:
        self.sent.clear()
        self.templates.clear()
        self.submitted.clear()
        self.fail_next.clear()
        self.auto_approve = True
