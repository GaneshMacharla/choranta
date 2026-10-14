"""
A coaching centre's Course catalogue: courses and their batches, kept up to date by the centre in the client portal
and by Choranta's team on the client page. Every change is recorded (fee changes flagged) so the team can see what a
centre edited. AI employees read the catalogue on each call (runtime/courses.py).
"""
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.course import Course, CourseBatch, CourseChange
from app.runtime.courses import MODE_LABELS
from app.runtime.today import client_today, spoken_date

Actor = Tuple[str, Optional[str]]  # ("CLIENT" | "TEAM", who)

COURSE_FIELDS = {
    "name": "Name", "aliases": "Also called", "category": "Category", "audience": "Who it's for",
    "eligibility": "Eligibility", "duration": "Duration", "mode": "Mode", "medium": "Medium", "fee": "Fee",
    "instalments": "Instalments", "highlights": "What's covered", "certificate": "Certificate",
    "extra_details": "Extra details", "sort_order": "Order",
}
REQUIRED_COURSE_FIELDS = ("name", "duration", "mode", "fee")
LONG_FIELDS = ("highlights", "extra_details", "audience", "eligibility", "instalments")  # summarised as "updated"
BATCH_FIELDS = {"start_date": "Start date", "timings": "Timings", "mode": "Mode", "medium": "Medium", "seats": "Seats"}
RECENT_BATCH_DAYS = 30  # started batches stay visible (greyed) this long, then drop off the list


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        value = " ".join(value.split()) if "\n" not in value else value.strip()
        return value or None
    return value


def _shown(field: str, value: Any) -> str:
    if value is None or value == "":
        return "—"
    if field == "mode":
        return MODE_LABELS.get(value, value)
    if field == "seats":
        return "Full" if value == "FULL" else "Open"
    if field == "certificate":
        return "Yes" if value else "No"
    if isinstance(value, date):
        return spoken_date(value)
    return str(value)


def _record(db: Session, client_id: str, course: Course, action: str, summary: str, actor: Actor,
            changes: Optional[Dict[str, List[Any]]] = None) -> None:
    changes = changes or {}
    db.add(CourseChange(
        client_id=client_id, course_id=course.id, course_name=course.name, action=action, summary=summary,
        changes={k: [_shown(k, old), _shown(k, new)] for k, (old, new) in changes.items()},
        fee_changed="fee" in changes, actor=actor[0], actor_name=actor[1],
    ))


def _course(db: Session, client_id: str, course_id: str) -> Course:
    course = db.get(Course, course_id)
    if not course or course.client_id != client_id:
        raise HTTPException(status_code=404, detail="Course not found.")
    return course


def _batch(db: Session, course: Course, batch_id: str) -> CourseBatch:
    batch = db.get(CourseBatch, batch_id)
    if not batch or batch.course_id != course.id:
        raise HTTPException(status_code=404, detail="Batch not found.")
    return batch


def _check_name(db: Session, client_id: str, name: str, course_id: Optional[str] = None) -> None:
    query = db.query(Course).filter(Course.client_id == client_id, func.lower(Course.name) == name.lower())
    if course_id:
        query = query.filter(Course.id != course_id)
    if query.first():
        raise HTTPException(status_code=409, detail=f'A course called "{name}" already exists.')


def _check_date(db: Session, client_id: str, start_date: date) -> None:
    if start_date < client_today(db, client_id):
        raise HTTPException(status_code=422, detail="That start date has already passed.")


def batch_out(batch: CourseBatch, today: date) -> Dict[str, Any]:
    state = "STARTED" if batch.start_date < today else ("FULL" if batch.seats == "FULL" else "UPCOMING")
    return {"id": batch.id, "start_date": batch.start_date.isoformat(), "timings": batch.timings, "mode": batch.mode,
            "medium": batch.medium, "seats": batch.seats, "state": state}


def course_out(course: Course, today: date) -> Dict[str, Any]:
    recent = today - timedelta(days=RECENT_BATCH_DAYS)
    return {
        "id": course.id, "name": course.name, "aliases": course.aliases, "category": course.category,
        "audience": course.audience, "eligibility": course.eligibility, "duration": course.duration,
        "mode": course.mode, "medium": course.medium, "fee": course.fee, "instalments": course.instalments,
        "highlights": course.highlights, "certificate": course.certificate, "extra_details": course.extra_details,
        "status": course.status, "sort_order": course.sort_order,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
        "batches": [batch_out(b, today) for b in course.batches if b.start_date >= recent],
    }


def change_out(change: CourseChange) -> Dict[str, Any]:
    return {"id": change.id, "course_id": change.course_id, "course_name": change.course_name,
            "action": change.action, "summary": change.summary, "changes": change.changes,
            "fee_changed": change.fee_changed, "actor": change.actor, "actor_name": change.actor_name,
            "created_at": change.created_at.isoformat() if change.created_at else None}


def catalogue(db: Session, client_id: str) -> Dict[str, Any]:
    today = client_today(db, client_id)
    courses = (db.query(Course).filter(Course.client_id == client_id)
               .order_by(Course.status, Course.sort_order, Course.name).all())
    return {"today": today.isoformat(), "courses": [course_out(c, today) for c in courses]}


