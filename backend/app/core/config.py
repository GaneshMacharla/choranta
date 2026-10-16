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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days; the app renews it on each visit (POST /auth/refresh)

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
    # Newer Cartesia voices (e.g. Akash, Aryan, Smruti) only run on this model; used for them automatically
    CARTESIA_TTS_FALLBACK_MODEL: str = "sonic-3.5"
    # Stream speech over one long-lived Cartesia WebSocket (no connection setup per sentence); HTTP fallback
    CARTESIA_TTS_WEBSOCKET: bool = True
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-3.8-flash"
    GEMINI_FALLBACK_TO_MOCK: bool = True
    # Sarvam LLM (OpenAI-compatible chat completions)
    SARVAM_API_KEY: Optional[str] = None
    SARVAM_BASE_URL: str = "https://api.sarvam.ai/v1"
    SARVAM_LLM_MODEL: str = "sarvam-105b-conversations"  # Sarvam's model for real-time voice agents
    SARVAM_REASONING_EFFORT: str = "none"                # "none" disables thinking for low latency
    SARVAM_MAX_TOKENS: int = 400
    SARVAM_TIMEOUT_S: float = 10.0
    SARVAM_FALLBACK_TO_GEMINI: bool = True               # use Gemini for a turn if Sarvam errors
    SARVAM_STT_MODEL: str = "saaras:v4"
    SARVAM_STT_LANGUAGE: str = "unknown"                 # "unknown" = auto-detect (Hindi/English/Telugu/...)
    SARVAM_TTS_MODEL: str = "bulbul:v3"
    SARVAM_TTS_SPEAKER: str = "shubh"                    # used when the agent's voice id isn't a Sarvam speaker
    SARVAM_TTS_LANGUAGE: str = ""                        # empty = agent's primary language
    SARVAM_TTS_STREAMING: bool = True                    # WebSocket streaming; REST fallback

    # Use these providers for every agent regardless of its own settings (e.g. "sarvam"); empty = agent's choice
    STT_PROVIDER_OVERRIDE: str = ""
    TTS_PROVIDER_OVERRIDE: str = ""
    LLM_PROVIDER_OVERRIDE: str = ""
    # Streaming requests that produce no output within this many seconds move on to the next model
    GEMINI_FIRST_TOKEN_TIMEOUT_S: float = 3.0
    # Cartesia plans cap concurrent requests (TTS + STT); stay at or below the plan's limit
    CARTESIA_MAX_CONCURRENCY: int = 2

    # --------------------------------------------------------
    # Call cost estimates (set these to your plans' actual rates)
    # --------------------------------------------------------
    TELEPHONY_RATE_PER_MINUTE_INR: float = 0.80     # Exotel outbound to mobile (third-party estimates ₹0.60–1.20)
    TELEPHONY_BILLING_PULSE_SECONDS: int = 60       # carrier bills per started pulse
    STT_USD_PER_MINUTE: float = 0.00118             # Cartesia ink-whisper batch: 1 credit / 2 s at Startup $39.2 per 1M credits
    TTS_USD_PER_MINUTE: float = 0.0353              # Cartesia Sonic: ~900 chars (credits) per audio minute at Startup $39.2 per 1M
    LLM_INPUT_USD_PER_MILLION_TOKENS: float = 0.30  # Gemini 3.5 Flash-Lite input
    LLM_OUTPUT_USD_PER_MILLION_TOKENS: float = 2.50 # Gemini 3.5 Flash-Lite output
    SARVAM_INPUT_INR_PER_MILLION_TOKENS: float = 15.0    # sarvam-105b(-conversations), Sarvam pricing page
    SARVAM_OUTPUT_INR_PER_MILLION_TOKENS: float = 60.0
    SARVAM_STT_INR_PER_HOUR: float = 30.0                # billed per second of audio
    SARVAM_TTS_INR_PER_10K_CHARS: float = 30.0           # Bulbul v3
    USD_TO_INR: float = 88.0
    # Pricing defaults until an admin sets them in Settings (stored in pricing_settings)
    DEFAULT_PROFIT_PERCENT: float = 40.0
    # Credits: 1 credit = Rs 1 (pre-GST). Calls cost real cost + profit %; this is only the "about N minutes"
    # estimate on plans until there are recent calls to average
    DEFAULT_CREDITS_PER_MINUTE: float = 7.0

    # --------------------------------------------------------
    # Billing & GST invoices
    # --------------------------------------------------------
    COMPANY_LEGAL_NAME: str = "Choranta"
    COMPANY_GSTIN: str = ""
    COMPANY_ADDRESS: str = ""
    COMPANY_STATE_CODE: str = "36"            # GST state code of the company (36 = Telangana)
    INVOICE_PREFIX: str = "CHR"
    INVOICE_SAC_CODE: str = "998319"          # confirm the correct SAC with your CA
    GST_RATE_PERCENT: float = 18.0
    # Not GST-registered yet: no GST is charged and payments get a plain receipt, not a tax invoice.
    # Once registered, set GST_REGISTERED=true and COMPANY_GSTIN in .env.
    GST_REGISTERED: bool = False
    # Monthly plans are retired: clients buy credits and pay per call (existing plans run out, then stop)
    PAYG_ONLY: bool = True
    DEFAULT_PAYG_MAX_CONCURRENT_CALLS: int = 3  # until an admin sets it in Settings
    PAYMENT_UPI_ID: str = ""
    PAYMENT_BANK_DETAILS: str = ""
    BILLING_ENFORCED: bool = True             # block new billable calls when the wallet balance is <= 0
    SUBSCRIPTION_GRACE_DAYS: int = 3          # calls keep working this long after a plan period ends unpaid
    MIN_WALLET_TOPUP_INR: float = 500.0       # smallest online wallet top-up (GST included when registered)
    NUMBER_GRACE_DAYS: int = 3                # unpaid number rent: released back to Exotel after this
    NUMBER_RENTAL_CHECK_S: int = 900          # how often number rent is renewed / released
    CAMPAIGN_TICK_S: int = 5                  # how often the campaign dispatcher checks for calls to place
    CAMPAIGN_MAX_DIALS_PER_MIN: int = 60      # pacing across all campaigns (Exotel default: 60 calls/minute)

    # Razorpay (online payments for plans and wallet top-ups)
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    # Testing only: plan purchases and credit top-ups succeed without Razorpay (no money moves).
    # Refused when ENVIRONMENT=production.
    SIMULATED_PAYMENTS: bool = False

    # --------------------------------------------------------
    # Google Sign-In
    # --------------------------------------------------------
    GOOGLE_CLIENT_ID: str = ""
    CLIENT_SELF_SIGNUP: bool = True           # new Google accounts sign up as clients (staff stay invite-only)

    # --------------------------------------------------------
    # Phone call behaviour (cost control)
    # --------------------------------------------------------
    VOICE_MAX_REPLY_CHARS: int = 130          # stop the agent's reply after the sentence that crosses this (~7 s of speech; people talk in short turns)
    VOICE_PREFETCH_SENTENCES: int = 1         # sentences synthesized ahead of playback (unheard audio is still billed)
    VOICE_TTS_CACHE_MB: int = 64              # repeated sentences (greeting, farewell, common replies) replay from memory; 0 = off
    CALL_SILENCE_REPROMPT_S: float = 5.0      # caller silent this long -> "Are you still there?"
    CALL_SILENCE_HANGUP_S: float = 5.0        # still silent this long after the reprompt -> goodbye and hang up
    CALL_MAX_DURATION_S: int = 600            # wrap up and hang up after this many seconds

    # Human-like turn-taking
    VOICE_END_SILENCE_MS: int = 550           # caller silence that ends their turn (unfinished sentences get VOICE_INCOMPLETE_HOLD_MS more)
    VOICE_INCOMPLETE_HOLD_MS: int = 900       # extra wait when the caller trailed off mid-thought ("my budget is..."); 0 = off
    VOICE_SLOW_REPLY_ACK_MS: int = 1800       # say a short "Okay." if the reply hasn't started by then; 0 = off
    VOICE_TOOL_FILLER: bool = True            # say "One moment, let me check." while a tool runs (unless the agent already did)

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
    # ExoPhone shown as caller ID on outbound calls placed directly by an agent
    EXOTEL_CALLER_ID: Optional[str] = None
    DEMO_LEADS_API_KEY: Optional[str] = None  # dev-only: client key the /demo/lead-form page sends leads with
    EXOTEL_NUMBERS_MOCK: bool = False         # fake number search/purchase (no Exotel calls) for local testing
    # Where phone call recordings (stereo WAV: caller left, agent right) are stored
    RECORDINGS_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "recordings")
    # Business verification (KYC) documents clients upload before buying numbers; private, admin download only
    KYC_UPLOAD_DIR: str = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads", "kyc")
    RUN_REAL_TELEPHONY_TESTS: bool = False


    @property
    def EFFECTIVE_GST_RATE_PERCENT(self) -> float:
        """GST charged on payments: the GST rate once registered, else 0."""
        return self.GST_RATE_PERCENT if self.GST_REGISTERED else 0.0

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

            # 3. Simulated payments would hand out plans and credits for free
            if self.SIMULATED_PAYMENTS:
                raise ValueError("CRITICAL: SIMULATED_PAYMENTS must be false in production.")

            # 4. Enforce secure CORS origins (no wildcard with credentials)
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
