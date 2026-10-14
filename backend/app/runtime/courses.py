"""
A coaching centre's Course catalogue as its AI employees see it on a call: every active course with its fee and
details, and only the batches still to start (full ones marked, never offered).

Always given whole, never retrieved in pieces, so a fee or batch date can't go missing. Read when the call starts,
so the centre's edits apply from the next call.
"""
import re
from datetime import date
from typing import List, Optional

from sqlalchemy.orm import Session

from app.runtime.today import spoken_date

CATALOGUE_MARKER = "Course catalogue"
MODE_LABELS = {"ONLINE": "Online", "CLASSROOM": "Classroom", "BOTH": "Online and classroom"}


def _one_line(text: Optional[str]) -> str:
    """Multi-line answers (e.g. "what's covered") as one line, so each course stays a compact block."""
    parts = [p.strip(" -•\t") for p in re.split(r"[\r\n]+", text or "")]
    return "; ".join(p for p in parts if p)


def upcoming_batches(course, today: date) -> List:
    """Batches that haven't started yet: a batch starting today is still offered today."""
    return [b for b in course.batches if b.start_date and b.start_date >= today]


def _batch_text(batch, course) -> str:
    text = f"{spoken_date(batch.start_date)}, {_one_line(batch.timings)}"
    extras = [MODE_LABELS.get(batch.mode, "") if batch.mode and batch.mode != course.mode else "",
              _one_line(batch.medium) if batch.medium and batch.medium != course.medium else ""]
    extras = [e for e in extras if e]
    if extras:
        text += f" ({', '.join(extras)})"
    return text + (" - FULL" if batch.seats == "FULL" else "")


def _course_text(course, today: date) -> str:
    head = course.name + (f" (also called: {_one_line(course.aliases)})" if course.aliases else "")
    if course.category:
        head += f" · {course.category}"
    facts = [("For", course.audience), ("Eligibility", course.eligibility), ("Duration", course.duration),
             ("Mode", MODE_LABELS.get(course.mode, course.mode)), ("Medium", course.medium)]
    lines = [f"- {head}", "  " + "; ".join(f"{label}: {_one_line(value)}" for label, value in facts if value)]
    lines.append(f"  Fee: {_one_line(course.fee)}" + (f"; Instalments: {_one_line(course.instalments)}" if course.instalments else ""))
    if course.highlights:
        lines.append(f"  Covers: {_one_line(course.highlights)}")
    if course.certificate is not None:
        lines.append(f"  Certificate on completion: {'yes' if course.certificate else 'no'}")
    if course.extra_details:
        lines.append(f"  More: {_one_line(course.extra_details)}")
    batches = upcoming_batches(course, today)
    if batches:
        lines.append("  Upcoming batches: " + " | ".join(_batch_text(b, course) for b in batches))
    else:
        lines.append("  Upcoming batches: none scheduled yet. Take the caller's name and interest so the centre can "
                     "tell them when the next batch is announced.")
    return "\n".join(lines)


def course_catalogue(db: Session, client_id: Optional[str], today: date) -> str:
    """The catalogue block for the instructions ("" when the client has no active courses)."""
    from app.models.course import Course

    if not client_id:
        return ""
    courses = (db.query(Course).filter(Course.client_id == client_id, Course.status == "ACTIVE")
               .order_by(Course.sort_order, Course.name).all())
    if not courses:
        return ""
    names = ", ".join(c.name for c in courses)
    lines = [
        f"### {CATALOGUE_MARKER} ({len(courses)} courses: {names})",
        "Quote fees and batch dates exactly as written here. Offer only the upcoming batches listed; a batch marked "
        "FULL is never offered (say it's full and suggest another). If the caller isn't sure which course they want, "
        "ask what they're interested in or about their background, then suggest courses from this list.",
    ]
    lines += [_course_text(course, today) for course in courses]
    return "\n".join(lines)
