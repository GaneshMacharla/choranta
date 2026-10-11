import os
import sys
from typing import List, Optional
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Choranta Internal Agent Studio"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api"
    ENVIRONMENT: str = "development"  # development, test, production

    # Database
    DATABASE_URL: str = "sqlite:///./choranta_dev.db"

    # Supabase Settings (used for Supabase Auth JWT verification)
    SUPABASE_URL: Optional[str] = None
    SUPABASE_JWT_SECRET: Optional[str] = None
    SUPABASE_SERVICE_ROLE_KEY: Optional[str] = None
    SUPABASE_ANON_KEY: Optional[str] = None

    # Internal Auth / JWT verification secret
    JWT_SECRET_KEY: Optional[str] = None
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours

    # Initial Platform Administrator Seed Credentials (empty by default)
    INITIAL_ADMIN_EMAIL: Optional[str] = None
    INITIAL_ADMIN_PASSWORD: Optional[str] = None
    INITIAL_ADMIN_NAME: str = "Choranta Platform Admin"

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    # --------------------------------------------------------
    # Voice Runtime & Providers (Phase 3B)
    # --------------------------------------------------------
    RUNTIME_MODE: str = "mock"  # "mock" or "provider"
    CARTESIA_API_KEY: Optional[str] = None
    CARTESIA_STT_MODEL: str = "ink-whisper"
    CARTESIA_ENABLE_STREAMING_STT: bool = False
    CARTESIA_TTS_MODEL: str = "sonic-3"
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_FALLBACK_TO_MOCK: bool = True

    # Mock-only pricing estimates. These never contribute to production billing.
    MOCK_STT_PRICE_PER_MINUTE: float = 0.02
    MOCK_TTS_PRICE_PER_MINUTE: float = 0.03
    MOCK_LLM_INPUT_PRICE_PER_MILLION_TOKENS: float = 0.10
    MOCK_LLM_OUTPUT_PRICE_PER_MILLION_TOKENS: float = 0.40


    # Resource safety bounds
    MAX_AUDIO_FRAME_SIZE: int = 65536  # 64 KB max per frame
    MAX_MESSAGE_SIZE: int = 1048576    # 1 MB max per WebSocket message
    MAX_SESSION_DURATION_SECONDS: int = 3600  # 1 hour max session
    MAX_CONCURRENT_SESSIONS: int = 100

    # --------------------------------------------------------
    # Telephony Integration (Phase 3C)
    # --------------------------------------------------------
    EXOTEL_ACCOUNT_SID: Optional[str] = None
    EXOTEL_API_KEY: Optional[str] = None
    EXOTEL_API_TOKEN: Optional[str] = None
    EXOTEL_SUBDOMAIN: str = "api.exotel.com"  # api.in.exotel.com for the Mumbai cluster
    EXOTEL_WEBHOOK_SECRET: Optional[str] = None
    TELEPHONY_BASE_URL: Optional[str] = None
    EXOTEL_FLOW_ID: Optional[str] = "1341429"
    RUN_REAL_TELEPHONY_TESTS: bool = False


    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        env = (self.ENVIRONMENT or "").strip().lower()
        mode = (self.RUNTIME_MODE or "").strip().lower()
        if mode == "provider":
            mode = "real"
            object.__setattr__(self, "RUNTIME_MODE", mode)
        if mode not in ("mock", "real"):
            raise ValueError("RUNTIME_MODE must be either 'mock' or 'real'.")
        if env in ("test", "testing"):
            object.__setattr__(self, "RUNTIME_MODE", "mock")
            mode = "mock"

        # Normalize postgresql scheme if postgres:// from Supabase
        if self.DATABASE_URL.startswith("postgres://"):
            object.__setattr__(self, "DATABASE_URL", self.DATABASE_URL.replace("postgres://", "postgresql://", 1))

        if env == "production":
            # 1. Enforce PostgreSQL for production
            if not (self.DATABASE_URL.startswith("postgresql://") or self.DATABASE_URL.startswith("postgresql+psycopg2://")):
                raise ValueError(
                    "CRITICAL: Production DATABASE_URL must be a PostgreSQL connection string (Supabase PostgreSQL). "
                    "SQLite is strictly prohibited in production."
                )

            # 2. Enforce strong JWT secret or Supabase JWT secret
            active_secret = self.SUPABASE_JWT_SECRET or self.JWT_SECRET_KEY
            if not active_secret or len(active_secret.strip()) < 32:
                raise ValueError(
                    "CRITICAL: Production requires either SUPABASE_JWT_SECRET or JWT_SECRET_KEY "
                    "with a minimum length of 32 characters."
                )

            # 3. Enforce secure CORS origins (no wildcard with credentials)
            if "*" in self.CORS_ORIGINS:
                raise ValueError(
                    "CRITICAL: Production CORS_ORIGINS cannot contain wildcard '*' when credentials are enabled."
                )

        # 4. If RUNTIME_MODE is provider, validate keys
        if mode == "real":
            if not self.CARTESIA_API_KEY:
                raise ValueError("CRITICAL: RUNTIME_MODE='provider' requires CARTESIA_API_KEY to be configured.")
            if not self.GEMINI_API_KEY:
                raise ValueError("CRITICAL: RUNTIME_MODE='provider' requires GEMINI_API_KEY to be configured.")

        else:
            # Development/Testing fallback handling
            if not self.JWT_SECRET_KEY and not self.SUPABASE_JWT_SECRET:
                # Assign deterministic local dev secret if none provided in dev mode
                object.__setattr__(self, "JWT_SECRET_KEY", "choranta-local-development-ephemeral-key-min32chars!")

            if not self.INITIAL_ADMIN_EMAIL:
                object.__setattr__(self, "INITIAL_ADMIN_EMAIL", "admin@choranta.internal")

            if not self.INITIAL_ADMIN_PASSWORD:
                object.__setattr__(self, "INITIAL_ADMIN_PASSWORD", "chorantaAdmin2026!")

        return self


settings = Settings()
