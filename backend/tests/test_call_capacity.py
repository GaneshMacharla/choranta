"""Sharing the Vobiz lines, staying inside Sarvam's limits, calling back turned-away callers, and the capacity card."""
import asyncio
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_unique_id
from app.models.agent import Agent
from app.models.agent_version import AgentVersion
from app.models.call import Call
from app.models.call_capacity import CapacityDaily, MissedCallCallback
from app.models.campaign import CampaignRecipient, DoNotCallEntry
from app.models.client import Client
from app.models.phone_number import PhoneNumber
from app.runtime.providers.registry import default_registry
from app.runtime.providers.sarvam import limits
from app.runtime.providers.sarvam.llm import SarvamLLMProvider
from app.runtime.providers.telephony.base import CarrierLimitError
from app.runtime.providers.telephony.vobiz import VobizTelephonyProvider
from app.services import billing, call_capacity, call_outputs, capacity_stats, missed_call_callbacks, subscriptions
from app.services import campaigns as svc
from app.services.outbound_calls import OutboundCallError, place_outbound_call
from test_call_outputs import FakeLLM, TURNS, _call_with_transcript, _with_outputs
from test_campaigns import IN_WINDOW, _running
from test_phase3c_telephony import telephony_setup  # noqa: F401

CSV_FIVE = "phone\n" + "\n".join(f"987650010{i}" for i in range(5)) + "\n"
CALLER = "+919876500200"
# 21:30 IST on the same day: outside calling hours
AFTER_HOURS = IN_WINDOW + timedelta(hours=10, minutes=30)


class Dialer:
    """Stands in for place_outbound_call: creates a live call for whichever client is dialling."""

    def __init__(self):
        self.dialed = []
        self.error = None

    def __call__(self, db, *, destination_number, agent_id, agent_version_id, caller_id, client_id, extra_metadata=None, **_):
        if self.error:
            raise self.error
        call = Call(id=generate_unique_id("call"), client_id=client_id, agent_id=agent_id, agent_version_id=agent_version_id,
                    caller_number=caller_id, destination_number=destination_number, direction="OUTBOUND",
                    status="INITIATED", provider="exotel", provider_call_id=generate_unique_id("exo"),
                    metadata_=extra_metadata or {})
        db.add(call)
        db.commit()
        self.dialed.append((client_id, destination_number))
        return call


@pytest.fixture
def three_lines(monkeypatch):
    """Today's limits: 3 Vobiz lines, one kept for inbound, Sarvam pay-as-you-go."""
    for name, value in {"VOBIZ_MAX_CONCURRENT_CALLS": 3, "MAX_CONCURRENT_CALLS_PLATFORM": 3, "INBOUND_RESERVED_LINES": 1,
                        "SARVAM_LLM_REQUESTS_PER_MIN": 60, "SARVAM_STT_WS_LIMIT": 20, "SARVAM_TTS_WS_LIMIT": 60}.items():
        monkeypatch.setattr(settings, name, value)
    # Tick times are fixed in the past, but a live call's own age comes from the real clock: both must be in the window
    monkeypatch.setattr(svc, "in_calling_window", lambda campaign, now: True)


@pytest.fixture
def vobiz_inbound(db: Session, telephony_setup, client, monkeypatch):
    """Posts an inbound Vobiz call to the client's number."""
    monkeypatch.setitem(default_registry._telephony_providers, "vobiz",
                        VobizTelephonyProvider(auth_id="MA_TEST", auth_token="tok", webhook_secret="vobiz_secret"))
    monkeypatch.setattr(settings, "VOBIZ_WEBHOOK_SECRET", "vobiz_secret", raising=False)
    monkeypatch.setattr(settings, "TELEPHONY_BASE_URL", "https://choranta.example.com", raising=False)
    monkeypatch.setattr(missed_call_callbacks, "_in_calling_hours", lambda now: True)
    number = telephony_setup["phone_number"]
    number.provider = "vobiz"
    db.commit()

    def post(call_uuid: str = "uuid-in", caller: str = "919876500200"):
        return client.post("/api/telephony/vobiz/answer?token=vobiz_secret",
                           data={"CallUUID": call_uuid, "From": caller, "To": number.phone_number.lstrip("+")})
    return post


