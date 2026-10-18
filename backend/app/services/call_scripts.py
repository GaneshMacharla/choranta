"""
Standard call scripts: one admin-maintained script per template (real estate, coaching, clinic...).

An AI employee is linked to a standard script through `instructions.script_source` (the script's key); an empty
value means it uses its own script. A linked employee takes the standard script's current content each time it is
published, so editing a standard script changes linked employees on their next publish, never mid-version.
"""
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.exceptions import NotFoundException, ValidationException
from app.models.agent_configuration import AgentConfiguration
from app.models.call_script import StandardCallScript
from app.schemas.agent_spec import AgentConfigurationData

logger = logging.getLogger("choranta.call_scripts")

SCRIPT_FIELDS = ("discovery_questions", "offer_points", "next_step")


def script_out(script: StandardCallScript) -> Dict[str, Any]:
    return {
        "key": script.key,
        "name": script.name,
        "discovery_questions": list(script.discovery_questions or []),
        "offer_points": list(script.offer_points or []),
        "next_step": script.next_step or "",
        "updated_at": script.updated_at.isoformat() if script.updated_at else None,
    }


def list_scripts(db: Session) -> List[StandardCallScript]:
    return db.query(StandardCallScript).order_by(StandardCallScript.name).all()


def get_script(db: Session, key: str) -> StandardCallScript:
    script = db.get(StandardCallScript, key)
    if not script:
        raise NotFoundException("Standard call script", key)
    return script


def update_script(db: Session, key: str, discovery_questions: List[str], offer_points: List[str],
                  next_step: str, user_id: Optional[str]) -> StandardCallScript:
    script = get_script(db, key)
    questions = [q.strip() for q in discovery_questions if q and q.strip()]
    points = [p.strip() for p in offer_points if p and p.strip()]
    if not questions or not next_step.strip():
        raise ValidationException("A standard call script needs at least one question and a next step.")
    script.discovery_questions = questions
    script.offer_points = points
    script.next_step = next_step.strip()
    script.updated_by = user_id
    db.commit()
    db.refresh(script)
    return script


def with_standard_script(db: Session, draft: AgentConfigurationData) -> AgentConfigurationData:
    """The draft with its call script replaced by the linked standard script's current content (if linked)."""
    key = (draft.instructions.script_source or "").strip()
    if not key:
        return draft
    script = db.get(StandardCallScript, key)
    if not script:
        logger.warning(f"Agent draft links to unknown standard call script '{key}'; using its own script.")
        return draft
    instructions = draft.instructions.model_copy(update={
        "discovery_questions": list(script.discovery_questions or []),
        "offer_points": list(script.offer_points or []),
        "next_step": script.next_step or "",
    })
    return draft.model_copy(update={"instructions": instructions})


# Standard scripts as first seeded, replaced since: a stored script still word for word like this was never
# edited by an admin, so it is upgraded to the template's current script
_SUPERSEDED_SCRIPTS = {
    "course_batch_announcement": (
        ("Do you work with data today, or are you a fresher?", "Would online or classroom suit you better?"),
        ("Snowflake and DBT batch starting Monday, 19 October 2026", "Real projects included", "Free demo class"),
        "Book a free demo class",
    ),
}


def seed_standard_scripts(db: Session) -> None:
    """Creates a standard script for every template that has one (existing scripts keep their edits)."""
    from app.services.agent_templates import AVAILABLE_AGENT_TEMPLATES
    from app.services.agent_templates_business import CALL_SCRIPTS

    names = {tpl["id"]: tpl["name"] for tpl in AVAILABLE_AGENT_TEMPLATES}
    for key, content in CALL_SCRIPTS.items():
        existing = db.get(StandardCallScript, key)
        if existing:
            stored = (tuple(existing.discovery_questions or []), tuple(existing.offer_points or []), existing.next_step or "")
            if _SUPERSEDED_SCRIPTS.get(key) == stored:
                existing.name = names.get(key, existing.name)
                existing.discovery_questions = list(content.get("discovery_questions") or [])
                existing.offer_points = list(content.get("offer_points") or [])
                existing.next_step = content.get("next_step") or ""
            continue
        db.add(StandardCallScript(
            key=key,
            name=names.get(key, key.replace("_", " ").title()),
            discovery_questions=list(content.get("discovery_questions") or []),
            offer_points=list(content.get("offer_points") or []),
            next_step=content.get("next_step") or "",
        ))
    db.commit()
    _link_unchanged_template_copies(db)


def _link_unchanged_template_copies(db: Session) -> None:
    """
    Links employees created before standard scripts existed when their script is still word for word a
    standard one, so nothing they say changes. Only drafts that have never had a script_source are touched,
    so an employee an admin has unlinked is never relinked.
    """
    scripts = {
        (tuple(s.discovery_questions or []), tuple(s.offer_points or []), s.next_step or ""): s.key
        for s in list_scripts(db)
    }
    linked = 0
    for record in db.query(AgentConfiguration).all():
        data = dict(record.configuration_data or {})
        instructions = dict(data.get("instructions") or {})
        if "script_source" in instructions:
            continue
        signature = (
            tuple(instructions.get("discovery_questions") or []),
            tuple(instructions.get("offer_points") or []),
            instructions.get("next_step") or "",
        )
        instructions["script_source"] = scripts.get(signature, "")
        data["instructions"] = instructions
        record.configuration_data = data
        flag_modified(record, "configuration_data")
        linked += bool(instructions["script_source"])
    db.commit()
    if linked:
        logger.info(f"Linked {linked} AI employee(s) to their unchanged standard call script.")
