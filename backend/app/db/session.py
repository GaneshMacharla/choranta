import logging
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings

logger = logging.getLogger("choranta.db")

# Normalize PostgreSQL URL if provided as postgres://
db_url = settings.DATABASE_URL
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

# Configure engine parameters based on database dialect
if db_url.startswith("sqlite"):
    if settings.ENVIRONMENT == "production":
        raise RuntimeError("FATAL: SQLite is disallowed in production mode.")
    logger.info("Using SQLite database for development/testing environment.")
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False},
        echo=False
    )
else:
    logger.info("Configuring production PostgreSQL / Supabase connection pool.")
    # Supabase's session pooler allows 15 clients in total; stay under it (with room for scripts/tests)
    # so a burst queues for a free connection instead of failing with EMAXCONNSESSION
    engine = create_engine(
        db_url,
        pool_size=5,
        max_overflow=5,
        pool_timeout=30,
        pool_pre_ping=True,
        pool_recycle=300,
        echo=False
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    """FastAPI database session dependency with transactional safety."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