def _other_client(db: Session, setup) -> dict:
    """A second client with its own agent and number, for testing what's shared between clients."""
    other = Client(id=generate_unique_id("cli_"), name="Other Clinic", business_type="CLINIC")
    db.add(other)
    db.flush()
    agent = Agent(id=generate_unique_id("age_"), client_id=other.id, name="Other", role="Receptionist", status="PUBLISHED")
    db.add(agent)
    db.flush()
    version = AgentVersion(id=generate_unique_id("agv_"), agent_id=agent.id, version_number=1, status="PUBLISHED",
                           configuration_json=setup["version"].configuration_json)
    db.add(version)
    db.flush()
    number = PhoneNumber(id=generate_unique_id("phn_"), client_id=other.id, agent_id=agent.id, agent_version_id=version.id,
                         phone_number="+15550002222", provider="exotel", provider_number_id="EXO_OTHER", status="ACTIVE")
    db.add(number)
    db.commit()
    return {"client": other, "agent": agent, "version": version, "phone_number": number}


def _call(db: Session, setup, status: str = "ACTIVE", provider: str = "vobiz", age: timedelta = timedelta(0),
          metadata: dict = None, answered: bool = False) -> Call:
    created = subscriptions.utcnow() - age
    call = Call(id=generate_unique_id("call_"), client_id=setup["client"].id, agent_id=setup["agent"].id,
                agent_version_id=setup["version"].id, caller_number="+914045209348", destination_number="+918008538015",
                direction="OUTBOUND", status=status, provider=provider, provider_call_id=generate_unique_id("exo_"),
                created_at=created, answered_at=created if answered else None, metadata_=metadata or {})
    db.add(call)
    db.commit()
    return call


# ---------------------------------------------------------------- capacity


@pytest.mark.parametrize("llm,stt,tts,calls", [(60, 20, 60, 6), (200, 100, 200, 20), (300, 100, 1000, 30)])
def test_capacity_follows_the_sarvam_plan(monkeypatch, llm, stt, tts, calls):
    for name, value in {"SARVAM_LLM_REQUESTS_PER_MIN": llm, "SARVAM_STT_WS_LIMIT": stt, "SARVAM_TTS_WS_LIMIT": tts,
                        "MAX_CONCURRENT_CALLS_PLATFORM": 1000, "VOBIZ_MAX_CONCURRENT_CALLS": 0}.items():
        monkeypatch.setattr(settings, name, value)
    assert call_capacity.speech_capacity() == calls
    assert call_capacity.total_capacity() == calls


def test_the_lowest_limit_wins_and_one_line_is_kept_for_inbound(three_lines):
    assert call_capacity.line_capacity() == 3
    assert call_capacity.reserved_lines() == 1
    assert call_capacity.outbound_line_capacity() == 2


def test_a_single_line_is_not_reserved(three_lines, monkeypatch):
    monkeypatch.setattr(settings, "VOBIZ_MAX_CONCURRENT_CALLS", 1)
    assert call_capacity.reserved_lines() == 0
    assert call_capacity.free_for_outbound(call_capacity.free_for_inbound(0, 0)) == 1


def test_campaigns_leave_the_last_line_for_another_clients_inbound_call(
    db: Session, telephony_setup, three_lines, vobiz_inbound,
):
    other = _other_client(db, telephony_setup)
    campaign = _running(db, other, csv_text=CSV_FIVE, max_concurrent=3)
    dialer = Dialer()
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    assert len(dialer.dialed) == 2
    assert campaign.id

    # A further tick still leaves it free
    svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=5), dial=dialer)
    assert len(dialer.dialed) == 2
    assert billing.outbound_headroom(db) == 0 and billing.platform_headroom(db) == 1
    assert billing.check_call_allowed(db, other["client"].id)[2] == "CONCURRENCY"
    assert billing.check_call_allowed(db, telephony_setup["client"].id, inbound=True)[0]

    resp = vobiz_inbound()
    assert "/ws/telephony/vobiz/media" in resp.text


def test_bulk_lists_share_the_outbound_lines_between_clients(db: Session, telephony_setup, three_lines):
    other = _other_client(db, telephony_setup)
    _running(db, telephony_setup, csv_text=CSV_FIVE, max_concurrent=2)
    _running(db, other, csv_text="phone\n" + "\n".join(f"987650020{i}" for i in range(5)) + "\n", max_concurrent=2)
    dialer = Dialer()
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    assert sorted(client for client, _ in dialer.dialed) == sorted([telephony_setup["client"].id, other["client"].id])


