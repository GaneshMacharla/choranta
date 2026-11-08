"""
Template call scripts ask like a human telecaller: what the caller needs first, a light background question next, and a
name only when booking. Stored scripts still word for word the old interrogation-first versions are upgraded; scripts
an admin edited are left alone.
"""
from sqlalchemy.orm import Session

from app.models.call_script import StandardCallScript
from app.services import call_scripts
from app.services.agent_templates_business import CALL_SCRIPTS


def test_scripts_start_with_what_the_caller_needs():
    assert CALL_SCRIPTS["skill_training_counsellor"]["discovery_questions"][0] == "Which course or skill are you looking at?"
    assert CALL_SCRIPTS["clinic_receptionist"]["discovery_questions"][0] == "Which doctor or what problem is it for?"
    assert CALL_SCRIPTS["coaching_admission_counsellor"]["discovery_questions"][0] == "Which exam or subject is it for?"
    for key, script in CALL_SCRIPTS.items():
        first = script["discovery_questions"][0].lower()
        assert "name" not in first and "qualification" not in first, key
        assert len(script["discovery_questions"]) <= 4, key


def _store(db: Session, key: str, content) -> StandardCallScript:
    questions, points, next_step = content
    script = db.get(StandardCallScript, key) or StandardCallScript(key=key, name=key)
    script.discovery_questions, script.offer_points, script.next_step = list(questions), list(points), next_step
    db.add(script)
    db.commit()
    return script


def test_unedited_old_scripts_are_upgraded(db: Session):
    _store(db, "skill_training_counsellor", call_scripts._SUPERSEDED_SCRIPTS["skill_training_counsellor"])
    call_scripts.seed_standard_scripts(db)
    db.expire_all()
    assert db.get(StandardCallScript, "skill_training_counsellor").discovery_questions == \
        CALL_SCRIPTS["skill_training_counsellor"]["discovery_questions"]


def test_scripts_an_admin_edited_are_kept(db: Session):
    edited = (("Which branch are you near?",), ("Our nearest centre",), "Book a centre visit")
    _store(db, "clinic_receptionist", edited)
    call_scripts.seed_standard_scripts(db)
    db.expire_all()
    assert db.get(StandardCallScript, "clinic_receptionist").discovery_questions == ["Which branch are you near?"]


def test_known_phone_number_is_not_read_out():
    from app.runtime.context import RuntimeContext
    from test_phase3c_telephony import _build_test_agent_spec
    ctx = RuntimeContext("s", "a", "c", "v", _build_test_agent_spec(), {"origin": "telephony_inbound", "caller": "+919000000001"})
    assert "Don't read it out: say \"on this number\"" in ctx.instruction_for_turn()
