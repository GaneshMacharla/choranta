import os
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
from app.runtime.providers.registry import default_registry
default_registry.enable_mock_providers()

TEST_DATABASE_URL = "sqlite:///./test_choranta_run.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)



@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    
    # Seed ADMIN
    auth_service = AuthService(db)
    auth_service.seed_initial_admin()
    seed_catalogs(db)
    
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
    if os.path.exists("./test_choranta.db"):
        try:
            os.remove("./test_choranta.db")
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
    """Operator credentials header."""
    response = client.post(
        "/api/auth/login",
        json={
            "email": "operator@choranta.internal",
            "password": "operatorPass2026!"
        }
    )
    assert response.status_code == 200, f"Operator login failed: {response.text}"
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