def test_a_client_running_alone_gets_every_outbound_line(db: Session, telephony_setup, three_lines):
    _running(db, telephony_setup, csv_text=CSV_FIVE, max_concurrent=2)
    dialer = Dialer()
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    assert len(dialer.dialed) == 2


# ---------------------------------------------------------------- stuck calls


def test_a_stuck_unanswered_call_stops_holding_its_line_after_5_minutes(db: Session, telephony_setup):
    _call(db, telephony_setup, status="RINGING", age=timedelta(minutes=4))
    assert billing.platform_live_call_count(db) == 1
    _call(db, telephony_setup, status="INITIATED", age=timedelta(minutes=6))
    assert billing.platform_live_call_count(db) == 1
    assert billing.vobiz_live_call_count(db) == 1
    assert billing.live_call_count(db, telephony_setup["client"].id) == 1


def test_an_answered_call_holds_its_line_until_its_maximum_length_plus_5_minutes(db: Session, telephony_setup):
    _call(db, telephony_setup, age=timedelta(minutes=14), metadata={"max_duration_s": 600}, answered=True)
    assert billing.platform_live_call_count(db) == 1
    _call(db, telephony_setup, age=timedelta(minutes=16), metadata={"max_duration_s": 600}, answered=True)
    assert billing.platform_live_call_count(db) == 1
    # A long agent's call is still live at the same age
    _call(db, telephony_setup, age=timedelta(minutes=16), metadata={"max_duration_s": 3600}, answered=True)
    assert billing.platform_live_call_count(db) == 2


def test_older_calls_without_a_length_use_the_default(db: Session, telephony_setup, monkeypatch):
    monkeypatch.setattr(settings, "CALL_MAX_DURATION_S", 600)
    _call(db, telephony_setup, age=timedelta(minutes=16))
    assert billing.platform_live_call_count(db) == 0


def test_a_stuck_call_releases_its_held_credits_too(db: Session, telephony_setup):
    _call(db, telephony_setup, status="RINGING", age=timedelta(minutes=6), metadata={"credit_budget": 70})
    _call(db, telephony_setup, status="RINGING", metadata={"credit_budget": 40})
    assert billing.held_credits(db, telephony_setup["client"].id) == (1, 40.0)


def test_browser_test_calls_use_speech_capacity_but_no_phone_line(db: Session, telephony_setup, three_lines, monkeypatch):
    monkeypatch.setattr(settings, "MAX_CONCURRENT_CALLS_PLATFORM", 5)
    monkeypatch.setattr(settings, "VOBIZ_MAX_CONCURRENT_CALLS", 3)
    for _ in range(3):
        _call(db, telephony_setup, provider="browser")
    assert billing.browser_session_allowed(db)
    assert billing.platform_headroom(db) == 2  # all 3 Vobiz lines are free, but the speech capacity is shared
    _call(db, telephony_setup, provider="browser")
    assert not billing.browser_session_allowed(db)  # the last free call is left for a phone call
    assert billing.platform_headroom(db) == 1


# ---------------------------------------------------------------- Vobiz limits


class _FakeHttp:
    """Replaces httpx.Client for the Vobiz adapter: records the request, answers with `status`."""
    requests = []
    status = 201

    def __init__(self, **_):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, url, json=None, headers=None):
        _FakeHttp.requests.append(json)
        return httpx.Response(_FakeHttp.status, json={"request_uuid": "req-1"}, request=httpx.Request("POST", url))


@pytest.fixture
def fake_vobiz_http(monkeypatch):
    monkeypatch.setattr(httpx, "Client", _FakeHttp)
    _FakeHttp.requests, _FakeHttp.status = [], 201
    return _FakeHttp


def _dial_vobiz(**kwargs):
    return VobizTelephonyProvider(auth_id="MA_TEST", auth_token="tok").initiate_outbound_call(
        customer_number="+919876500100", caller_id="+918071234567", flow_url="https://x.example.com/answer", **kwargs)


