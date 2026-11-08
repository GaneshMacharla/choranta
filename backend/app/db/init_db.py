import logging
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import engine, Base, SessionLocal
from app.models import (
    User, Client, Agent, AgentVersion,
    AgentConfiguration, KnowledgeSource, Tool, Integration,
    Property, Lead
)
from app.models.tool import SWITCHED_OFF_TOOLS
from app.services.auth_service import AuthService

logger = logging.getLogger("choranta.init_db")


# Placeholder number rents (pre-GST, INR/month); admins change them on the Plans page
DEFAULT_NUMBER_RENTS = {"Landline": 499.0, "Mobile": 699.0, "TollFree": 1999.0}


def seed_number_pricing(db: Session) -> None:
    from app.models.subscription import NumberPricing
    for number_type, rent in DEFAULT_NUMBER_RENTS.items():
        if not db.get(NumberPricing, number_type):
            db.add(NumberPricing(number_type=number_type, monthly_rent_inr=rent, is_available=True))
    db.commit()


# Starter plans (pre-GST, INR); seeded only when no plans exist, admins change them on the Plans page.
# Bigger plans grant more bonus credits per rupee.
DEFAULT_PLANS = [
    {"name": "Starter", "description": "Credits for about 500 minutes of calls a month", "monthly_price_inr": 3000.0,
     "monthly_credits": 3500.0, "max_concurrent_calls": 2},
    {"name": "Growth", "description": "Credits for about 2,000 minutes a month for growing teams", "monthly_price_inr": 11500.0,
     "monthly_credits": 14000.0, "max_concurrent_calls": 5},
    {"name": "Pro", "description": "Credits for about 5,000 minutes a month for busy sales teams", "monthly_price_inr": 27500.0,
     "monthly_credits": 35000.0, "max_concurrent_calls": 10},
    {"name": "Business", "description": "Credits for about 15,000 minutes a month for high call volumes", "monthly_price_inr": 75000.0,
     "monthly_credits": 105000.0, "max_concurrent_calls": 25},
]


def seed_plans(db: Session) -> None:
    from app.models.subscription import Plan
    from app.services.subscriptions import apply_credit_fields
    if db.query(Plan).first():
        return
    for order, plan in enumerate(DEFAULT_PLANS):
        row = Plan(sort_order=order, is_active=True, **plan)
        apply_credit_fields(row, plan["monthly_credits"], settings.DEFAULT_CREDITS_PER_MINUTE)
        db.add(row)
    db.commit()


def retire_plans(db: Session) -> None:
    """
    Pay-as-you-go only: plans are no longer offered, and current subscriptions run to the end of their
    period without renewing (they end CANCELLED rather than PAST_DUE). Safe to run on every startup.
    """
    from app.models.subscription import ClientSubscription, Plan
    plans = db.query(Plan).filter(Plan.is_active.is_(True)).update({Plan.is_active: False}, synchronize_session=False)
    subs = (
        db.query(ClientSubscription)
        .filter(ClientSubscription.cancel_at_period_end.is_(False), ClientSubscription.status != "CANCELLED")
        .update({ClientSubscription.cancel_at_period_end: True}, synchronize_session=False)
    )
    db.commit()
    if plans or subs:
        logger.info(f"Pay-as-you-go: retired {plans} plan(s); {subs} subscription(s) end at period end")


# Seeded connectors with no implementation yet: hidden from the catalog until built
_RETIRED_INTEGRATIONS = ("int_google_calendar", "int_hubspot", "int_salesforce", "int_custom_webhook", "int_twilio_sms")


