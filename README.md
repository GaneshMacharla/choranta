# CHORANTA — Internal Agent Studio (Phase 1)

Choranta is the internal operating system used by our engineering and operations team to build, configure, test, and operate AI voice employees for enterprise business clients (hospitals, clinics, salons, hotels, real estate, etc.).

> **Important**: This is an internal operations studio, not a generic SaaS dashboard or consumer chat application.

---

## Architecture Overview

```text
Frontend (React + Vite + TypeScript + Tailwind)
    ↓  (Authenticated REST API with JWT)
FastAPI Application (Python 3.11)
    ↓
Application Services (Auth, Clients, Agents, Dashboard)
    ↓
Repositories (Abstracted Data Access)
    ↓
Domain Models (SQLAlchemy ORM)
    ↓
Supabase PostgreSQL (or local SQLite fallback)
```

---

## Phase 1 Deliverables

1. **Database Foundation & Reproducible Migrations**:
   - `users`: Internal operators and administrators with role-based access (`ADMIN`, `OPERATOR`).
   - `clients`: Enterprise accounts categorized across 8 business types (`CLINIC`, `HOSPITAL`, `SALON`, `REAL_ESTATE`, `HOTEL`, `RESTAURANT`, `CORPORATE`, `OTHER`).
   - `agents`: Voice employees mapped to clients with unique non-sequential IDs (`agt_xxxxxxxx`) and lifecycle states (`DRAFT`, `TESTING`, `READY`, `DEPLOYED`, `PAUSED`, `ARCHIVED`).
   - `agent_versions`: Immutable version snapshots with reserved Canonical Agent Spec.
   - Migration file: [`supabase/migrations/001_initial_schema.sql`](file:///c:/GANI%20MACHARLA/projects/choranta/supabase/migrations/001_initial_schema.sql).

2. **Backend Service**:
   - Layered architecture: `app/api` $\rightarrow$ `app/services` $\rightarrow$ `app/repositories` $\rightarrow$ `app/models`.
   - Secure PBKDF2 password hashing & HMAC verification.
   - JWT token issuance & Bearer authentication protection.
   - Strict Pydantic v2 schemas for all requests and responses.
   - Initial platform administrator auto-seeded on first run.

3. **Frontend Application**:
   - Enterprise Linear/Vercel-inspired desktop-first operations console.
   - Protected routing with automatic redirect to `/login`.
   - Comprehensive UI kit: `Button`, `Input`, `Select`, `Modal`, `Table`, `Badge`, `Card`, `EmptyState`, `LoadingState`, `ErrorState`.
   - Real database-backed metrics dashboard (0 if empty, no fake data).
   - Full CRUD management for Clients and AI Employees.
   - Canonical Agent Spec model preview & Phase 2 configuration placeholders.

---

## Quickstart

### 1. Backend Setup

```powershell
# Navigate to backend directory
cd backend

# (Optional) configure .env from template
cp .env.example .env

# Run FastAPI development server
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

In production run `python -m app.serve` instead (HOST / PORT from the environment). On SIGTERM it stops
placing new calls, reports 503 on `/health`, and waits for live calls to finish (up to `SHUTDOWN_DRAIN_S`)
before exiting, so deploys don't hang up on callers. Set the host's stop grace period above `SHUTDOWN_DRAIN_S`
(e.g. Docker `stop_grace_period`, Kubernetes `terminationGracePeriodSeconds`). Run a single worker: call limits
are tracked in memory.

* API Docs available at: `http://127.0.0.1:8000/docs`
* Health Check: `http://127.0.0.1:8000/health`

### 2. Frontend Setup

```powershell
# Navigate to frontend directory
cd frontend

# Run Vite development server
npm run dev
```

* Frontend application available at: `http://localhost:5173`

### 3. Seed Credentials

* **Internal Administrator Email**: `admin@choranta.internal`
* **Default Password**: `chorantaAdmin2026!`

---

## Automated Tests

Run the complete backend automated test suite:

```powershell
python -m pytest -v
```

All 14 integration and unit test scenarios verify:
* Internal login, JWT validation, and invalid credentials rejection
* Protected route rejection for unauthenticated users
* Client creation, validation (email/phone/name), and duplicate rejection
* AI Employee creation with unique `agt_xxxxxxxx` IDs and `DRAFT` status
* Agent lifecycle status updates (`READY`) and version history inspection
* Live database-backed dashboard metrics aggregation