def test_vobiz_dials_carry_a_ring_limit_and_a_time_limit(fake_vobiz_http):
    _dial_vobiz(max_duration_s=720, ring_timeout_s=25)
    assert fake_vobiz_http.requests[0]["time_limit"] == 720
    assert fake_vobiz_http.requests[0]["hangup_on_ring"] == 25


def test_a_ring_limit_of_zero_is_left_to_vobiz(fake_vobiz_http):
    _dial_vobiz(max_duration_s=720, ring_timeout_s=0)
    assert "hangup_on_ring" not in fake_vobiz_http.requests[0]


def test_vobiz_429_is_a_limit_error(fake_vobiz_http):
    fake_vobiz_http.status = 429
    with pytest.raises(CarrierLimitError):
        _dial_vobiz()


@pytest.fixture
def real_vobiz_dial(db: Session, telephony_setup, monkeypatch, fake_vobiz_http):
    """The real place_outbound_call and Vobiz adapter, with only the HTTP request to Vobiz faked."""
    monkeypatch.setitem(default_registry._telephony_providers, "vobiz",
                        VobizTelephonyProvider(auth_id="MA_TEST", auth_token="tok", webhook_secret="vobiz_secret"))
    for name, value in {"VOBIZ_AUTH_ID": "MA_TEST", "VOBIZ_AUTH_TOKEN": "tok", "VOBIZ_WEBHOOK_SECRET": "vobiz_secret",
                        "TELEPHONY_BASE_URL": "https://choranta.example.com", "VOBIZ_CPS": 0,
                        "VOBIZ_SUBACCOUNTS_ENABLED": False, "MAX_CONCURRENT_CALLS_PLATFORM": 5}.items():
        monkeypatch.setattr(settings, name, value, raising=False)
    monkeypatch.setattr(svc, "in_calling_window", lambda campaign, now: True)
    telephony_setup["phone_number"].provider = "vobiz"
    db.commit()
    return fake_vobiz_http


def test_a_placed_call_tells_vobiz_the_agents_limit_plus_the_margin(db: Session, telephony_setup, real_vobiz_dial):
    call = place_outbound_call(db, destination_number="+919876500100", phone_number_id=telephony_setup["phone_number"].id)
    max_duration = billing.agent_max_call_seconds(db, telephony_setup["version"].id)
    assert call.metadata_["max_duration_s"] == max_duration
    assert real_vobiz_dial.requests[0]["time_limit"] == max_duration + settings.VOBIZ_TIME_LIMIT_MARGIN_S
    assert real_vobiz_dial.requests[0]["hangup_on_ring"] == settings.VOBIZ_RING_TIMEOUT_S


def test_a_vobiz_limit_rejection_keeps_the_customers_attempt_and_pauses_outbound(db: Session, telephony_setup, real_vobiz_dial):
    _running(db, telephony_setup, csv_text="phone\n9876500100\n", retry_max=0)
    real_vobiz_dial.status = 429
    svc.run_campaign_tick(db, IN_WINDOW)

    recipient = db.query(CampaignRecipient).one()
    assert (recipient.status, recipient.attempts) == ("PENDING", 0)  # back in the queue, nothing used up
    assert db.query(Call).filter(Call.termination_reason == "carrier_limit").count() == 1
    assert call_capacity.outbound_pause_left() > 0
    assert billing.outbound_headroom(db) == 0 and billing.platform_headroom(db) > 0

    # No further dials during the pause
    requests = len(real_vobiz_dial.requests)
    svc.run_campaign_tick(db, IN_WINDOW + timedelta(seconds=5))
    assert len(real_vobiz_dial.requests) == requests


# ---------------------------------------------------------------- missed-call callbacks


def test_a_busy_inbound_call_queues_one_callback(db: Session, telephony_setup, three_lines, vobiz_inbound):
    for _ in range(3):
        _call(db, telephony_setup)
    resp = vobiz_inbound("uuid-1")
    assert "We will call you back shortly" in resp.text
    assert db.query(Call).filter(Call.provider_call_id == "uuid-1").count() == 0

    resp = vobiz_inbound("uuid-2")  # rings again while waiting: same promise, no second callback
    assert "We will call you back shortly" in resp.text
    callback = db.query(MissedCallCallback).one()
    assert (callback.client_id, callback.caller_number, callback.status) == (telephony_setup["client"].id, CALLER, "QUEUED")


