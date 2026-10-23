import logging
from typing import Any, Dict, List, Optional
from app.runtime.tools.mock import (
    ToolResult,
    BaseToolHandler,
    MockCheckAvailabilityTool,
    MockBookAppointmentTool,
    MockCreateLeadTool,
    MockGetLeadDetailsTool,
    MockSearchPropertiesTool,
    MockCheckSiteVisitSlotsTool,
    MockUpdateLeadRecordTool,
    MockBookSiteVisitTool,
    MockScheduleCallbackTool,
)

logger = logging.getLogger("choranta.runtime.tools")

# On a call, choices are offered two at a time ("9 AM or 2:30 PM?"); reading out a list sounds robotic
_CHOICE_KEYS = ("slot", "time", "option")


def offer_two_choices(data: Any) -> Any:
    """
    Trims lists of choices (time slots, options) in a tool result to two well-spaced ones (the first and the
    last, e.g. a morning and an afternoon slot). The rest stay available under "<key>_only_if_asked".
    """
    if not isinstance(data, dict):
        return data
    trimmed = dict(data)
    for key, value in data.items():
        if (
            isinstance(value, list) and len(value) > 2 and any(word in key.lower() for word in _CHOICE_KEYS)
            and all(isinstance(item, (str, int, float)) for item in value)
        ):
            trimmed[key] = [value[0], value[-1]]
            trimmed[f"{key}_only_if_asked"] = value[1:-1]
    return trimmed


class ToolExecutor:
    """
    Executes tool calls during a runtime session.
    Validates tool activation, enforces timeouts, handles errors, and returns structured ToolResult.
    """

    def __init__(self):
        self._handlers: Dict[str, BaseToolHandler] = {}
        self._register_default_handlers()

    def _register_default_handlers(self) -> None:
        self.register_handler(MockCheckAvailabilityTool())
        self.register_handler(MockBookAppointmentTool())
        self.register_handler(MockCreateLeadTool())
        self.register_handler(MockGetLeadDetailsTool())
        self.register_handler(MockSearchPropertiesTool())
        self.register_handler(MockCheckSiteVisitSlotsTool())
        self.register_handler(MockUpdateLeadRecordTool())
        self.register_handler(MockBookSiteVisitTool())
        self.register_handler(MockScheduleCallbackTool())

    def register_handler(self, handler: BaseToolHandler) -> None:
        self._handlers[handler.tool_id] = handler

    def execute_tool(
        self,
        tool_call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        enabled_tool_ids: List[str],
        timeout: int = 15,
        client_id: Optional[str] = None
    ) -> ToolResult:
        if tool_name not in enabled_tool_ids:
            logger.warning(f"Tool execution blocked: '{tool_name}' is not enabled for session.")
            return ToolResult(
                tool_call_id=tool_call_id,
                success=False,
                data={},
                error=f"Tool '{tool_name}' is not enabled for this agent."
            )

        handler = self._handlers.get(tool_name)
        if not handler:
            logger.warning(f"No execution handler registered for tool '{tool_name}'.")
            return ToolResult(
                tool_call_id=tool_call_id,
                success=False,
                data={},
                error=f"Tool handler for '{tool_name}' is not registered."
            )

        try:
            logger.info(f"Executing tool '{tool_name}' (call_id: {tool_call_id})")
            if handler.accepts_context:
                result_data = handler.execute(arguments, timeout=timeout, context={"client_id": client_id})
            else:
                result_data = handler.execute(arguments, timeout=timeout)
            result_data = offer_two_choices(result_data)
            return ToolResult(
                tool_call_id=tool_call_id,
                success=True,
                data=result_data,
                error=""
            )
        except Exception as e:
            logger.error(f"Error executing tool '{tool_name}': {e}")
            return ToolResult(
                tool_call_id=tool_call_id,
                success=False,
                data={},
                error=f"Execution error: {str(e)}"
            )