def seed_catalogs(db: Session) -> None:
    """Seed default system tools, integrations, and sample knowledge sources if empty."""
    seed_number_pricing(db)
    seed_plans(db)
    if settings.PAYG_ONLY:
        retire_plans(db)
    # 1. Tools
    # Switched off for now (see SWITCHED_OFF_TOOLS); kept commented until they're turned back on
    initial_tools = [
    #     {
    #         "id": "check_availability",
    #         "name": "Check Availability",
    #         "description": "Check appointment or schedule availability for a provider or service.",
    #         "input_schema": {"type": "object", "properties": {"date": {"type": "string"}, "service": {"type": "string"}}, "required": ["date"]},
    #         "output_schema": {"type": "object", "properties": {"available_slots": {"type": "array", "items": {"type": "string"}}}},
    #         "executor_type": "CALENDAR",
    #         "timeout": 15,
    #     },
    #     {
    #         "id": "book_appointment",
    #         "name": "Book Appointment",
    #         "description": "Book a confirmed appointment slot for a customer or patient.",
    #         "input_schema": {"type": "object", "properties": {"slot": {"type": "string"}, "customer_name": {"type": "string"}, "contact_phone": {"type": "string"}}, "required": ["slot", "customer_name"]},
    #         "output_schema": {"type": "object", "properties": {"confirmation_id": {"type": "string"}, "status": {"type": "string"}}},
    #         "executor_type": "SYSTEM",
    #         "timeout": 20,
    #     },
    #     {
    #         "id": "cancel_appointment",
    #         "name": "Cancel Appointment",
    #         "description": "Cancel an existing scheduled appointment with confirmation ID.",
    #         "input_schema": {"type": "object", "properties": {"confirmation_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["confirmation_id"]},
    #         "output_schema": {"type": "object", "properties": {"success": {"type": "boolean"}, "message": {"type": "string"}}},
    #         "executor_type": "SYSTEM",
    #         "timeout": 15,
    #     },
    #     {
    #         "id": "reschedule_appointment",
    #         "name": "Reschedule Appointment",
    #         "description": "Move an existing booking to an alternative available time slot.",
    #         "input_schema": {"type": "object", "properties": {"confirmation_id": {"type": "string"}, "new_slot": {"type": "string"}}, "required": ["confirmation_id", "new_slot"]},
    #         "output_schema": {"type": "object", "properties": {"updated_confirmation_id": {"type": "string"}, "status": {"type": "string"}}},
    #         "executor_type": "SYSTEM",
    #         "timeout": 20,
    #     },
    #     {
    #         "id": "create_lead",
    #         "name": "Create CRM Lead",
    #         "description": "Record caller inquiry, qualifications, and contact details into CRM.",
    #         "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"}, "notes": {"type": "string"}}, "required": ["name", "phone"]},
    #         "output_schema": {"type": "object", "properties": {"lead_id": {"type": "string"}, "status": {"type": "string"}}},
    #         "executor_type": "CRM",
    #         "timeout": 15,
    #     },
    #     {
    #         "id": "update_customer",
    #         "name": "Update Customer Record",
    #         "description": "Update address, preferences, or contact details for existing profile.",
    #         "input_schema": {"type": "object", "properties": {"customer_id": {"type": "string"}, "updates": {"type": "object"}}, "required": ["customer_id"]},
    #         "output_schema": {"type": "object", "properties": {"success": {"type": "boolean"}}},
    #         "executor_type": "CRM",
    #         "timeout": 15,
    #     },
    #     {
    #         "id": "transfer_call",
    #         "name": "Transfer Call",
    #         "description": "Escalate live session to an operational human department or supervisor.",
    #         "input_schema": {"type": "object", "properties": {"department": {"type": "string"}, "priority": {"type": "string"}, "reason": {"type": "string"}}, "required": ["department"]},
    #         "output_schema": {"type": "object", "properties": {"transfer_status": {"type": "string"}, "queue_id": {"type": "string"}}},
    #         "executor_type": "TELEPHONY",
    #         "timeout": 10,
    #     },
    #     {
    #         "id": "get_lead_details",
    #         "name": "Get Lead Details",
    #         "description": "Retrieve the lead's current record and known enquiry details from CRM.",
    #         "input_schema": {"type": "object", "properties": {"lead_id": {"type": "string"}}, "required": ["lead_id"]},
    #         "output_schema": {"type": "object", "properties": {"found": {"type": "boolean"}, "name": {"type": "string"}, "enquiry_location": {"type": "string"}, "enquiry_budget": {"type": "string"}, "enquiry_bhk": {"type": "string"}}},
    #         "executor_type": "CRM",
    #         "timeout": 15,
    #     },
    #     {
    #         "id": "search_properties",
    #         "name": "Search Properties",
    #         "description": "Find matching property inventory records using structured filters: location, budget, BHK, status.",
    #         "input_schema": {"type": "object", "properties": {"location": {"type": "string"}, "budget_min": {"type": "number"}, "budget_max": {"type": "number"}, "bhk": {"type": "integer"}, "status": {"type": "string"}}},
    #         "output_schema": {"type": "object", "properties": {"count": {"type": "integer"}, "properties": {"type": "array"}}},
    #         "executor_type": "SYSTEM",
    #         "timeout": 15,
    #     },
    #     {
    #         "id": "check_site_visit_slots",
    #         "name": "Check Site Visit Slots",
    #         "description": "Retrieve available calendar time slots for scheduling property site visits.",
    #         "input_schema": {"type": "object", "properties": {"property_id": {"type": "string"}, "preferred_date": {"type": "string"}}, "required": ["property_id"]},
    #         "output_schema": {"type": "object", "properties": {"property_id": {"type": "string"}, "available_slots": {"type": "array"}}},
    #         "executor_type": "CALENDAR",
    #         "timeout": 15,
    #     },
    #     {
    #         "id": "update_lead_record",
    #         "name": "Update Lead Record",
    #         "description": "Save collected buyer preferences, qualification status, and call outcome in CRM.",
    #         "input_schema": {"type": "object", "properties": {"lead_id": {"type": "string"}, "buyer_budget": {"type": "string"}, "buyer_location": {"type": "string"}, "buyer_bhk": {"type": "string"}, "purchase_timeline": {"type": "string"}, "lead_qualification_status": {"type": "string"}, "call_disposition": {"type": "string"}, "next_action": {"type": "string"}}, "required": ["lead_id"]},
    #         "output_schema": {"type": "object", "properties": {"success": {"type": "boolean"}, "status": {"type": "string"}, "lead_id": {"type": "string"}}},
    #         "executor_type": "CRM",
    #         "timeout": 15,
    #     },
    #     {
    #         "id": "book_site_visit",
    #         "name": "Book Site Visit",
    #         "description": "Confirm an in-person site visit booking with meeting point and executive assignment.",
    #         "input_schema": {"type": "object", "properties": {"property_id": {"type": "string"}, "slot": {"type": "string"}, "lead_id": {"type": "string"}}, "required": ["property_id", "slot"]},
    #         "output_schema": {"type": "object", "properties": {"booking_id": {"type": "string"}, "status": {"type": "string"}}},
    #         "executor_type": "CALENDAR",
    #         "timeout": 15,
    #     },
    #     {
    #         "id": "schedule_callback",
    #         "name": "Schedule Sales Callback",
    #         "description": "Schedule an executive callback for leads requesting specialized advisory.",
    #         "input_schema": {"type": "object", "properties": {"lead_id": {"type": "string"}, "preferred_time": {"type": "string"}}, "required": ["lead_id"]},
    #         "output_schema": {"type": "object", "properties": {"callback_id": {"type": "string"}, "status": {"type": "string"}}},
    #         "executor_type": "CRM",
    #         "timeout": 15,
    #     },
    ]

    for tool_data in initial_tools:
        if not db.query(Tool).filter(Tool.id == tool_data["id"]).first():
            db.add(Tool(**tool_data))
    # Mark the switched-off tools seeded before; kept (not deleted) so agents' links survive
    db.query(Tool).filter(Tool.id.in_(SWITCHED_OFF_TOOLS)).update({"enabled": False}, synchronize_session=False)

    # 2. Integrations
    # Only WhatsApp is live for now. The connectors below have no implementation yet; they stay commented
    # out (and are hidden from existing databases, see _RETIRED_INTEGRATIONS) until each one is built.
    initial_integrations = [
        {
            "id": "int_whatsapp",
            "name": "WhatsApp Business",
            "description": "Follow-up message to qualified leads after a call, from the client's own number (Meta Cloud API). Clients connect it in the portal.",
            "category": "MESSAGING",
            "provider": "META",
            "connection_status": "CONFIGURED",
        },
        # {
        #     "id": "int_google_calendar",
        #     "name": "Google Calendar",
        #     "description": "Real-time calendar availability and event scheduling.",
        #     "category": "CALENDAR",
        #     "provider": "GOOGLE",
        #     "connection_status": "CONFIGURED",
        # },
        # {
        #     "id": "int_hubspot",
        #     "name": "HubSpot CRM",
        #     "description": "Customer contact tracking, deals, and automated lead capture.",
        #     "category": "CRM",
        #     "provider": "HUBSPOT",
        #     "connection_status": "CONFIGURED",
        # },
        # {
        #     "id": "int_salesforce",
        #     "name": "Salesforce CRM",
        #     "description": "Enterprise customer management and service cases.",
        #     "category": "CRM",
        #     "provider": "SALESFORCE",
        #     "connection_status": "CONFIGURED",
        # },
        # {
        #     "id": "int_custom_webhook",
        #     "name": "Custom Webhook API",
        #     "description": "Dispatch call events and actions to proprietary client endpoints.",
        #     "category": "WEBHOOK",
        #     "provider": "CUSTOM",
        #     "connection_status": "CONFIGURED",
        # },
        # {
        #     "id": "int_twilio_sms",
        #     "name": "Twilio SMS",
        #     "description": "Post-call confirmation and SMS summary dispatch.",
        #     "category": "MESSAGING",
        #     "provider": "TWILIO",
        #     "connection_status": "CONFIGURED",
        # },
        # ]
    ]

    for int_data in initial_integrations:
        if not db.query(Integration).filter(Integration.id == int_data["id"]).first():
            db.add(Integration(**int_data))
    # Hide the not-yet-built connectors seeded before; kept (not deleted) so agents' links survive
    db.query(Integration).filter(Integration.id.in_(_RETIRED_INTEGRATIONS)).update(
        {"connection_status": "DISABLED"}, synchronize_session=False)

    db.commit()