def test_a_low_balance_refusal_queues_no_callback(db: Session, telephony_setup, three_lines, vobiz_inbound, monkeypatch):
    monkeypatch.setattr(settings, "BILLING_ENFORCED", True, raising=False)
    monkeypatch.setattr(settings, "PAYG_ONLY", True, raising=False)
    resp = vobiz_inbound("uuid-1")
    assert "Please call back later" in resp.text
    assert db.query(MissedCallCallback).count() == 0


def test_callbacks_can_be_switched_off(db: Session, telephony_setup, three_lines, vobiz_inbound, monkeypatch):
    monkeypatch.setattr(settings, "MISSED_CALL_CALLBACKS_ENABLED", False)
    for _ in range(3):
        _call(db, telephony_setup)
    assert "Please call back later" in vobiz_inbound("uuid-1").text
    assert db.query(MissedCallCallback).count() == 0


def test_no_callback_is_promised_outside_calling_hours(db: Session, telephony_setup):
    assert not missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=AFTER_HOURS)
    assert missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=IN_WINDOW)


def test_no_callback_for_anonymous_or_opted_out_callers(db: Session, telephony_setup):
    number = telephony_setup["phone_number"]
    assert not missed_call_callbacks.queue(db, number, "anonymous", now=IN_WINDOW)
    db.add(DoNotCallEntry(client_id=telephony_setup["client"].id, phone=CALLER))
    db.commit()
    assert not missed_call_callbacks.queue(db, number, CALLER, now=IN_WINDOW)


def test_no_second_callback_within_a_day_of_the_first_finishing(db: Session, telephony_setup):
    number = telephony_setup["phone_number"]
    assert missed_call_callbacks.queue(db, number, CALLER, now=IN_WINDOW)
    db.query(MissedCallCallback).one().status = "CONNECTED"
    db.commit()
    assert not missed_call_callbacks.queue(db, number, CALLER, now=IN_WINDOW + timedelta(hours=1))
    assert missed_call_callbacks.queue(db, number, CALLER, now=IN_WINDOW + timedelta(hours=25))


def test_callbacks_go_ahead_of_bulk_campaigns(db: Session, telephony_setup, three_lines):
    _running(db, telephony_setup, csv_text=CSV_FIVE, max_concurrent=2)
    missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=IN_WINDOW)
    dialer = Dialer()
    svc.run_campaign_tick(db, IN_WINDOW, dial=dialer)
    assert dialer.dialed[0][1] == CALLER
    assert len(dialer.dialed) == 2  # the rest of the outbound lines still go to the campaign


def _settle_call(db: Session, callback: MissedCallCallback, status: str, duration: float = 0.0) -> None:
    db.refresh(callback)
    call = db.get(Call, callback.last_call_id)
    call.status, call.duration_seconds, call.termination_reason = status, duration, "no-answer" if not duration else None
    db.commit()


def test_a_callback_stops_after_two_attempts(db: Session, telephony_setup, three_lines):
    missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=IN_WINDOW)
    callback = db.query(MissedCallCallback).one()
    dialer = Dialer()

    assert missed_call_callbacks.run_due(db, IN_WINDOW, dialer) == 1
    _settle_call(db, callback, "FAILED")

    # Waits out the retry delay
    assert missed_call_callbacks.run_due(db, IN_WINDOW + timedelta(minutes=1), dialer) == 0
    assert missed_call_callbacks.run_due(db, IN_WINDOW + timedelta(minutes=7), dialer) == 1
    _settle_call(db, callback, "FAILED")

    assert missed_call_callbacks.run_due(db, IN_WINDOW + timedelta(minutes=14), dialer) == 0
    db.refresh(callback)
    assert (callback.status, callback.attempts) == ("FAILED", 2)


def test_an_answered_callback_is_connected(db: Session, telephony_setup, three_lines):
    missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=IN_WINDOW)
    callback = db.query(MissedCallCallback).one()
    missed_call_callbacks.run_due(db, IN_WINDOW, Dialer())
    _settle_call(db, callback, "COMPLETED", duration=45)
    missed_call_callbacks.run_due(db, IN_WINDOW + timedelta(seconds=5), Dialer())
    db.refresh(callback)
    assert callback.status == "CONNECTED"


