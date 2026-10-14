from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.core.security import generate_unique_id


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Course(Base):
    """
    One course a coaching centre offers. The centre keeps it up to date in the client portal (and Choranta's team on
    the client page); its AI employees quote fees and batches only from here (runtime/courses.py).
    """
    __tablename__ = "courses"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("crs_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    aliases = Column(Text, nullable=True)  # other names callers use, e.g. "CGL, staff selection"
    category = Column(String(64), nullable=True)
    audience = Column(Text, nullable=True)  # who it's for
    eligibility = Column(Text, nullable=True)
    duration = Column(String(64), nullable=False)
    mode = Column(String(16), nullable=False, default="BOTH")  # ONLINE, CLASSROOM, BOTH
    medium = Column(String(128), nullable=True)  # language of teaching, e.g. "Telugu, English"
    fee = Column(String(64), nullable=False)  # as the centre quotes it, e.g. "₹25,000"
    instalments = Column(Text, nullable=True)
    highlights = Column(Text, nullable=True)  # what's covered
    certificate = Column(Boolean, nullable=True)
    extra_details = Column(Text, nullable=True)  # exam, test series / tools, projects, placement
    status = Column(String(16), nullable=False, default="ACTIVE", index=True)  # ACTIVE, HIDDEN
    sort_order = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    batches = relationship("CourseBatch", back_populates="course", cascade="all, delete-orphan",
                           order_by="CourseBatch.start_date")

    def __repr__(self) -> str:
        return f"<Course {self.id}: {self.name}>"


class CourseBatch(Base):
    """A batch of a course. Offered to callers until its start date has passed, and never while FULL."""
    __tablename__ = "course_batches"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("bat_"))
    course_id = Column(String(64), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    start_date = Column(Date, nullable=False, index=True)
    timings = Column(String(255), nullable=False)  # e.g. "Weekdays 7–9 PM"
    mode = Column(String(16), nullable=True)  # None = the course's mode
    medium = Column(String(128), nullable=True)  # None = the course's medium
    seats = Column(String(16), nullable=False, default="OPEN")  # OPEN, FULL
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    course = relationship("Course", back_populates="batches")


class CourseChange(Base):
    """History of catalogue edits, so Choranta's team can see what a centre changed (fee changes flagged)."""
    __tablename__ = "course_changes"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("crc_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    course_id = Column(String(64), nullable=True, index=True)
    course_name = Column(String(255), nullable=False)
    action = Column(String(32), nullable=False)  # COURSE_ADDED, COURSE_UPDATED, COURSE_HIDDEN, COURSE_SHOWN, BATCH_*
    summary = Column(Text, nullable=False)  # e.g. "Fee: ₹25,000 → ₹27,000"
    changes = Column(JSON, nullable=False, default=dict)  # field -> [old, new]
    fee_changed = Column(Boolean, nullable=False, default=False)
    actor = Column(String(16), nullable=False)  # CLIENT, TEAM
    actor_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)
