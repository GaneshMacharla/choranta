import logging
from typing import Any, Dict, List, Optional
from app.runtime.exceptions import ToolNotFound, ToolExecutionError
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