# Columns added to tables that already exist; create_all only creates missing tables
_ADDED_COLUMNS = [
    ("invoices", "description", "TEXT"),
    ("campaigns", "kind", "VARCHAR(16) NOT NULL DEFAULT 'BULK'"),
    ("campaigns", "webhook_url", "TEXT"),
    ("campaigns", "webhook_secret", "VARCHAR(64)"),
    ("campaigns", "variables", "JSON"),
    ("campaign_recipients", "source", "VARCHAR(64)"),
    ("leads", "consent_given", "BOOLEAN"),
    ("leads", "consent_at", "TIMESTAMP"),
    ("leads", "consent_source", "VARCHAR(255)"),
    ("plans", "monthly_credits", "FLOAT"),
    ("client_subscriptions", "credits_used", "FLOAT NOT NULL DEFAULT 0"),
    ("call_usage", "plan_credits", "FLOAT NOT NULL DEFAULT 0"),
    ("call_usage", "wallet_credits", "FLOAT NOT NULL DEFAULT 0"),
    ("pricing_settings", "credits_per_minute", "FLOAT"),
    ("clients", "client_code", "VARCHAR(16)"),
    ("agent_requests", "details", "TEXT"),
    ("agent_requests", "company_name", "VARCHAR(255)"),
    ("agent_requests", "business_type", "VARCHAR(32)"),
    ("agent_requests", "trial_calls_used", "INTEGER NOT NULL DEFAULT 0"),
    ("knowledge_sources", "content", "TEXT"),
    ("number_pricing", "setup_fee_inr", "FLOAT NOT NULL DEFAULT 0"),
    ("knowledge_sources", "owner_agent_id", "VARCHAR(64) REFERENCES agents(id) ON DELETE CASCADE"),
    ("pricing_settings", "payg_max_concurrent_calls", "INTEGER"),
    ("clients", "max_concurrent_calls", "INTEGER"),
    ("knowledge_sources", "client_id", "VARCHAR(64) REFERENCES clients(id) ON DELETE CASCADE"),
    ("api_keys", "is_default", "BOOLEAN"),
    ("api_keys", "key_enc", "TEXT"),
    ("provider_numbers", "subaccount_auth_id", "VARCHAR(128)"),
    ("number_rentals", "reminders_sent", "JSON"),
    ("carrier_subaccounts", "business_type", "VARCHAR(32)"),
    ("carrier_subaccounts", "application_id", "VARCHAR(128)"),
]


