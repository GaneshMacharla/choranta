from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Date, Text, ForeignKey
from app.db.session import Base
from app.core.security import generate_unique_id


def _now():
    return datetime.now(timezone.utc)


class ClientUser(Base):
    """Links a CLIENT-role login to the client whose portal it can see."""
    __tablename__ = "client_users"

    user_id = Column(String(64), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=_now, nullable=False)


class ClientWallet(Base):
    """Prepaid balance (taxable value, INR) that calls are charged against."""
    __tablename__ = "client_wallets"

    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    balance_inr = Column(Float, nullable=False, default=0.0)
    low_balance_threshold_inr = Column(Float, nullable=False, default=500.0)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class WalletTransaction(Base):
    """Ledger entry: CREDIT (payment), DEBIT (call charge) or ADJUSTMENT (admin correction)."""
    __tablename__ = "wallet_transactions"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("wtx_"))
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    type = Column(String(16), nullable=False)
    amount_inr = Column(Float, nullable=False)  # signed: credits positive, debits negative
    balance_after_inr = Column(Float, nullable=False)
    call_id = Column(String(64), nullable=True, unique=True, index=True)  # one debit per call
    invoice_id = Column(String(64), nullable=True, index=True)
    reference = Column(String(255), nullable=True)
    note = Column(Text, nullable=True)
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False, index=True)


class ClientBillingProfile(Base):
    """Details printed on the client's GST invoices."""
    __tablename__ = "client_billing_profiles"

    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True)
    legal_name = Column(String(255), nullable=False)
    gstin = Column(String(15), nullable=True)
    address = Column(Text, nullable=True)
    state_code = Column(String(2), nullable=True)  # GST state code, e.g. "29" Karnataka, "36" Telangana
    billing_email = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)


class Invoice(Base):
    """GST tax invoice issued when a wallet recharge payment is recorded."""
    __tablename__ = "invoices"

    id = Column(String(64), primary_key=True, default=lambda: generate_unique_id("inv_"))
    number = Column(String(32), nullable=False, unique=True, index=True)
    client_id = Column(String(64), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    issue_date = Column(Date, nullable=False)
    financial_year = Column(String(7), nullable=False, index=True)  # e.g. 2026-27
    sequence = Column(Float, nullable=False)
    taxable_inr = Column(Float, nullable=False)
    cgst_inr = Column(Float, nullable=False, default=0.0)
    sgst_inr = Column(Float, nullable=False, default=0.0)
    igst_inr = Column(Float, nullable=False, default=0.0)
    total_inr = Column(Float, nullable=False)
    place_of_supply = Column(String(2), nullable=True)
    payment_reference = Column(String(255), nullable=True)
    transaction_id = Column(String(64), nullable=True)
    bill_to = Column(Text, nullable=True)  # JSON snapshot of the billing profile at issue time
    description = Column(Text, nullable=True)  # invoice line text; None = prepaid usage credit
    created_by = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
