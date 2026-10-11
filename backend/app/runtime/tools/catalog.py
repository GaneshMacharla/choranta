from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.models.tool import Tool

# Tool definitions rarely change; cache them for the process so hot paths don't query the DB
_definitions: Dict[str, Dict[str, Any]] = {}


def describe_tools(db: Session, tool_ids: List[str]) -> List[Dict[str, Any]]:
    """Returns LLM tool definitions (name, description, input JSON schema) for the given tool ids."""
    missing = [t for t in tool_ids if t not in _definitions]
    if missing:
        try:
            for tool in db.query(Tool).filter(Tool.id.in_(missing)).all():
                _definitions[tool.id] = {
                    "description": tool.description,
                    "input_schema": tool.input_schema if isinstance(tool.input_schema, dict) else {},
                }
        except Exception:
            pass
    return [{"name": t, "id": t, **_definitions.get(t, {})} for t in tool_ids]
