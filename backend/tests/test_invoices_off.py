"""With invoices switched off, payments still add credits and everything that used to rely on an invoice keeps working."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing import Invoice, WalletTransaction
from app.services import agent_requests, billing
from app.services.finance import finance_summary, period_range
from test_billing import company  # noqa: F401
from test_phase3c_telephony import telephony_setup  # noqa: F401


@pytest.fixture
def invoices_off(monkeypatch):
    monkeypatch.setattr(settings, "INVOICES_ENABLED", False, raising=False)


def test_payment_adds_credits_without_an_invoice(db: Session, telephony_setup, company, invoices_off):
    cid = telephony_setup["client"].id
    result = billing.record_payment(db, cid, 1180, "UTR1", None)
    assert result["invoice_id"] is None and result["invoice_number"] is None and result["balance_inr"] == 1000.0
    assert db.query(Invoice).filter(Invoice.client_id == cid).count() == 0
    txn = db.query(WalletTransaction).filter(WalletTransaction.client_id == cid).one()
    assert txn.type == "CREDIT" and txn.note == "Recharge" and txn.invoice_id is None


def test_zero_payment_is_still_refused(db: Session, telephony_setup, company, invoices_off):
    with pytest.raises(Exception):
        billing.record_payment(db, telephony_setup["client"].id, 0, None, None)


def test_a_payment_without_an_invoice_lets_the_client_request_an_employee(db: Session, telephony_setup, company, invoices_off):
    cid = telephony_setup["client"].id
    assert agent_requests.has_paid(db, cid) is False
    billing.record_payment(db, cid, 1180, None, None)
    assert agent_requests.has_paid(db, cid) is True


def test_finance_counts_payments_without_invoices(db: Session, telephony_setup, company, invoices_off):
    billing.record_payment(db, telephony_setup["client"].id, 1180, None, None)
    data = finance_summary(db, *period_range("7d"))
    assert data["money_in"] == {"total": 1180.0, "taxable": 1000.0, "gst": 180.0, "adjustments": 0.0}


def test_payments_with_invoices_are_not_counted_twice(db: Session, telephony_setup, company):
    billing.record_payment(db, telephony_setup["client"].id, 1180, None, None)
    assert finance_summary(db, *period_range("7d"))["money_in"]["total"] == 1180.0


def test_invoice_endpoints_are_hidden(client: TestClient, auth_headers: dict, db: Session, telephony_setup, company, monkeypatch):
    cid = telephony_setup["client"].id
    invoice_id = billing.record_payment(db, cid, 1180, None, None)["invoice_id"]  # issued while invoices were on
    assert client.get(f"/api/invoices/{invoice_id}/pdf", headers=auth_headers).status_code == 200

    monkeypatch.setattr(settings, "INVOICES_ENABLED", False, raising=False)
    assert client.get(f"/api/clients/{cid}/invoices", headers=auth_headers).json() == []
    assert client.get(f"/api/invoices/{invoice_id}/pdf", headers=auth_headers).status_code == 404
    assert client.get(f"/api/clients/{cid}/wallet", headers=auth_headers).json()["invoices_enabled"] is False
