import logging
from sqlalchemy.orm import Session
from app.db.session import engine, Base, SessionLocal
from app.models import (
    User, Client, Agent, AgentVersion,
    AgentConfiguration, KnowledgeSource, Tool, Integration,
    Property, Lead
)
from app.services.auth_service import AuthService

logger = logging.getLogger("choranta.init_db")


def seed_catalogs(db: Session) -> None:
    """Seed default system tools, integrations, and sample knowledge sources if empty."""
    # 1. Tools
    initial_tools = [
        {
            "id": "check_availability",
            "name": "Check Availability",
            "description": "Check appointment or schedule availability for a provider or service.",
            "input_schema": {"type": "object", "properties": {"date": {"type": "string"}, "service": {"type": "string"}}, "required": ["date"]},
            "output_schema": {"type": "object", "properties": {"available_slots": {"type": "array", "items": {"type": "string"}}}},
            "executor_type": "CALENDAR",
            "timeout": 15,
        },
        {
            "id": "book_appointment",
            "name": "Book Appointment",
            "description": "Book a confirmed appointment slot for a customer or patient.",
            "input_schema": {"type": "object", "properties": {"slot": {"type": "string"}, "customer_name": {"type": "string"}, "contact_phone": {"type": "string"}}, "required": ["slot", "customer_name"]},
            "output_schema": {"type": "object", "properties": {"confirmation_id": {"type": "string"}, "status": {"type": "string"}}},
            "executor_type": "SYSTEM",
            "timeout": 20,
        },
        {
            "id": "cancel_appointment",
            "name": "Cancel Appointment",
            "description": "Cancel an existing scheduled appointment with confirmation ID.",
            "input_schema": {"type": "object", "properties": {"confirmation_id": {"type": "string"}, "reason": {"type": "string"}}, "required": ["confirmation_id"]},
            "output_schema": {"type": "object", "properties": {"success": {"type": "boolean"}, "message": {"type": "string"}}},
            "executor_type": "SYSTEM",
            "timeout": 15,
        },
        {
            "id": "reschedule_appointment",
            "name": "Reschedule Appointment",
            "description": "Move an existing booking to an alternative available time slot.",
            "input_schema": {"type": "object", "properties": {"confirmation_id": {"type": "string"}, "new_slot": {"type": "string"}}, "required": ["confirmation_id", "new_slot"]},
            "output_schema": {"type": "object", "properties": {"updated_confirmation_id": {"type": "string"}, "status": {"type": "string"}}},
            "executor_type": "SYSTEM",
            "timeout": 20,
        },
        {
            "id": "create_lead",
            "name": "Create CRM Lead",
            "description": "Record caller inquiry, qualifications, and contact details into CRM.",
            "input_schema": {"type": "object", "properties": {"name": {"type": "string"}, "email": {"type": "string"}, "phone": {"type": "string"}, "notes": {"type": "string"}}, "required": ["name", "phone"]},
            "output_schema": {"type": "object", "properties": {"lead_id": {"type": "string"}, "status": {"type": "string"}}},
            "executor_type": "CRM",
            "timeout": 15,
        },
        {
            "id": "update_customer",
            "name": "Update Customer Record",
            "description": "Update address, preferences, or contact details for existing profile.",
            "input_schema": {"type": "object", "properties": {"customer_id": {"type": "string"}, "updates": {"type": "object"}}, "required": ["customer_id"]},
            "output_schema": {"type": "object", "properties": {"success": {"type": "boolean"}}},
            "executor_type": "CRM",
            "timeout": 15,
        },
        {
            "id": "transfer_call",
            "name": "Transfer Call",
            "description": "Escalate live session to an operational human department or supervisor.",
            "input_schema": {"type": "object", "properties": {"department": {"type": "string"}, "priority": {"type": "string"}, "reason": {"type": "string"}}, "required": ["department"]},
            "output_schema": {"type": "object", "properties": {"transfer_status": {"type": "string"}, "queue_id": {"type": "string"}}},
            "executor_type": "TELEPHONY",
            "timeout": 10,
        },
        {
            "id": "get_lead_details",
            "name": "Get Lead Details",
            "description": "Retrieve the lead's current record and known enquiry details from CRM.",
            "input_schema": {"type": "object", "properties": {"lead_id": {"type": "string"}}, "required": ["lead_id"]},
            "output_schema": {"type": "object", "properties": {"found": {"type": "boolean"}, "name": {"type": "string"}, "enquiry_location": {"type": "string"}, "enquiry_budget": {"type": "string"}, "enquiry_bhk": {"type": "string"}}},
            "executor_type": "CRM",
            "timeout": 15,
        },
        {
            "id": "search_properties",
            "name": "Search Properties",
            "description": "Find matching property inventory records using structured filters: location, budget, BHK, status.",
            "input_schema": {"type": "object", "properties": {"location": {"type": "string"}, "budget_min": {"type": "number"}, "budget_max": {"type": "number"}, "bhk": {"type": "integer"}, "status": {"type": "string"}}},
            "output_schema": {"type": "object", "properties": {"count": {"type": "integer"}, "properties": {"type": "array"}}},
            "executor_type": "SYSTEM",
            "timeout": 15,
        },
        {
            "id": "check_site_visit_slots",
            "name": "Check Site Visit Slots",
            "description": "Retrieve available calendar time slots for scheduling property site visits.",
            "input_schema": {"type": "object", "properties": {"property_id": {"type": "string"}, "preferred_date": {"type": "string"}}, "required": ["property_id"]},
            "output_schema": {"type": "object", "properties": {"property_id": {"type": "string"}, "available_slots": {"type": "array"}}},
            "executor_type": "CALENDAR",
            "timeout": 15,
        },
        {
            "id": "update_lead_record",
            "name": "Update Lead Record",
            "description": "Save collected buyer preferences, qualification status, and call outcome in CRM.",
            "input_schema": {"type": "object", "properties": {"lead_id": {"type": "string"}, "buyer_budget": {"type": "string"}, "buyer_location": {"type": "string"}, "buyer_bhk": {"type": "string"}, "purchase_timeline": {"type": "string"}, "lead_qualification_status": {"type": "string"}, "call_disposition": {"type": "string"}, "next_action": {"type": "string"}}, "required": ["lead_id"]},
            "output_schema": {"type": "object", "properties": {"success": {"type": "boolean"}, "status": {"type": "string"}, "lead_id": {"type": "string"}}},
            "executor_type": "CRM",
            "timeout": 15,
        },
        {
            "id": "book_site_visit",
            "name": "Book Site Visit",
            "description": "Confirm an in-person site visit booking with meeting point and executive assignment.",
            "input_schema": {"type": "object", "properties": {"property_id": {"type": "string"}, "slot": {"type": "string"}, "lead_id": {"type": "string"}}, "required": ["property_id", "slot"]},
            "output_schema": {"type": "object", "properties": {"booking_id": {"type": "string"}, "status": {"type": "string"}}},
            "executor_type": "CALENDAR",
            "timeout": 15,
        },
        {
            "id": "schedule_callback",
            "name": "Schedule Sales Callback",
            "description": "Schedule an executive callback for leads requesting specialized advisory.",
            "input_schema": {"type": "object", "properties": {"lead_id": {"type": "string"}, "preferred_time": {"type": "string"}}, "required": ["lead_id"]},
            "output_schema": {"type": "object", "properties": {"callback_id": {"type": "string"}, "status": {"type": "string"}}},
            "executor_type": "CRM",
            "timeout": 15,
        },
    ]

    for tool_data in initial_tools:
        if not db.query(Tool).filter(Tool.id == tool_data["id"]).first():
            db.add(Tool(**tool_data))

    # 2. Integrations
    initial_integrations = [
        {
            "id": "int_google_calendar",
            "name": "Google Calendar",
            "description": "Real-time calendar availability and event scheduling.",
            "category": "CALENDAR",
            "provider": "GOOGLE",
            "connection_status": "CONFIGURED",
        },
        {
            "id": "int_hubspot",
            "name": "HubSpot CRM",
            "description": "Customer contact tracking, deals, and automated lead capture.",
            "category": "CRM",
            "provider": "HUBSPOT",
            "connection_status": "CONFIGURED",
        },
        {
            "id": "int_salesforce",
            "name": "Salesforce CRM",
            "description": "Enterprise customer management and service cases.",
            "category": "CRM",
            "provider": "SALESFORCE",
            "connection_status": "CONFIGURED",
        },
        {
            "id": "int_custom_webhook",
            "name": "Custom Webhook API",
            "description": "Dispatch call events and actions to proprietary client endpoints.",
            "category": "WEBHOOK",
            "provider": "CUSTOM",
            "connection_status": "CONFIGURED",
        },
        {
            "id": "int_twilio_sms",
            "name": "Twilio SMS",
            "description": "Post-call confirmation and SMS summary dispatch.",
            "category": "MESSAGING",
            "provider": "TWILIO",
            "connection_status": "CONFIGURED",
        },
    ]

    for int_data in initial_integrations:
        if not db.query(Integration).filter(Integration.id == int_data["id"]).first():
            db.add(Integration(**int_data))

    # 3. Knowledge Sources
    initial_knowledge = [
        {
            "id": "knw_hospital_services",
            "name": "Hospital Services & Departments Directory.pdf",
            "type": "PDF",
            "description": "Clinical department listings, locations, and appointment guidelines.",
            "status": "READY",
            "metadata": {"pages": 14, "file_size_kb": 1240},
        },
        {
            "id": "knw_doctor_schedules",
            "name": "Doctor Specialties and Roster.pdf",
            "type": "PDF",
            "description": "Physician shifts, consultation timings, and qualifications.",
            "status": "READY",
            "metadata": {"pages": 8, "file_size_kb": 890},
        },
        {
            "id": "knw_patient_faq",
            "name": "General Patient & Booking FAQ.txt",
            "type": "FAQ",
            "description": "Frequently asked questions covering billing, parking, and insurance.",
            "status": "READY",
            "metadata": {"entries": 32},
        },
        {
            "id": "knw_property_catalog",
            "name": "Approved Property Inventory & FAQ Guide.pdf",
            "type": "PDF",
            "description": "Floor plans, approved project brochures, pricing slabs, amenities, and RERA approvals.",
            "status": "READY",
            "metadata": {"pages": 24, "file_size_kb": 3200},
        },
    ]

    for knw_data in initial_knowledge:
        if not db.query(KnowledgeSource).filter(KnowledgeSource.id == knw_data["id"]).first():
            db.add(KnowledgeSource(
                id=knw_data["id"],
                name=knw_data["name"],
                type=knw_data["type"],
                description=knw_data["description"],
                status=knw_data["status"],
                meta=knw_data.get("metadata", {})
            ))

    db.commit()