def _add_missing_columns() -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    added = set()
    with engine.begin() as conn:
        for table, column, ddl_type in _ADDED_COLUMNS:
            if table in tables and column not in {c["name"] for c in inspector.get_columns(table)}:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))
                added.add((table, column))
                logger.info(f"Added column {table}.{column}")
        _migrate_to_credits(conn, added)
        if "clients" in tables:
            _assign_client_codes(conn)


def _assign_client_codes(conn) -> None:
    """Gives clients created before client codes existed one, in sign-up order."""
    from app.models.client import next_client_code
    rows = conn.execute(text("SELECT id FROM clients WHERE client_code IS NULL ORDER BY created_at, id")).fetchall()
    for (client_id,) in rows:
        conn.execute(text("UPDATE clients SET client_code = :code WHERE id = :id"),
                     {"code": next_client_code(conn), "id": client_id})
    if rows:
        logger.info(f"Assigned client codes to {len(rows)} client(s)")
    conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_clients_client_code ON clients (client_code)"))


def _migrate_to_credits(conn, added: set) -> None:
    """
    Moves minute-based plans to credits (1 credit = Rs 1). A plan grants the larger of its price and its old
    minutes at the default credit rate, so no subscriber gets fewer minutes than before. Plan minutes already
    used this period become used credits.
    """
    rate = settings.DEFAULT_CREDITS_PER_MINUTE
    result = conn.execute(text(
        "UPDATE plans SET monthly_credits = CASE WHEN included_minutes * :rate > monthly_price_inr "
        "THEN included_minutes * :rate ELSE monthly_price_inr END WHERE monthly_credits IS NULL"
    ), {"rate": rate})
    if result.rowcount:
        logger.info(f"Converted {result.rowcount} plan(s) to monthly credits")
    if ("client_subscriptions", "credits_used") in added:
        conn.execute(text("UPDATE client_subscriptions SET credits_used = minutes_used * :rate"), {"rate": rate})
    if ("call_usage", "wallet_credits") in added:
        conn.execute(text("UPDATE call_usage SET wallet_credits = overage_charge_inr, plan_credits = included_minutes * :rate"),
                     {"rate": rate})


