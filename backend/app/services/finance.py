"""
Finance analytics for staff: money collected, revenue earned, what it cost Choranta, and the profit, for a
period, over time and per client. Read-only; everything comes from records billing already keeps.

- Money in: invoices issued (credit recharges and plan payments), with the GST collected on them, plus
  recharges made while invoices are switched off
- Revenue: credits taken from wallets (calls, number rent and setup fees, WhatsApp messages) plus plan
  payments (their credits are used without a wallet debit)
- Cost: each billable call's real cost (same estimate billing charges from) and the carrier's rent for numbers
"""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing import ClientWallet, Invoice, WalletTransaction
from app.models.call import Call
from app.models.client import Client
from app.models.numbers import NumberAssignment, ProviderNumber
from app.models.runtime_session import RuntimeSession
from app.services.call_costing import estimate_call_cost

REVENUE_SOURCES = ("calls", "number_rent", "number_setup", "whatsapp", "plans", "other")
COST_COMPONENTS = ("telephony", "speech_to_text", "text_to_speech", "llm", "number_rent")
MONTHLY_BUCKETS_AFTER_DAYS = 92  # longer ranges are shown per month
DAYS_PER_MONTH = 30.0


def _naive(value: Optional[datetime]) -> Optional[datetime]:
    """UTC without tzinfo, so values read back from SQLite (naive) and Postgres (aware) compare alike."""
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _money(value: float) -> float:
    return round(value, 2)


def _revenue_source(txn: WalletTransaction) -> str:
    note = txn.note or ""
    if txn.call_id:
        return "calls"
    if note.startswith("Rent for"):
        return "number_rent"
    if note.startswith("Number setup fee"):
        return "number_setup"
    if (txn.reference or "").startswith("whatsapp:"):
        return "whatsapp"
    return "other"


def _overlap_days(start: datetime, end: datetime, lo: datetime, hi: datetime) -> float:
    seconds = (min(end, hi) - max(start, lo)).total_seconds()
    return max(0.0, seconds) / 86400.0


class _Totals:
    def __init__(self):
        self.money_in = 0.0
        self.revenue = defaultdict(float)
        self.cost = defaultdict(float)

    @property
    def revenue_total(self) -> float:
        return sum(self.revenue.values())

    @property
    def cost_total(self) -> float:
        return sum(self.cost.values())


def _margin(revenue: float, profit: float) -> Optional[float]:
    return round(profit / revenue * 100.0, 1) if revenue > 0 else None


