"""
Development-only demo of a client's website: a simple enquiry form whose server side forwards
each submission to Choranta's public leads API (POST /api/v1/public/leads) with the client's
API key, exactly as a real website's server would. Not mounted when ENVIRONMENT=production.
Set DEMO_LEADS_API_KEY in backend/.env to the client's key (portal → API & integrations).

Also plays the client's CRM: /demo/results-webhook receives the campaign's results webhooks
(verifying the signature) and /demo/results shows them.
"""
import hmac
import html
import json
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Deque, Dict

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.campaign import Campaign, CampaignRecipient
from app.services import instant_leads
from app.services.campaigns import normalize_phone, sign_webhook

# In memory only: cleared when the backend restarts
RECEIVED: Deque[Dict[str, Any]] = deque(maxlen=50)

router = APIRouter(prefix="/demo", tags=["Demo"])


@router.get("/lead-form", response_class=HTMLResponse)
def lead_form():
    return HTMLResponse(PAGE)


@router.post("/lead-form/submit")
async def submit_demo_lead(request: Request):
    """The 'website server': forwards the form fields to the public leads API with the API key."""
    if not settings.DEMO_LEADS_API_KEY:
        return JSONResponse(status_code=500, content={"error": "Set DEMO_LEADS_API_KEY in backend/.env first."})
    form: Dict[str, Any] = await request.json()
    lead = {k: v for k, v in form.items() if v not in (None, "")}
    lead.setdefault("source", "demo_website")
    _allow_resubmit(str(lead.get("phone") or ""))
    url = str(request.base_url).rstrip("/") + f"{settings.API_V1_PREFIX}/public/leads"
    async with httpx.AsyncClient(timeout=15) as client:
        res = await client.post(url, json=lead, headers={"X-API-Key": settings.DEMO_LEADS_API_KEY})
    return JSONResponse(status_code=res.status_code, content=res.json())


def _allow_resubmit(raw_phone: str) -> None:
    """Demo only: lets a number whose earlier call has finished be submitted again straight away,
    by moving that submission outside the leads API's 24-hour duplicate window."""
    phone = normalize_phone(raw_phone)
    if not phone:
        return
    with SessionLocal() as db:
        try:
            ctx = instant_leads.authenticate(db, settings.DEMO_LEADS_API_KEY)
        except instant_leads.LeadError:
            return
        finished = db.query(CampaignRecipient).filter(
            CampaignRecipient.client_id == ctx.client_id, CampaignRecipient.phone == phone,
            CampaignRecipient.status.notin_(("PENDING", "DIALING", "RETRY_WAIT")),
        ).all()
        for recipient in finished:
            recipient.created_at = recipient.created_at - instant_leads.DUPLICATE_WINDOW - timedelta(minutes=1)
        db.commit()


@router.post("/results-webhook")
async def receive_results(request: Request):
    """The 'CRM': accepts a results webhook and checks its X-Choranta-Signature."""
    body = await request.body()
    try:
        payload = json.loads(body)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Expected JSON."})
    signature = request.headers.get("X-Choranta-Signature", "")
    timestamp = request.headers.get("X-Choranta-Timestamp", "")
    with SessionLocal() as db:
        campaign = db.get(Campaign, ((payload.get("campaign") or {}).get("id")) or "")
        secret = campaign.webhook_secret if campaign else None
    verified = bool(secret) and hmac.compare_digest(signature, f"sha256={sign_webhook(secret, timestamp, body)}")
    RECEIVED.appendleft({"received_at": datetime.now(timezone.utc), "verified": verified, "payload": payload})
    return {"ok": True, "signature_valid": verified}


@router.get("/results", response_class=HTMLResponse)
def results_page():
    def row(item: Dict[str, Any]) -> str:
        p = item["payload"]
        r, call = p.get("recipient") or {}, p.get("call") or {}
        badge = '<span class="ok">signature ✓</span>' if item["verified"] else '<span class="bad">signature ✗</span>'
        rec = f' · <a href="{html.escape(call["recording_url"])}" target="_blank">recording</a>' if call.get("recording_url") else ""
        return f"""<div class="card">
  <div class="top"><b>{html.escape(str(r.get("name") or "—"))}</b> {html.escape(str(r.get("phone") or ""))} {badge}</div>
  <div class="meta">{html.escape(str((p.get("campaign") or {}).get("name") or ""))} · {html.escape(str(r.get("status")))} / {html.escape(str(r.get("outcome")))}
    · {call.get("duration_seconds", 0)}s{rec} · received {item["received_at"].strftime("%H:%M:%S")} UTC</div>
  <p>{html.escape(str(p.get("summary") or "No summary."))}</p>
  <details><summary>Full payload</summary><pre>{html.escape(json.dumps(p, indent=2, default=str))}</pre></details>
</div>"""
    cards = "".join(row(i) for i in RECEIVED) or '<p class="empty">Nothing received yet. Results arrive after each lead’s call ends.</p>'
    return HTMLResponse(RESULTS_PAGE.replace("{{CARDS}}", cards))