def seed_real_estate_data(db: Session) -> None:
    """Seed sample properties and leads for client tenants."""
    clients = db.query(Client).all()
    if not clients:
        return

    for client in clients:
        sample_properties = [
            {
                "id": f"prop_re_{client.id[-6:]}_01",
                "client_id": client.id,
                "project_name": "Prestige Highline Residences",
                "location": "Whitefield",
                "price": 9500000,
                "price_display": "₹95 Lakhs",
                "bhk": 3,
                "property_type": "Apartment",
                "status": "AVAILABLE",
                "amenities": ["Gym", "Covered Parking", "Clubhouse", "Children Play Area"],
                "meta": {"rera": "PRM/KA/RERA/1251/446/PR/171015/000451", "possession": "Dec 2026"},
            },
            {
                "id": f"prop_re_{client.id[-6:]}_02",
                "client_id": client.id,
                "project_name": "Prestige Palm Meadows Villa",
                "location": "Whitefield",
                "price": 24000000,
                "price_display": "₹2.4 Cr",
                "bhk": 4,
                "property_type": "Villa",
                "status": "AVAILABLE",
                "amenities": ["Private Garden", "Clubhouse", "24/7 Security", "Swimming Pool"],
                "meta": {"rera": "PRM/KA/RERA/1251/446/PR/180222/001899", "possession": "Ready to Move"},
            },
            {
                "id": f"prop_re_{client.id[-6:]}_03",
                "client_id": client.id,
                "project_name": "Sobha Dream Acres",
                "location": "Panathur",
                "price": 7500000,
                "price_display": "₹75 Lakhs",
                "bhk": 2,
                "property_type": "Apartment",
                "status": "AVAILABLE",
                "amenities": ["Swimming Pool", "Jogging Track", "Badminton Court"],
                "meta": {"rera": "PRM/KA/RERA/1251/446/PR/190510/002560", "possession": "Ready to Move"},
            },
            {
                "id": f"prop_re_{client.id[-6:]}_04",
                "client_id": client.id,
                "project_name": "Brigade Cornerstone Utopia",
                "location": "Varthur",
                "price": 11500000,
                "price_display": "₹1.15 Cr",
                "bhk": 3,
                "property_type": "Apartment",
                "status": "AVAILABLE",
                "amenities": ["Clubhouse", "Tennis Court", "Multiplex", "Supermarket"],
                "meta": {"rera": "PRM/KA/RERA/1251/446/PR/200115/003180", "possession": "June 2026"},
            },
        ]

        for p in sample_properties:
            if not db.query(Property).filter(Property.id == p["id"]).first():
                db.add(Property(**p))

        sample_leads = [
            {
                "id": f"lead_re_{client.id[-6:]}_101",
                "client_id": client.id,
                "name": "Rahul Sharma",
                "phone": "+919876543210",
                "email": "rahul.sharma@example.com",
                "lead_source": "MagicBricks",
                "property_viewed": "Prestige Highline Residences",
                "enquiry_location": "Whitefield",
                "enquiry_budget": "₹90 Lakhs - ₹1.1 Cr",
                "enquiry_bhk": "3 BHK",
                "lead_qualification_status": "PENDING",
            },
            {
                "id": f"lead_re_{client.id[-6:]}_102",
                "client_id": client.id,
                "name": "Priya Patel",
                "phone": "+919812345678",
                "email": "priya.patel@example.com",
                "lead_source": "Website Enquiry",
                "property_viewed": "Sobha Dream Acres",
                "enquiry_location": "Panathur",
                "enquiry_budget": "₹70 - ₹80 Lakhs",
                "enquiry_bhk": "2 BHK",
                "lead_qualification_status": "PENDING",
            },
        ]

        for l in sample_leads:
            if not db.query(Lead).filter(Lead.id == l["id"]).first():
                db.add(Lead(**l))

    db.commit()


def init_db() -> None:
    """Create tables if they do not exist and seed the initial internal administrator and catalogs."""
    Base.metadata.create_all(bind=engine)
    
    db: Session = SessionLocal()
    try:
        auth_service = AuthService(db)
        admin = auth_service.seed_initial_admin()
        if admin:
            logger.info("Internal platform admin initialized.")
        seed_catalogs(db)
        seed_real_estate_data(db)
        logger.info("Catalogs and real estate sample data seeded.")
    except Exception as e:
        logger.error(f"Error during db initialization: {e}")
        db.rollback()
    finally:
        db.close()
