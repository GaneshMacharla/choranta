import logging
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.runtime.providers.messaging.base import (
    MessagingError, MessagingProvider, TemplateSpec, TemplateStatus, WhatsAppCredentials,
)

logger = logging.getLogger("choranta.runtime.messaging.meta")

# Graph API error codes worth retrying later; anything else (bad template, bad number, bad params) won't
# succeed by trying again
_RETRYABLE_CODES = {1, 2, 4, 80007, 130429, 131000, 131016, 131048, 131056, 133004}
# The token is expired, revoked or lacks permission: the client must reconnect
_AUTH_CODES = {10, 190, 200}


def _to_meta_number(phone: str) -> str:
    """Meta wants the number with country code and no "+"."""
    return "".join(ch for ch in phone if ch.isdigit())


class MetaWhatsAppProvider(MessagingProvider):
    """WhatsApp Cloud API (graph.facebook.com), with each client's own WABA and token."""

    def __init__(self, name: str = "whatsapp"):
        super().__init__(name)

    def _request(self, method: str, path: str, creds: WhatsAppCredentials, **kwargs) -> Dict[str, Any]:
        url = f"{settings.WHATSAPP_GRAPH_API.rstrip('/')}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.request(method, url, headers={"Authorization": f"Bearer {creds.access_token}"}, **kwargs)
        except httpx.RequestError as exc:
            raise MessagingError(f"Couldn't reach WhatsApp: {exc}") from exc
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400 or "error" in data:
            err = data.get("error") or {}
            code = err.get("code")
            detail = (err.get("error_data") or {}).get("details") or err.get("error_user_msg") or err.get("message") or resp.text
            logger.warning(f"WhatsApp API {method} {path} failed ({resp.status_code}, code {code}): {detail}")
            retryable = code in _RETRYABLE_CODES or (code is None and resp.status_code >= 500)
            raise MessagingError(str(detail)[:500], code=code, permanent=not retryable, auth=code in _AUTH_CODES)
        return data

    def verify_number(self, creds: WhatsAppCredentials) -> Dict[str, Any]:
        data = self._request("GET", creds.phone_number_id, creds,
                             params={"fields": "display_phone_number,verified_name"})
        # The number must belong to the WABA we'll submit templates to
        self._request("GET", f"{creds.waba_id}/phone_numbers", creds, params={"fields": "id"})
        return {"display_phone": data.get("display_phone_number"), "verified_name": data.get("verified_name")}

    def subscribe_app(self, creds: WhatsAppCredentials) -> None:
        self._request("POST", f"{creds.waba_id}/subscribed_apps", creds)

    def submit_template(self, creds: WhatsAppCredentials, spec: TemplateSpec) -> TemplateStatus:
        body: Dict[str, Any] = {"type": "BODY", "text": spec.body}
        if spec.examples:
            body["example"] = {"body_text": [spec.examples]}
        components: List[Dict[str, Any]] = [body]
        if spec.button_url:
            components.append({"type": "BUTTONS", "buttons": [
                {"type": "URL", "text": spec.button_text or "View details", "url": spec.button_url},
            ]})
        data = self._request("POST", f"{creds.waba_id}/message_templates", creds, json={
            "name": spec.name, "language": spec.language, "category": spec.category, "components": components,
        })
        return TemplateStatus(name=spec.name, status=(data.get("status") or "PENDING").upper(),
                              category=data.get("category"), language=spec.language)

    def template_status(self, creds: WhatsAppCredentials, name: str) -> Optional[TemplateStatus]:
        data = self._request("GET", f"{creds.waba_id}/message_templates", creds,
                             params={"name": name, "fields": "name,status,category,language,rejected_reason"})
        for row in data.get("data") or []:
            if row.get("name") == name:
                reason = row.get("rejected_reason")
                return TemplateStatus(name=name, status=(row.get("status") or "").upper(), category=row.get("category"),
                                      language=row.get("language"), reason=None if reason in (None, "NONE") else reason)
        return None

    def send_template(self, creds: WhatsAppCredentials, to: str, name: str, language: str,
                      params: List[str]) -> str:
        template: Dict[str, Any] = {"name": name, "language": {"code": language}}
        if params:
            template["components"] = [{"type": "body", "parameters": [{"type": "text", "text": p} for p in params]}]
        data = self._request("POST", f"{creds.phone_number_id}/messages", creds, json={
            "messaging_product": "whatsapp", "to": _to_meta_number(to), "type": "template", "template": template,
        })
        messages = data.get("messages") or []
        if not messages or not messages[0].get("id"):
            raise MessagingError("WhatsApp accepted the message but returned no message id.")
        return messages[0]["id"]