RESULTS_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>Demo CRM Results</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; padding: 24px 16px; background: #040d12; color: #e2e8f0; font: 14px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; }
  main { max-width: 760px; margin: 0 auto; }
  h1 { font-size: 22px; margin: 0 0 4px; }
  .sub, .meta, .empty { color: #94a3b8; font-size: 13px; }
  .card { background: #091b22; border: 1px solid #153945; border-radius: 12px; padding: 16px; margin-top: 14px; }
  .top { font-size: 15px; }
  .ok { color: #00df8f; font-size: 12px; margin-left: 6px; }
  .bad { color: #fb7185; font-size: 12px; margin-left: 6px; }
  a { color: #00df8f; }
  pre { overflow-x: auto; background: #06141a; padding: 10px; border-radius: 8px; font-size: 12px; }
  summary { cursor: pointer; color: #94a3b8; font-size: 12px; }
</style>
</head>
<body><main>
  <h1>Demo CRM: call results</h1>
  <p class="sub">Results webhooks Choranta sent to /demo/results-webhook. Refreshes every 10 seconds.</p>
  {{CARDS}}
</main></body>
</html>
"""


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Demo Enquiry Form</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 16px;
         background: #040d12; color: #e2e8f0; font: 15px/1.5 system-ui, -apple-system, Segoe UI, sans-serif; }
  .card { width: 100%; max-width: 440px; background: #091b22; border: 1px solid #153945; border-radius: 14px; padding: 28px; }
  h1 { margin: 0 0 4px; font-size: 22px; }
  p.sub { margin: 0 0 22px; color: #94a3b8; font-size: 13px; }
  label { display: block; margin: 14px 0 6px; font-size: 12px; font-weight: 600; color: #cbd5e1; }
  input[type=text], input[type=tel], select { width: 100%; padding: 10px 12px; border-radius: 8px; font: inherit;
         background: #06141a; color: #f1f5f9; border: 1px solid #153945; }
  input:focus, select:focus { outline: none; border-color: #00df8f; box-shadow: 0 0 0 1px #00df8f; }
  .check { display: flex; gap: 8px; align-items: flex-start; margin: 18px 0 4px; font-size: 13px; color: #cbd5e1; font-weight: 400; }
  .check input { margin-top: 3px; accent-color: #00df8f; }
  button { width: 100%; margin-top: 20px; padding: 12px; border: 0; border-radius: 8px; cursor: pointer;
           background: #00df8f; color: #03251a; font: 600 15px system-ui, sans-serif; }
  button:disabled { opacity: .6; cursor: wait; }
  .msg { margin-top: 16px; padding: 12px; border-radius: 8px; font-size: 13px; display: none; }
  .ok { display: block; background: rgba(0,223,143,.1); border: 1px solid rgba(0,223,143,.4); color: #6ee7b7; }
  .err { display: block; background: rgba(244,63,94,.1); border: 1px solid rgba(244,63,94,.4); color: #fda4af; }
</style>
</head>
<body>
<form class="card" id="f">
  <h1>Request a callback</h1>
  <p class="sub">Demo website. This page's server sends your enquiry to Choranta's leads API with the client's API key, and the AI Employee calls within seconds.</p>
  <label for="name">Name</label>
  <input id="name" type="text" placeholder="Your name" required>
  <label for="phone">Phone number</label>
  <input id="phone" type="tel" value="+918008538015" required>
  <label for="course">Course enquired</label>
  <select id="course">
    <option>Data Science</option>
    <option>Full Stack Development</option>
    <option>UI/UX Design</option>
    <option>Digital Marketing</option>
  </select>
  <label for="city">City</label>
  <input id="city" type="text" placeholder="e.g. Hyderabad">
  <label class="check"><input id="consent" type="checkbox" checked> I agree to receive a call about my enquiry.</label>
  <button id="btn" type="submit">Call me</button>
  <div class="msg" id="msg"></div>
</form>
<script>
  const f = document.getElementById('f'), msg = document.getElementById('msg'), btn = document.getElementById('btn');
  const show = (cls, text) => { msg.className = 'msg ' + cls; msg.textContent = text; };
  f.addEventListener('submit', async (e) => {
    e.preventDefault();
    btn.disabled = true; show('', '');
    try {
      const res = await fetch('lead-form/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: document.getElementById('name').value.trim(),
          phone: document.getElementById('phone').value.trim(),
          course_enquired: document.getElementById('course').value,
          city: document.getElementById('city').value.trim(),
          consent: document.getElementById('consent').checked,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) return show('err', data.error || data.detail?.[0]?.msg || 'Something went wrong.');
      if (data.calling === 'now') show('ok', 'Thanks! You will get a call in a few seconds.');
      else if (data.calling === 'queued') show('ok', 'Received. It is outside calling hours (or the outbound is paused), so you will be called when the window opens.');
      else show('err', 'This number was already submitted in the last 24 hours, so it will not be called again yet.');
    } catch (err) {
      show('err', 'Could not reach the server.');
    } finally {
      btn.disabled = false;
    }
  });
</script>
</body>
</html>
"""
