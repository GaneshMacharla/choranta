from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.core.security import generate_unique_id


class TestScenario(Base):
    __tablename__ = "test_scenarios"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("scn_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    caller_goal = Column(Text, nullable=False, default="")
    turns_json = Column(JSON, nullable=False, default=list)
    expected_json = Column(JSON, nullable=False, default=dict)
    provider_config_json = Column(JSON, nullable=False, default=dict)
    initial_mock_state_json = Column(JSON, nullable=False, default=dict)
    evaluation_config_json = Column(JSON, nullable=False, default=dict)
    max_turns = Column(Integer, nullable=False, default=10)
    timeout_seconds = Column(Integer, nullable=False, default=120)
    version_number = Column(Integer, nullable=False, default=1)
    status = Column(String(32), nullable=False, default="ACTIVE", index=True)
    created_by = Column(String(64), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    client = relationship("Client")
    agent = relationship("Agent")
    agent_version = relationship("AgentVersion")
    runs = relationship("TestRun", back_populates="scenario", cascade="all, delete-orphan")


class TestRun(Base):
    __tablename__ = "test_runs"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("run_"))
    scenario_id = Column(String(64), ForeignKey("test_scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_id = Column(String(64), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True)
    agent_version_id = Column(String(64), ForeignKey("agent_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    runtime_session_id = Column(String(64), ForeignKey("runtime_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    status = Column(String(16), nullable=False, default="RUNNING", index=True)
    provider_mode = Column(String(16), nullable=False, default="mock")
    scenario_version = Column(Integer, nullable=False, default=1)
    started_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
    ended_at = Column(DateTime, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    turn_count = Column(Integer, nullable=False, default=0)
    summary_json = Column(JSON, nullable=False, default=dict)
    usage_json = Column(JSON, nullable=False, default=dict)
    final_state_json = Column(JSON, nullable=False, default=dict)
    metrics_json = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    scenario = relationship("TestScenario", back_populates="runs")
    events = relationship("TestRunEvent", back_populates="run", cascade="all, delete-orphan", order_by="TestRunEvent.timestamp.asc()")


class TestRunEvent(Base):
    __tablename__ = "test_run_events"

    id = Column(String(64), primary_key=True, index=True, default=lambda: generate_unique_id("runevt_"))
    run_id = Column(String(64), ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(String(64), nullable=True, index=True)
    event_type = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    duration_ms = Column(Integer, nullable=True)
    metadata_json = Column(JSON, nullable=False, default=dict)

    run = relationship("TestRun", back_populates="events")