def test_a_callback_expires_after_30_minutes(db: Session, telephony_setup, three_lines):
    missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=IN_WINDOW)
    dialer = Dialer()
    assert missed_call_callbacks.run_due(db, IN_WINDOW + timedelta(minutes=31), dialer) == 0
    assert dialer.dialed == []
    assert db.query(MissedCallCallback).one().status == "EXPIRED"


def test_a_callback_waits_for_a_free_line_without_using_an_attempt(db: Session, telephony_setup, three_lines):
    for _ in range(2):
        _call(db, telephony_setup)
    missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=IN_WINDOW)
    dialer = Dialer()
    assert missed_call_callbacks.run_due(db, IN_WINDOW, dialer) == 0  # the last line is kept for inbound

    dialer.error = OutboundCallError("CONCURRENCY", "busy", 429)
    db.query(Call).delete()
    db.commit()
    assert missed_call_callbacks.run_due(db, IN_WINDOW, dialer) == 0
    callback = db.query(MissedCallCallback).one()
    assert (callback.status, callback.attempts) == ("QUEUED", 0)


def test_a_callback_respects_do_not_call_added_while_waiting(db: Session, telephony_setup, three_lines):
    missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=IN_WINDOW)
    db.add(DoNotCallEntry(client_id=telephony_setup["client"].id, phone=CALLER))
    db.commit()
    dialer = Dialer()
    missed_call_callbacks.run_due(db, IN_WINDOW, dialer)
    assert dialer.dialed == []
    assert db.query(MissedCallCallback).one().status == "SKIPPED"


def test_a_callback_is_dropped_when_the_client_has_no_balance(db: Session, telephony_setup, three_lines):
    missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=IN_WINDOW)
    dialer = Dialer()
    dialer.error = OutboundCallError("NO_BALANCE", "Add credits", 402)
    missed_call_callbacks.run_due(db, IN_WINDOW, dialer)
    assert db.query(MissedCallCallback).one().status == "SKIPPED"


def test_no_callback_is_placed_outside_calling_hours(db: Session, telephony_setup, three_lines):
    missed_call_callbacks.queue(db, telephony_setup["phone_number"], CALLER, now=IN_WINDOW)
    dialer = Dialer()
    db.query(MissedCallCallback).one().created_at = AFTER_HOURS
    db.commit()
    assert missed_call_callbacks.run_due(db, AFTER_HOURS, dialer) == 0
    assert dialer.dialed == []


# ---------------------------------------------------------------- Sarvam limits


class _FakeSarvam:
    def __init__(self, *statuses):
        self.statuses = list(statuses)
        self.sent = 0

    def build_request(self, method, url, json=None):
        return None

    def send(self, request, stream=False):
        self.sent += 1
        return httpx.Response(self.statuses.pop(0) if self.statuses else 200, content=b"")


def _provider(fake: _FakeSarvam) -> SarvamLLMProvider:
    provider = SarvamLLMProvider(api_key="test")
    provider._client = fake
    return provider


@pytest.fixture
def with_fallback(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_FALLBACK_TO_GEMINI", True, raising=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "key", raising=False)


def test_a_live_turn_over_the_limit_goes_to_the_fallback_quickly(monkeypatch, with_fallback):
    monkeypatch.setattr(settings, "SARVAM_LLM_REQUESTS_PER_MIN", 6)  # one request every 10 s
    fake = _FakeSarvam()
    provider = _provider(fake)
    provider._open_stream({})
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="request limit"):
        provider._open_stream({})
    assert time.monotonic() - started < 0.6
    assert fake.sent == 1  # the request that would be refused was never sent


