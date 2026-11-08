# Production checklist

Go through this before every production launch or server move. Each item says what to do and why it matters.

## 1. How the server runs

- [ ] **Start with `python -m app.serve`, not `uvicorn ...`.**
  Plain uvicorn hangs up every live call on restart. `app.serve` stops taking new calls, lets live ones finish
  (up to `SHUTDOWN_DRAIN_S`, default 600 s), then exits. Send a second stop signal to force it.
- [ ] **Set the host's stop grace period above `SHUTDOWN_DRAIN_S`** (Docker `stop_grace_period: 11m`,
  Kubernetes `terminationGracePeriodSeconds: 660`). Otherwise the host kills the server mid-drain, because
  Docker's default is 10 s.
- [ ] **Run exactly ONE worker / ONE server.** Call limits (platform, per-client, Vobiz, Sarvam) are counted in
  memory. With two workers, each counts only its own calls and the limits can be exceeded. Scaling out first
  needs those counts moved to Redis.
- [ ] **Point the health check at `/health`.** It returns 503 `draining` during shutdown, so a load balancer
  stops sending traffic to it.
- [ ] **Host in India (Mumbai, e.g. AWS `ap-south-1`).** Vobiz and Sarvam are in India, and a server abroad
  adds 0.5–1 s to every reply.
- [ ] **Use an always-on VM, not serverless.** Calls are long WebSockets: serverless times them out and bills
  for the whole call.
- [ ] **Never use `--reload` in production.**

## 2. Environment (`backend/.env`)

The server refuses to start in production if the first five are wrong:

- [ ] `ENVIRONMENT=production`
- [ ] `DATABASE_URL` = Supabase **PostgreSQL** (SQLite is refused)
- [ ] `JWT_SECRET_KEY` or `SUPABASE_JWT_SECRET`, at least 32 characters
- [ ] `SIMULATED_PAYMENTS=false`, `PHONE_NUMBER_MOCK_MODE=false`
- [ ] `CORS_ORIGINS` = your real frontend URL(s), no `*`
- [ ] `RUNTIME_MODE=real` with `SARVAM_API_KEY`, `CARTESIA_API_KEY` and `GEMINI_API_KEY` set
- [ ] **Both Sarvam and Cartesia keys must have credits.** If an agent's voice fails mid-call, the other vendor's
  voice takes over (`VOICE_TTS_FALLBACK_PROVIDERS=sarvam,cartesia`). Without a working second key, callers hear
  silence.
- [ ] `VOBIZ_WEBHOOK_SECRET` set, so fake webhooks are rejected
- [ ] Webhook / stream URLs at the carrier point at the production domain (HTTPS / WSS)
- [ ] Razorpay live keys and `RAZORPAY_WEBHOOK_SECRET`

## 3. Capacity limits (know your numbers)

| Setting | Default | Meaning |
|---|---|---|
| `MAX_CONCURRENT_CALLS_PLATFORM` | 5 | Calls at once, all clients together |
| `MAX_CONCURRENT_CALLS_PER_CLIENT` | 5 | Calls at once per client |
| `VOBIZ_MAX_CONCURRENT_CALLS` | 3 | Vobiz account-wide limit |
| DB pool | 5 + 5 overflow | Supabase session pooler allows 15 in total |
| `VOICE_LLM_THREADS` / `VOICE_TOOL_THREADS` | 32 / 16 | Thread pools for replies / tools |

- [ ] Raise call limits only after confirming the matching limits with Vobiz and in the Sarvam plan.
- [ ] Around 30–50 concurrent calls, one process starts to strain (all audio runs on one event loop). That is
  the point to plan for multiple servers plus Redis.

## 4. Data that must survive a redeploy

- [ ] **Recordings** are written to `backend/recordings/` (`RECORDINGS_DIR`) as WAV (~1 MB per minute).
  Put that folder on a persistent disk or volume, or they're lost on redeploy. Watch the disk space.
- [ ] MongoDB (knowledge base) reachable from the server. The knowledge APIs return 503 when it isn't.
- [ ] Database backups enabled in Supabase.

## 5. Business / compliance (before real customers)

- [ ] **DLT registration done** (TRAI). Required for business calls in India.
- [ ] Calls are enquiry callbacks, follow-ups and inbound only. Promotional calling needs the 140-series and
  separate rules.
- [ ] **Replace the made-up sample knowledge** (fees/batches note `knw_62ae2e8909f0` on the Ananya agent, for
  kundhanasai) with real data.
- [ ] Number renting is out of mock mode and Vobiz has credits.

## 6. Every deploy

1. Run the backend tests: `cd backend && python -m pytest -q tests`. All must pass.
2. Deploy, then send the stop signal to the old server and let it drain. Don't kill it.
3. Check `/health` says `healthy`.
4. Place one real test call: greeting plays, the agent answers, barge-in works, the recording saves.
5. Watch the logs for `Fallback TTS`, `Could not release the database connection` or `Drain time is up`.
   Any of these means something needs a look.

## Known limits (accepted for now)

- One server only (see section 1). Scaling out needs Redis for call counts.
- A Vobiz outage stops calls, and a speech-to-text outage leaves the agent unable to hear. The voice (TTS) has a
  cross-vendor fallback. Test what happens when the LLM provider fails before relying on it.
- If the carrier's network drops the WebSocket, that call ends. There is no reconnect.