def finance_summary(db: Session, start: datetime, end: datetime, client_id: Optional[str] = None) -> Dict[str, Any]:
    """Finance figures for [start, end) (UTC), optionally for one client."""
    start, end = _naive(start), _naive(end)
    monthly = (end - start).days > MONTHLY_BUCKETS_AFTER_DAYS

    def bucket(when: datetime) -> str:
        return when.strftime("%Y-%m") if monthly else when.strftime("%Y-%m-%d")

    total = _Totals()
    per_client: Dict[str, _Totals] = defaultdict(_Totals)
    per_bucket: Dict[str, _Totals] = defaultdict(_Totals)
    gst = taxable = 0.0
    calls_counted = 0
    call_minutes = 0.0

    # Money in: invoices issued in the period (GST-inclusive), and plan payments as revenue
    invoices = db.query(Invoice).filter(Invoice.issue_date >= start.date(), Invoice.issue_date < end.date() + timedelta(days=1))
    if client_id:
        invoices = invoices.filter(Invoice.client_id == client_id)
    for inv in invoices.all():
        when = datetime.combine(inv.issue_date, datetime.min.time())
        if when >= end:
            continue
        taxable += inv.taxable_inr
        gst += (inv.cgst_inr or 0) + (inv.sgst_inr or 0) + (inv.igst_inr or 0)
        for t in (total, per_client[inv.client_id], per_bucket[bucket(when)]):
            t.money_in += inv.total_inr
            if inv.description:  # a plan payment: no wallet credit, the plan's credits are spent without debits
                t.revenue["plans"] += inv.taxable_inr

    # Recharges made while invoices are off have no invoice: the wallet credit is the amount excluding GST
    gst_rate = settings.EFFECTIVE_GST_RATE_PERCENT / 100.0
    recharges = db.query(WalletTransaction).filter(
        WalletTransaction.type == "CREDIT", WalletTransaction.invoice_id.is_(None),
        WalletTransaction.created_at >= start, WalletTransaction.created_at < end)
    if client_id:
        recharges = recharges.filter(WalletTransaction.client_id == client_id)
    for txn in recharges.all():
        tax = txn.amount_inr * gst_rate
        taxable += txn.amount_inr
        gst += tax
        for t in (total, per_client[txn.client_id], per_bucket[bucket(_naive(txn.created_at))]):
            t.money_in += txn.amount_inr + tax

    # Revenue: credits taken from wallets
    debits = db.query(WalletTransaction).filter(
        WalletTransaction.type == "DEBIT", WalletTransaction.created_at >= start, WalletTransaction.created_at < end)
    if client_id:
        debits = debits.filter(WalletTransaction.client_id == client_id)
    for txn in debits.all():
        amount = -txn.amount_inr
        source = _revenue_source(txn)
        for t in (total, per_client[txn.client_id], per_bucket[bucket(_naive(txn.created_at))]):
            t.revenue[source] += amount
    adj = db.query(WalletTransaction).filter(
        WalletTransaction.type == "ADJUSTMENT", WalletTransaction.created_at >= start, WalletTransaction.created_at < end)
    if client_id:
        adj = adj.filter(WalletTransaction.client_id == client_id)
    adjustments = sum(t.amount_inr for t in adj.all())

    # Cost of calls: the same estimate billing charges from (test calls aren't billed, so aren't counted)
    calls = db.query(Call).filter(Call.status == "COMPLETED", Call.duration_seconds > 0,
                                  Call.created_at >= start, Call.created_at < end)
    if client_id:
        calls = calls.filter(Call.client_id == client_id)
    calls = [c for c in calls.all() if not (c.metadata_ or {}).get("is_test")]
    session_ids = [c.runtime_session_id for c in calls if c.runtime_session_id]
    sessions = {s.id: s for s in db.query(RuntimeSession).filter(RuntimeSession.id.in_(session_ids)).all()} if session_ids else {}
    for call in calls:
        session_obj = sessions.get(call.runtime_session_id)
        usage = session_obj.usage_json if session_obj and isinstance(session_obj.usage_json, dict) else {}
        breakdown = estimate_call_cost(call.duration_seconds, usage)["breakdown"]
        calls_counted += 1
        call_minutes += call.duration_seconds / 60.0
        for t in (total, per_client[call.client_id], per_bucket[bucket(_naive(call.created_at))]):
            for component, value in breakdown.items():
                t.cost[component] += value

    # Carrier cost of numbers: rent for the days held in the period, split to the clients the number was
    # assigned to at the time (days in Choranta's pool, and setup on purchase, count only towards the total)
    now = _naive(datetime.now(timezone.utc))
    until = min(end, now)
    numbers = db.query(ProviderNumber).filter(ProviderNumber.purchased_at.isnot(None), ProviderNumber.purchased_at < end).all()
    assignments = defaultdict(list)
    if numbers:
        for a in db.query(NumberAssignment).filter(NumberAssignment.provider_number_id.in_([n.id for n in numbers])).all():
            assignments[a.provider_number_id].append(a)
    mock_numbers = 0
    for number in numbers:
        held_from, held_to = _naive(number.purchased_at), _naive(number.released_at) or now
        days = _overlap_days(held_from, held_to, start, until)
        daily_rent = (number.monthly_cost or 0.0) / DAYS_PER_MONTH
        setup = (number.setup_cost or 0.0) if start <= held_from < end and not client_id else 0.0
        shares = defaultdict(float)  # client -> days assigned in the period
        for a in assignments.get(number.id, []):
            a_from = max(_naive(a.assigned_at), held_from)
            shares[a.client_id] += _overlap_days(a_from, _naive(a.released_at) or held_to, start, until)
        if client_id:
            shares = {client_id: shares.get(client_id, 0.0)}
            counted_days = shares[client_id]
        else:
            counted_days = days
        if not (daily_rent * counted_days or setup):
            continue
        if number.is_mock:
            mock_numbers += 1
        for cid, c_days in shares.items():
            if c_days > 0:
                per_client[cid].cost["number_rent"] += daily_rent * c_days
        total.cost["number_rent"] += daily_rent * counted_days + setup
        if setup:
            per_bucket[bucket(held_from)].cost["number_rent"] += setup
        # Rent over the trend: spread evenly across the days counted
        if counted_days > 0 and days > 0:
            day, stop = max(held_from, start), min(held_to, until)
            while day < stop:
                nxt = min(datetime.combine(day.date() + timedelta(days=1), datetime.min.time()), stop)
                per_bucket[bucket(day)].cost["number_rent"] += daily_rent * counted_days * (nxt - day).total_seconds() / 86400.0 / days
                day = nxt

    revenue, cost = total.revenue_total, total.cost_total

    clients = {c.id: c for c in db.query(Client).filter(Client.id.in_(list(per_client))).all()} if per_client else {}
    wallets = {w.client_id: w for w in db.query(ClientWallet).filter(ClientWallet.client_id.in_(list(per_client))).all()} if per_client else {}
    client_rows = []
    for cid, t in per_client.items():
        if client_id and cid != client_id:
            continue
        wallet = wallets.get(cid)
        c_rev, c_cost = t.revenue_total, t.cost_total
        client_rows.append({
            "client_id": cid,
            "name": clients[cid].name if cid in clients else cid,
            "money_in": _money(t.money_in),
            "revenue": _money(c_rev),
            "cost": _money(c_cost),
            "profit": _money(c_rev - c_cost),
            "margin_pct": _margin(c_rev, c_rev - c_cost),
            "wallet_balance": _money(wallet.balance_inr) if wallet else 0.0,
            "low_balance": bool(wallet and wallet.balance_inr < wallet.low_balance_threshold_inr),
        })
    client_rows.sort(key=lambda r: (-r["revenue"], r["name"]))

    # Every bucket in the range, so the chart has no gaps
    trend = []
    cursor = start
    keys = []
    while cursor < end:
        key = bucket(cursor)
        if key not in keys:
            keys.append(key)
        cursor += timedelta(days=1)
    for key in keys:
        t = per_bucket.get(key) or _Totals()
        b_rev, b_cost = t.revenue_total, t.cost_total
        trend.append({"bucket": key, "money_in": _money(t.money_in), "revenue": _money(b_rev),
                      "cost": _money(b_cost), "profit": _money(b_rev - b_cost)})

    return {
        "currency": "INR",
        "start": start.isoformat(),
        "end": end.isoformat(),
        "granularity": "month" if monthly else "day",
        "money_in": {"total": _money(total.money_in), "taxable": _money(taxable), "gst": _money(gst),
                     "adjustments": _money(adjustments)},
        "revenue": {"total": _money(revenue), **{k: _money(total.revenue.get(k, 0.0)) for k in REVENUE_SOURCES}},
        "cost": {"total": _money(cost), **{k: _money(total.cost.get(k, 0.0)) for k in COST_COMPONENTS}},
        "profit": _money(revenue - cost),
        "margin_pct": _margin(revenue, revenue - cost),
        "calls": {"count": calls_counted, "minutes": round(call_minutes, 1)},
        "mock_numbers": mock_numbers,
        "trend": trend,
        "clients": client_rows,
    }


def period_range(period: str, start: Optional[date] = None, end: Optional[date] = None,
                 today: Optional[date] = None) -> tuple:
    """[start, end) datetimes (UTC) for a named period: 7d, 30d, 90d, month, or custom (inclusive dates)."""
    today = today or datetime.now(timezone.utc).date()
    tomorrow = datetime.combine(today + timedelta(days=1), datetime.min.time())
    if period == "custom":
        if not start or not end or end < start:
            raise ValueError("A custom period needs a start and an end date, with the end on or after the start.")
        return datetime.combine(start, datetime.min.time()), datetime.combine(end + timedelta(days=1), datetime.min.time())
    if period == "month":
        return datetime.combine(today.replace(day=1), datetime.min.time()), tomorrow
    days = {"7d": 7, "30d": 30, "90d": 90}.get(period)
    if not days:
        raise ValueError("Period must be 7d, 30d, 90d, month or custom.")
    return tomorrow - timedelta(days=days), tomorrow
