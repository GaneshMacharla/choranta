"""Coaching centres keep a Course catalogue; AI employees quote only its fees and upcoming batches, and know today's date."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import generate_unique_id
from app.models.client import Client
from app.models.course import Course, CourseBatch
from app.models.knowledge_source import KnowledgeSource
from app.runtime import knowledge
from app.runtime.conversation import ConversationState
from app.runtime.courses import CATALOGUE_MARKER
from app.runtime.today import client_today, spoken_date
from test_portal import _client_headers


def _client(db: Session, business_type: str = "COACHING", tz: str = "UTC") -> Client:
    c = Client(id=generate_unique_id("cli_"), name=f"Academy {generate_unique_id('')}", business_type=business_type,
               timezone=tz)
    db.add(c)
    db.commit()
    return c


def _course(db: Session, client_id: str, name: str, **kw) -> Course:
    c = Course(client_id=client_id, name=name, duration=kw.pop("duration", "8 weeks"), mode=kw.pop("mode", "ONLINE"),
               fee=kw.pop("fee", "₹25,000"), **kw)
    db.add(c)
    db.commit()
    return c


def _batch(db: Session, course: Course, start: date, timings: str = "Weekdays 7–9 PM", seats: str = "OPEN") -> None:
    db.add(CourseBatch(course_id=course.id, client_id=course.client_id, start_date=start, timings=timings, seats=seats))
    db.commit()


def _prompt(db: Session, client_id: str, sources=()) -> SimpleNamespace:
    ctx = SimpleNamespace(agent_id=None, client_id=client_id, knowledge_index=None,
                          agent_spec=SimpleNamespace(knowledge=SimpleNamespace(sources=list(sources))),
                          conversation=ConversationState(system_instruction="You are Priya."))
    knowledge.apply_knowledge(db, ctx)
    return ctx


def test_today_is_in_the_clients_timezone_with_unset_meaning_india(db: Session):
    late_evening_utc = datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)  # 1:30 AM on the 15th in India
    assert client_today(db, _client(db, tz="UTC").id, late_evening_utc) == date(2026, 10, 15)
    assert client_today(db, _client(db, tz="America/New_York").id, late_evening_utc) == date(2026, 10, 14)
    assert client_today(db, _client(db, tz="Not/AZone").id, late_evening_utc) == date(2026, 10, 15)
    assert spoken_date(date(2026, 10, 15)) == "Thursday 15 October 2026"


def test_every_agent_is_told_todays_date(db: Session):
    c = _client(db)
    ctx = _prompt(db, c.id)
    prompt = ctx.conversation.system_instruction + ctx.call_details  # the date travels with the per-call details
    assert f"Today's date: {spoken_date(client_today(db, c.id))}" in prompt
    assert "none has been added" in prompt  # no courses, no knowledge: still the strict grounding rule


def test_catalogue_offers_only_upcoming_open_batches_of_active_courses(db: Session):
    c = _client(db)
    today = client_today(db, c.id)
    python = _course(db, c.id, "Python Full Stack", aliases="Python, full stack", fee="₹30,000",
                     instalments="2 instalments", highlights="Django\nReact\n3 projects", certificate=True)
    _batch(db, python, today - timedelta(days=1), "Old batch timings")
    _batch(db, python, today, "Weekdays 7–9 PM")
    _batch(db, python, today + timedelta(days=10), "Weekends 10 AM–1 PM", seats="FULL")
    _course(db, c.id, "SSC CGL", mode="CLASSROOM")
    _course(db, c.id, "Retired course", status="HIDDEN")

    prompt = _prompt(db, c.id).conversation.system_instruction
    assert f"{CATALOGUE_MARKER} (2 courses: Python Full Stack, SSC CGL)" in prompt
    assert "Python Full Stack (also called: Python, full stack)" in prompt
    assert "Fee: ₹30,000; Instalments: 2 instalments" in prompt and "Covers: Django; React; 3 projects" in prompt
    assert f"{spoken_date(today)}, Weekdays 7–9 PM" in prompt  # starts today: still offered
    assert "Old batch timings" not in prompt                   # started yesterday: gone
    assert "Weekends 10 AM–1 PM - FULL" in prompt              # full: shown as full, never offered
    assert "Retired course" not in prompt
    ssc = prompt.split("- SSC CGL")[1]
    assert "Mode: Classroom" in ssc and "none scheduled yet" in ssc
    assert "none has been added" not in prompt  # the catalogue counts as knowledge


def test_catalogue_is_given_whole_even_when_other_knowledge_is_retrieved(db: Session):
    c = _client(db)
    _course(db, c.id, "Snowflake & DBT", fee="₹25,000")
    big = KnowledgeSource(id=generate_unique_id("knw", 12), name="Syllabus", type="NOTES", status="READY",
                          content="\n\n".join(f"Module {i}: warehouses lesson {i}." for i in range(400)), meta={},
                          client_id=c.id)
    db.add(big)
    db.commit()
    ctx = _prompt(db, c.id, [big.id])
    assert ctx.knowledge_index is not None                         # the syllabus is retrieved per reply...
    assert "Snowflake & DBT" in ctx.conversation.system_instruction  # ...the catalogue is always there
    assert "₹25,000" in ctx.conversation.system_instruction


def test_coaching_centre_keeps_its_catalogue_up_to_date_in_the_portal(client: TestClient, auth_headers: dict, db: Session):
    c = _client(db)
    h = _client_headers(client, auth_headers, c.id, f"owner-{c.id}@academy.example.com")
    today = date.fromisoformat(client.get("/api/portal/courses", headers=h).json()["today"])

    made = client.post("/api/portal/courses", headers=h, json={
        "name": "Python Full Stack", "aliases": "Python", "duration": "4 months", "mode": "BOTH", "fee": "₹30,000"})
    assert made.status_code == 201, made.text
    cid = made.json()["id"]
    dup = client.post("/api/portal/courses", headers=h, json={
        "name": "python full stack", "duration": "1 month", "mode": "ONLINE", "fee": "₹1"})
    assert dup.status_code == 409
    missing_fee = client.post("/api/portal/courses", headers=h, json={"name": "AI", "duration": "1 month", "mode": "ONLINE"})
    assert missing_fee.status_code == 422

    past = client.post(f"/api/portal/courses/{cid}/batches", headers=h,
                       json={"start_date": (today - timedelta(days=1)).isoformat(), "timings": "7 PM"})
    assert past.status_code == 422
    added = client.post(f"/api/portal/courses/{cid}/batches", headers=h,
                        json={"start_date": (today + timedelta(days=5)).isoformat(), "timings": "Weekdays 7–9 PM"})
    assert added.status_code == 201, added.text
    batch = added.json()["batches"][0]
    assert batch["state"] == "UPCOMING" and batch["seats"] == "OPEN"

    full = client.patch(f"/api/portal/courses/{cid}/batches/{batch['id']}", headers=h, json={"seats": "FULL"})
    assert full.json()["batches"][0]["state"] == "FULL"
    fee = client.patch(f"/api/portal/courses/{cid}", headers=h, json={"fee": "₹32,000"})
    assert fee.json()["fee"] == "₹32,000"
    blank = client.patch(f"/api/portal/courses/{cid}", headers=h, json={"fee": "  "})
    assert blank.status_code == 422
    hidden = client.patch(f"/api/portal/courses/{cid}", headers=h, json={"status": "HIDDEN"})
    assert hidden.json()["status"] == "HIDDEN"
    gone = client.delete(f"/api/portal/courses/{cid}/batches/{batch['id']}", headers=h)
    assert gone.json()["batches"] == []

    history = client.get("/api/portal/courses/changes", headers=h).json()
    assert [x["action"] for x in history] == ["BATCH_REMOVED", "COURSE_HIDDEN", "COURSE_UPDATED", "BATCH_UPDATED",
                                              "BATCH_ADDED", "COURSE_ADDED"]
    fee_change = history[2]
    assert fee_change["fee_changed"] and fee_change["summary"] == "Fee: ₹30,000 → ₹32,000"
    assert fee_change["actor"] == "CLIENT" and history[3]["summary"].endswith("Seats: Open → Full")

    # The team sees the same catalogue and history on the client page, and its own edits are marked as the team's
    admin = client.get(f"/api/clients/{c.id}/courses", headers=auth_headers).json()
    assert [x["name"] for x in admin["courses"]] == ["Python Full Stack"]
    client.patch(f"/api/clients/{c.id}/courses/{cid}", headers=auth_headers, json={"status": "ACTIVE"})
    assert client.get(f"/api/clients/{c.id}/courses/changes", headers=auth_headers).json()[0]["actor"] == "TEAM"


def test_portal_courses_are_only_for_coaching_centres_and_their_own_courses(client: TestClient, auth_headers: dict,
                                                                            db: Session):
    clinic = _client(db, business_type="CLINIC")
    h = _client_headers(client, auth_headers, clinic.id, f"owner-{clinic.id}@clinic.example.com")
    assert client.get("/api/portal/courses", headers=h).status_code == 403

    mine, other = _client(db), _client(db)
    foreign = _course(db, other.id, "Someone else's course")
    h = _client_headers(client, auth_headers, mine.id, f"owner-{mine.id}@academy.example.com")
    assert client.get("/api/portal/courses", headers=h).json()["courses"] == []
    assert client.patch(f"/api/portal/courses/{foreign.id}", headers=h, json={"fee": "₹1"}).status_code == 404
    assert client.post(f"/api/portal/courses/{foreign.id}/batches", headers=h,
                       json={"start_date": "2099-01-01", "timings": "7 PM"}).status_code == 404
    assert client.get("/api/portal/me", headers=h).json()["business_type"] == "COACHING"
