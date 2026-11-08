import os

# Before any app import: app startup (init_db) must never touch the database in the developer's .env
STARTUP_DATABASE_FILE = "./test_choranta_startup.db"
os.environ["DATABASE_URL"] = f"sqlite:///{STARTUP_DATABASE_FILE}"
# Tests set payment modes themselves; a developer's .env must not switch them on
os.environ["SIMULATED_PAYMENTS"] = "false"
# Knowledge bases go to an in-memory MongoDB, never the Atlas cluster in the developer's .env
os.environ["MONGODB_URI"] = "mongomock://test"
# Phone numbers come from the simulated carrier: tests never reach Vobiz
os.environ["PHONE_NUMBER_MOCK_MODE"] = "true"

from datetime import timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.core.security import hash_password, create_access_token
from app.db.session import Base, get_db
from app.main import app
from app.models.user import User
from app.services.auth_service import AuthService
from app.db.init_db import seed_catalogs

# Ensure test mode
object.__setattr__(settings, "ENVIRONMENT", "test")
# Existing suites cover the plan and GST paths; pay-as-you-go without GST is tested by patching these back
object.__setattr__(settings, "PAYG_ONLY", False)
object.__setattr__(settings, "GST_REGISTERED", True)
# Tests never reach real providers, whatever RUNTIME_MODE the developer's .env sets
object.__setattr__(settings, "RUNTIME_MODE", "mock")
for _override in ("STT_PROVIDER_OVERRIDE", "TTS_PROVIDER_OVERRIDE", "LLM_PROVIDER_OVERRIDE"):
    object.__setattr__(settings, _override, "")  # each test agent uses its own providers
# Billing tests enable wallet enforcement explicitly; other tests place calls freely
object.__setattr__(settings, "BILLING_ENFORCED", False)
# Existing suites cover invoices; test_invoices_off.py covers running without them
object.__setattr__(settings, "INVOICES_ENABLED", True)
# Most suites place calls with agents that never went live; test_agent_creation_flow.py covers the rule
object.__setattr__(settings, "AGENT_STATUS_ENFORCED", False)
# Suites dial through the mock Vobiz carrier, with no dial pacing; capacity tests set the limits they check
object.__setattr__(settings, "TELEPHONY_PROVIDER", "vobiz")
object.__setattr__(settings, "VOBIZ_AUTH_ID", "MA_TEST")
object.__setattr__(settings, "VOBIZ_AUTH_TOKEN", "test_token")
object.__setattr__(settings, "VOBIZ_CPS", 0)
object.__setattr__(settings, "VOBIZ_MAX_CONCURRENT_CALLS", 1000)
# Existing suites set the limits they test; test_call_capacity.py covers the Sarvam limits and the inbound reserve
for _limit in ("SARVAM_LLM_REQUESTS_PER_MIN", "SARVAM_STT_WS_LIMIT", "SARVAM_TTS_WS_LIMIT", "INBOUND_RESERVED_LINES",
               "SARVAM_WS_OPEN_SPACING_MS"):
    object.__setattr__(settings, _limit, 0)
from app.runtime.providers.registry import default_registry
default_registry.enable_mock_providers()

TEST_DATABASE_URL = "sqlite:///./test_choranta_run.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture(autouse=True)
def fresh_rate_limits():
    """Rate limits on buying and releasing numbers count per test, not across the suite."""
    from app.core import rate_limit
    rate_limit.reset()
    yield


@pytest.fixture(autouse=True)
def fresh_call_capacity():
    """An outbound pause or counters from one test must not carry into the next."""
    from app.runtime.providers.sarvam import limits
    from app.services import call_capacity
    call_capacity.reset()
    limits.reset()
    yield
    call_capacity.reset()
    limits.reset()


@pytest.fixture(autouse=True)
def empty_tts_cache():
    """Speech audio cached by one test must not replace synthesis in the next."""
    from app.runtime.telephony import tts_cache
    tts_cache.clear()
    yield
    tts_cache.clear()



@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    
    # Seed ADMIN
    auth_service = AuthService(db)
    auth_service.seed_initial_admin()
    seed_catalogs(db)
    from app.services.call_scripts import seed_standard_scripts
    seed_standard_scripts(db)
    
    # Seed OPERATOR for role tests
    operator = db.query(User).filter(User.email == "operator@choranta.internal").first()
    if not operator:
        db.add(User(
            id="usr_test_operator",
            email="operator@choranta.internal",
            name="Test Operator",
            hashed_password=hash_password("operatorPass2026!"),
            role="OPERATOR",
            status="ACTIVE"
        ))
        db.commit()

    db.close()
    yield
    try:
        test_engine.dispose()
        Base.metadata.drop_all(bind=test_engine)
    except Exception:
        pass
    test_engine.dispose()
    from app.db.session import engine as startup_engine
    startup_engine.dispose()  # release the file so it can be deleted on Windows
    for leftover in ("./test_choranta.db", STARTUP_DATABASE_FILE):
        if os.path.exists(leftover):
            try:
                os.remove(leftover)
            except Exception:
                pass



@pytest.fixture
def db():
    connection = test_engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client):
    """Admin credentials header."""
    response = client.post(
        "/api/auth/login",
        json={
            "email": settings.INITIAL_ADMIN_EMAIL,
            "password": settings.INITIAL_ADMIN_PASSWORD
        }
    )
    assert response.status_code == 200, f"Admin login failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def operator_headers(client):
    """Operator credentials header (operators sign in with Google, so mint the same token directly)."""
    from app.core.security import create_access_token
    token = create_access_token(
        subject="usr_test_operator",
        claims={"email": "operator@choranta.internal", "role": "OPERATOR", "name": "Test Operator"},
    )
    return {"Authorization": f"Bearer {token}"}