def recent_changes(db: Session, client_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    rows = (db.query(CourseChange).filter(CourseChange.client_id == client_id)
            .order_by(CourseChange.created_at.desc()).limit(limit).all())
    return [change_out(c) for c in rows]


def create_course(db: Session, client_id: str, data: Dict[str, Any], actor: Actor) -> Dict[str, Any]:
    values = {k: _clean(v) for k, v in data.items() if k in COURSE_FIELDS}
    for field in REQUIRED_COURSE_FIELDS:
        if not values.get(field):
            raise HTTPException(status_code=422, detail=f"{COURSE_FIELDS[field]} is required.")
    _check_name(db, client_id, values["name"])
    if values.get("sort_order") is None:  # new courses go to the end of the list
        last = db.query(func.max(Course.sort_order)).filter(Course.client_id == client_id).scalar()
        values["sort_order"] = (last or 0) + 1
    course = Course(client_id=client_id, status="ACTIVE", **values)
    db.add(course)
    db.flush()
    _record(db, client_id, course, "COURSE_ADDED", f"Course added (fee {course.fee})", actor)
    db.commit()
    db.refresh(course)
    return course_out(course, client_today(db, client_id))


def update_course(db: Session, client_id: str, course_id: str, data: Dict[str, Any], actor: Actor) -> Dict[str, Any]:
    course = _course(db, client_id, course_id)
    diffs: Dict[str, List[Any]] = {}
    for field, value in data.items():
        if field not in COURSE_FIELDS:
            continue
        value = _clean(value)
        if field in REQUIRED_COURSE_FIELDS and not value:
            raise HTTPException(status_code=422, detail=f"{COURSE_FIELDS[field]} can't be empty.")
        if value != getattr(course, field):
            diffs[field] = [getattr(course, field), value]
    if "name" in diffs:
        _check_name(db, client_id, diffs["name"][1], course.id)
    status = data.get("status")
    status_changed = status in ("ACTIVE", "HIDDEN") and status != course.status
    if not diffs and not status_changed:
        return course_out(course, client_today(db, client_id))

    for field, (_, new) in diffs.items():
        setattr(course, field, new)
    parts = [f"{COURSE_FIELDS[f]} updated" if f in LONG_FIELDS else f"{COURSE_FIELDS[f]}: {_shown(f, old)} → {_shown(f, new)}"
             for f, (old, new) in diffs.items() if f != "sort_order"]
    if status_changed:
        course.status = status
        parts.append("Hidden from callers" if status == "HIDDEN" else "Offered to callers again")
    if parts:  # reordering alone isn't worth a history entry
        action = ("COURSE_HIDDEN" if status == "HIDDEN" else "COURSE_SHOWN") if status_changed and not diffs else "COURSE_UPDATED"
        _record(db, client_id, course, action, "; ".join(parts), actor, diffs)
    db.commit()
    db.refresh(course)
    return course_out(course, client_today(db, client_id))


def add_batch(db: Session, client_id: str, course_id: str, data: Dict[str, Any], actor: Actor) -> Dict[str, Any]:
    course = _course(db, client_id, course_id)
    values = {k: _clean(v) for k, v in data.items() if k in BATCH_FIELDS}
    if not values.get("start_date") or not values.get("timings"):
        raise HTTPException(status_code=422, detail="Add the start date and timings.")
    _check_date(db, client_id, values["start_date"])
    batch = CourseBatch(course_id=course.id, client_id=client_id, seats=values.pop("seats", None) or "OPEN", **values)
    db.add(batch)
    _record(db, client_id, course, "BATCH_ADDED",
            f"Batch added: {spoken_date(batch.start_date)}, {batch.timings}", actor)
    db.commit()
    db.refresh(course)
    return course_out(course, client_today(db, client_id))


def update_batch(db: Session, client_id: str, course_id: str, batch_id: str, data: Dict[str, Any],
                 actor: Actor) -> Dict[str, Any]:
    course = _course(db, client_id, course_id)
    batch = _batch(db, course, batch_id)
    diffs: Dict[str, List[Any]] = {}
    for field, value in data.items():
        if field not in BATCH_FIELDS:
            continue
        value = _clean(value)
        if field in ("start_date", "timings", "seats") and not value:
            raise HTTPException(status_code=422, detail=f"{BATCH_FIELDS[field]} can't be empty.")
        if value != getattr(batch, field):
            diffs[field] = [getattr(batch, field), value]
    if "start_date" in diffs:
        _check_date(db, client_id, diffs["start_date"][1])
    if diffs:
        label = spoken_date(batch.start_date)
        for field, (_, new) in diffs.items():
            setattr(batch, field, new)
        summary = "; ".join(f"{BATCH_FIELDS[f]}: {_shown(f, old)} → {_shown(f, new)}" for f, (old, new) in diffs.items())
        _record(db, client_id, course, "BATCH_UPDATED", f"Batch {label}: {summary}", actor, diffs)
        db.commit()
    db.refresh(course)
    return course_out(course, client_today(db, client_id))


def delete_batch(db: Session, client_id: str, course_id: str, batch_id: str, actor: Actor) -> Dict[str, Any]:
    course = _course(db, client_id, course_id)
    batch = _batch(db, course, batch_id)
    _record(db, client_id, course, "BATCH_REMOVED",
            f"Batch removed: {spoken_date(batch.start_date)}, {batch.timings}", actor)
    db.delete(batch)
    db.commit()
    db.refresh(course)
    return course_out(course, client_today(db, client_id))