def init_db() -> None:
    """Create tables if they do not exist and seed the initial internal administrator and catalogs."""
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()
    
    db: Session = SessionLocal()
    try:
        auth_service = AuthService(db)
        admin = auth_service.seed_initial_admin()
        if admin:
            logger.info("Internal platform admin initialized.")
        seed_catalogs(db)
        from app.services.call_scripts import seed_standard_scripts
        seed_standard_scripts(db)
        logger.info("Catalogs seeded.")
    except Exception as e:
        logger.error(f"Error during db initialization: {e}")
        db.rollback()
    finally:
        db.close()
    _move_client_knowledge_to_mongo()


def _move_client_knowledge_to_mongo() -> None:
    """Clients' knowledge written before MongoDB is moved there once MONGODB_URI is set."""
    from app.db import mongo
    if not mongo.configured():
        logger.warning("MONGODB_URI is not set: clients' knowledge bases (documents, notes, FAQs) are unavailable.")
        return
    db: Session = SessionLocal()
    try:
        from app.services.knowledge_store import migrate_sql_client_knowledge
        moved = migrate_sql_client_knowledge(db)
        if moved:
            logger.info("Moved %d client knowledge entries to MongoDB.", moved)
    except Exception as e:
        logger.error(f"Couldn't move client knowledge to MongoDB (will retry next start): {e}")
        db.rollback()
    finally:
        db.close()