def test_a_live_turn_with_no_fallback_is_sent_anyway(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_LLM_REQUESTS_PER_MIN", 6)
    monkeypatch.setattr(settings, "SARVAM_FALLBACK_TO_GEMINI", False, raising=False)
    fake = _FakeSarvam()
    provider = _provider(fake)
    provider._open_stream({})
    provider._open_stream({})
    assert fake.sent == 2


def test_a_live_turn_waits_briefly_for_a_token(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_LLM_REQUESTS_PER_MIN", 600)  # refills in 0.1 s
    while limits.acquire_llm_request() and limits._tokens and limits._tokens >= 1:
        pass
    assert limits.acquire_llm_request()


def test_background_work_leaves_part_of_the_allowance_for_live_calls(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_LLM_REQUESTS_PER_MIN", 60)  # 10 at once, a quarter kept back
    monkeypatch.setattr(settings, "SARVAM_LLM_BACKGROUND_WAIT_S", 0.0)
    taken = 0
    with limits.background_llm():
        while limits.acquire_llm_request():
            taken += 1
    assert taken == 7
    assert limits.acquire_llm_request()  # a live call still gets through


def test_background_work_waits_where_a_live_call_would_not(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_LLM_REQUESTS_PER_MIN", 600)
    monkeypatch.setattr(settings, "SARVAM_LLM_LIVE_RESERVE", 0.0)
    monkeypatch.setattr(settings, "SARVAM_LLM_BACKGROUND_WAIT_S", 2.0)
    with limits.background_llm():
        for _ in range(101):  # capacity is 100, so the last one has to wait for a refill
            assert limits.acquire_llm_request()


def test_post_call_extraction_runs_as_background_work(db: Session, telephony_setup):
    seen = []

    class Spy(FakeLLM):
        def generate(self, *args, **kwargs):
            seen.append(limits.is_background())
            return super().generate(*args, **kwargs)

    _with_outputs(db, telephony_setup)
    call = _call_with_transcript(db, telephony_setup, TURNS)
    call_outputs.mark_pending(db, call)
    call_outputs.run_extraction(db, call.id, llm=Spy('{"outputs": {}, "summary": ""}'))
    assert seen == [True]
    assert not limits.is_background()


def test_sarvam_429s_are_counted_and_three_pause_outbound(db: Session, telephony_setup, monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_RATE_LIMIT_RETRIES", 0)
    monkeypatch.setattr(settings, "SARVAM_LLM_REQUESTS_PER_MIN", 0)
    provider = _provider(_FakeSarvam(429, 503))
    for _ in range(2):
        with pytest.raises(RuntimeError, match="Sarvam API error"):
            provider._open_stream({})
    assert call_capacity.outbound_pause_left() == 0
    call_capacity.record_speech_rejection("sarvam_ws_rejected")
    assert call_capacity.outbound_pause_left() > 0

    assert billing.check_call_allowed(db, telephony_setup["client"].id)[2] == "CONCURRENCY"
    assert billing.check_call_allowed(db, telephony_setup["client"].id, inbound=True)[0]  # inbound carries on

    counters, _ = call_capacity.take_counters()
    assert (counters["sarvam_429"], counters["sarvam_503"], counters["sarvam_ws_rejected"]) == (1, 1, 1)


def test_old_rejections_dont_add_up_to_a_pause(monkeypatch):
    monkeypatch.setattr(settings, "SPEECH_BACKPRESSURE_WINDOW_S", 0.01)
    call_capacity.record_speech_rejection("sarvam_429")
    call_capacity.record_speech_rejection("sarvam_429")
    time.sleep(0.03)
    call_capacity.record_speech_rejection("sarvam_429")
    assert call_capacity.outbound_pause_left() == 0


def test_outbound_resumes_after_the_pause(monkeypatch):
    call_capacity.pause_outbound(0.01)
    assert call_capacity.free_for_outbound(2) == 0
    time.sleep(0.03)
    monkeypatch.setattr(settings, "INBOUND_RESERVED_LINES", 0)
    assert call_capacity.free_for_outbound(2) == 2


def test_new_sarvam_connections_are_spaced_out(monkeypatch):
    monkeypatch.setattr(settings, "SARVAM_WS_OPEN_SPACING_MS", 40)

    async def open_three():
        started = time.monotonic()
        await asyncio.gather(*(limits.wait_for_ws_open() for _ in range(3)))
        return time.monotonic() - started

    assert asyncio.run(open_three()) >= 0.07


@pytest.mark.parametrize("error,counted", [
    ("received 1003 (unsupported data); Rate limit exceeded", 1.0),
    ("Rate limit exceeded. Visit the API Dashboard", 1.0),
    ("connection reset by peer", None),
])
def test_only_rate_limit_closes_count_as_rejections(error, counted):
    limits.note_ws_failure(error)
    assert call_capacity.take_counters()[0].get("sarvam_ws_rejected") == counted


# ---------------------------------------------------------------- capacity card


def test_counters_are_saved_by_day(db: Session):
    call_capacity.count("inbound_refused_busy", 2)
    call_capacity.note_live_calls(2)
    capacity_stats.flush(db, IN_WINDOW)
    call_capacity.count("inbound_refused_busy")
    call_capacity.note_live_calls(1)
    capacity_stats.flush(db, IN_WINDOW)
    row = db.get(CapacityDaily, IN_WINDOW.date())
    assert (row.inbound_refused_busy, row.peak_live_calls) == (3, 2)


def test_counters_survive_a_failed_save():
    class BrokenDb:
        def get(self, *_):
            raise RuntimeError("database down")

        def rollback(self):
            pass

    call_capacity.count("sarvam_429", 2)
    call_capacity.note_live_calls(3)
    with pytest.raises(RuntimeError):
        capacity_stats.flush(BrokenDb())
    counters, peak = call_capacity.take_counters()
    assert (counters["sarvam_429"], peak) == (2, 3)


def test_live_call_minutes_add_up_between_samples(monkeypatch):
    clock = SimpleNamespace(now=1000.0)
    monkeypatch.setattr(call_capacity.time, "monotonic", lambda: clock.now)
    call_capacity.note_live_calls(2)
    clock.now += 60
    call_capacity.note_live_calls(2)
    assert call_capacity.take_counters()[0]["live_call_minutes"] == 2.0

    # The dispatcher wasn't running for a while: that gap isn't counted
    clock.now += 3600
    call_capacity.note_live_calls(2)
    assert "live_call_minutes" not in call_capacity.take_counters()[0]


def test_capacity_report_names_the_bottleneck_and_measures_requests(db: Session, three_lines):
    call_capacity.count("sarvam_llm_requests", 240)
    call_capacity.count("live_call_minutes", 30)
    report = capacity_stats.capacity_report(db)
    assert report["bottleneck"] == "vobiz"
    assert report["limits"]["usable_calls"] == 3 and report["limits"]["reserved_for_inbound"] == 1
    assert report["llm_requests_per_call_minute"] == {"assumed": settings.SARVAM_LLM_REQUESTS_PER_CALL, "measured": 8.0}


def test_too_few_minutes_arent_a_measurement(db: Session, three_lines):
    call_capacity.count("sarvam_llm_requests", 40)
    call_capacity.count("live_call_minutes", 5)
    assert capacity_stats.capacity_report(db)["llm_requests_per_call_minute"]["measured"] is None


def test_sarvam_becomes_the_bottleneck_once_lines_are_bought(db: Session, three_lines, monkeypatch):
    monkeypatch.setattr(settings, "VOBIZ_MAX_CONCURRENT_CALLS", 10)
    monkeypatch.setattr(settings, "MAX_CONCURRENT_CALLS_PLATFORM", 10)
    assert capacity_stats.capacity_report(db)["bottleneck"] == "sarvam"


def test_hints_follow_the_data(db: Session, three_lines):
    assert capacity_stats.capacity_report(db)["hints"] == []
    call_capacity.count("inbound_refused_busy", 14)
    call_capacity.count("sarvam_429", 2)
    call_capacity.count("campaign_wait_seconds", 7200)
    hints = " ".join(hint["text"] for hint in capacity_stats.capacity_report(db)["hints"])
    assert "14 inbound calls were refused" in hints
    assert "Sarvam's limits were hit 2 times" in hints
    assert "more lines would finish them faster" in hints


def test_spare_bought_lines_are_pointed_out_after_a_week(db: Session, three_lines, monkeypatch):
    monkeypatch.setattr(settings, "VOBIZ_MAX_CONCURRENT_CALLS", 5)
    today = capacity_stats._today()
    for back in range(7):
        db.add(CapacityDaily(day=today - timedelta(days=back), peak_live_calls=2))
    db.commit()
    hints = capacity_stats.capacity_report(db)["hints"]
    assert any("Peak was 2 of 5 lines" in hint["text"] for hint in hints)


def test_the_capacity_endpoint_is_admin_only(client, auth_headers):
    resp = client.get("/api/finance/capacity", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert "limits" in resp.json() and "hints" in resp.json()
    assert client.get("/api/finance/capacity").status_code in (401, 403)
