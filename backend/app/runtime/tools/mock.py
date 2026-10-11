from typing import Any, Dict
from pydantic import BaseModel


class ToolResult(BaseModel):
    tool_call_id: str
    success: bool
    data: Dict[str, Any]
    error: str = ""


class BaseToolHandler:
    @property
    def tool_id(self) -> str:
        raise NotImplementedError

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        raise NotImplementedError


class MockCheckAvailabilityTool(BaseToolHandler):
    """
    Mock calendar/schedule availability tool.
    ENVIRONMENT: development/test
    """
    @property
    def tool_id(self) -> str:
        return "check_availability"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        doctor = arguments.get("doctor", "Assigned Provider")
        date_str = arguments.get("date", "2026-10-10")
        return {
            "available": True,
            "doctor": doctor,
            "date": date_str,
            "slots": [
                f"{date_str} 09:00 AM",
                f"{date_str} 10:00 AM",
                f"{date_str} 02:30 PM",
            ]
        }


class MockBookAppointmentTool(BaseToolHandler):
    """
    Mock appointment confirmation tool.
    ENVIRONMENT: development/test
    """
    @property
    def tool_id(self) -> str:
        return "book_appointment"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        customer = arguments.get("customer_name", "Caller")
        slot = arguments.get("slot", "2026-10-10 10:00 AM")
        return {
            "confirmation_id": "apt_conf_98721",
            "status": "CONFIRMED",
            "customer_name": customer,
            "slot": slot
        }


class MockCreateLeadTool(BaseToolHandler):
    """
    Mock CRM lead creation tool.
    ENVIRONMENT: development/test
    """
    @property
    def tool_id(self) -> str:
        return "create_lead"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        return {
            "lead_id": "lead_mock_441",
            "status": "RECORDED"
        }


class MockGetLeadDetailsTool(BaseToolHandler):
    """
    Mock lead retrieval tool for real estate qualification.
    """
    @property
    def tool_id(self) -> str:
        return "get_lead_details"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        lead_id = arguments.get("lead_id", "lead_re_101")
        try:
            from app.db.session import SessionLocal
            from app.models.lead import Lead
            db = SessionLocal()
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                res = {
                    "found": True,
                    "lead_id": lead.id,
                    "name": lead.name,
                    "phone": lead.phone,
                    "lead_source": lead.lead_source,
                    "property_viewed": lead.property_viewed,
                    "enquiry_location": lead.enquiry_location,
                    "enquiry_budget": lead.enquiry_budget,
                    "enquiry_bhk": lead.enquiry_bhk,
                    "qualification_status": lead.lead_qualification_status,
                }
                db.close()
                return res
            db.close()
        except Exception:
            pass

        return {
            "found": True,
            "lead_id": lead_id,
            "name": "Rahul Sharma",
            "phone": "+919876543210",
            "lead_source": "MagicBricks",
            "property_viewed": "Prestige Highline Residences",
            "enquiry_location": "Whitefield",
            "enquiry_budget": "₹90 Lakhs - ₹1.1 Cr",
            "enquiry_bhk": "3 BHK",
            "qualification_status": "PENDING",
        }


class MockSearchPropertiesTool(BaseToolHandler):
    """
    Mock property search tool for structured inventory filtering.
    """
    @property
    def tool_id(self) -> str:
        return "search_properties"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        location_filter = str(arguments.get("location", "")).lower().strip()
        bhk_filter = arguments.get("bhk")
        budget_min = arguments.get("budget_min")
        budget_max = arguments.get("budget_max")
        status_filter = str(arguments.get("status", "AVAILABLE")).upper()

        try:
            from app.db.session import SessionLocal
            from app.models.property import Property
            db = SessionLocal()
            q = db.query(Property)
            if status_filter:
                q = q.filter(Property.status == status_filter)
            if location_filter:
                q = q.filter(Property.location.ilike(f"%{location_filter}%"))
            if bhk_filter:
                try:
                    q = q.filter(Property.bhk == int(bhk_filter))
                except Exception:
                    pass
            if budget_max:
                try:
                    q = q.filter(Property.price <= int(budget_max))
                except Exception:
                    pass
            if budget_min:
                try:
                    q = q.filter(Property.price >= int(budget_min))
                except Exception:
                    pass

            db_props = q.limit(5).all()
            if db_props:
                items = [
                    {
                        "id": p.id,
                        "project_name": p.project_name,
                        "location": p.location,
                        "bhk": p.bhk,
                        "price": p.price,
                        "price_display": p.price_display,
                        "property_type": p.property_type,
                        "status": p.status,
                        "amenities": p.amenities,
                    }
                    for p in db_props
                ]
                db.close()
                return {"count": len(items), "properties": items}
            db.close()
        except Exception:
            pass

        all_props = [
            {
                "id": "prop_01",
                "project_name": "Prestige Highline Residences",
                "location": "Whitefield",
                "bhk": 3,
                "price": 9500000,
                "price_display": "₹95 Lakhs",
                "property_type": "Apartment",
                "status": "AVAILABLE",
                "amenities": ["Gym", "Covered Parking", "Clubhouse", "Children Play Area"],
            },
            {
                "id": "prop_02",
                "project_name": "Prestige Palm Meadows Villa",
                "location": "Whitefield",
                "bhk": 4,
                "price": 24000000,
                "price_display": "₹2.4 Cr",
                "property_type": "Villa",
                "status": "AVAILABLE",
                "amenities": ["Private Garden", "Clubhouse", "24/7 Security", "Swimming Pool"],
            },
            {
                "id": "prop_03",
                "project_name": "Sobha Dream Acres",
                "location": "Panathur",
                "bhk": 2,
                "price": 7500000,
                "price_display": "₹75 Lakhs",
                "property_type": "Apartment",
                "status": "AVAILABLE",
                "amenities": ["Swimming Pool", "Jogging Track", "Badminton Court"],
            },
            {
                "id": "prop_04",
                "project_name": "Brigade Cornerstone Utopia",
                "location": "Varthur",
                "bhk": 3,
                "price": 11500000,
                "price_display": "₹1.15 Cr",
                "property_type": "Apartment",
                "status": "AVAILABLE",
                "amenities": ["Clubhouse", "Tennis Court", "Multiplex", "Supermarket"],
            },
        ]

        filtered = []
        for p in all_props:
            if location_filter and location_filter not in p["location"].lower() and location_filter not in p["project_name"].lower():
                continue
            if bhk_filter is not None:
                try:
                    if int(bhk_filter) != p["bhk"]:
                        continue
                except Exception:
                    pass
            filtered.append(p)

        return {
            "count": len(filtered),
            "properties": filtered if filtered else all_props[:2]
        }


class MockCheckSiteVisitSlotsTool(BaseToolHandler):
    """
    Mock site-visit slot checking tool.
    """
    @property
    def tool_id(self) -> str:
        return "check_site_visit_slots"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        property_id = arguments.get("property_id", "prop_01")
        preferred_date = arguments.get("preferred_date", "tomorrow")
        return {
            "property_id": property_id,
            "preferred_date": preferred_date,
            "available_slots": [
                "Tomorrow at 10:30 AM",
                "Tomorrow at 03:00 PM",
                "Saturday at 11:00 AM",
                "Sunday at 04:30 PM",
            ],
            "sales_executive": "Vikram Singh (Senior Property Consultant)",
            "meeting_point": "Project Experience Centre & Model Flat"
        }


class MockUpdateLeadRecordTool(BaseToolHandler):
    """
    Mock CRM lead record update tool.
    """
    @property
    def tool_id(self) -> str:
        return "update_lead_record"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        lead_id = arguments.get("lead_id", "lead_re_101")
        buyer_budget = arguments.get("buyer_budget")
        buyer_location = arguments.get("buyer_location")
        buyer_bhk = arguments.get("buyer_bhk")
        qualification_status = arguments.get("lead_qualification_status", "QUALIFIED")
        call_disposition = arguments.get("call_disposition", "INTERESTED")
        next_action = arguments.get("next_action", "Site visit scheduled")

        try:
            from app.db.session import SessionLocal
            from app.models.lead import Lead
            db = SessionLocal()
            lead = db.query(Lead).filter(Lead.id == lead_id).first()
            if lead:
                if buyer_budget:
                    lead.buyer_budget = str(buyer_budget)
                if buyer_location:
                    lead.buyer_location = str(buyer_location)
                if buyer_bhk:
                    lead.buyer_bhk = str(buyer_bhk)
                if qualification_status:
                    lead.lead_qualification_status = str(qualification_status)
                if call_disposition:
                    lead.call_disposition = str(call_disposition)
                if next_action:
                    lead.next_action = str(next_action)
                db.commit()
                db.close()
        except Exception:
            pass

        return {
            "success": True,
            "lead_id": lead_id,
            "status": "RECORD_UPDATED",
            "qualification_status": qualification_status,
            "call_disposition": call_disposition,
            "next_action": next_action,
        }


class MockBookSiteVisitTool(BaseToolHandler):
    """Mock site visit confirmation tool."""
    @property
    def tool_id(self) -> str:
        return "book_site_visit"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        return {
            "booking_id": "sv_98214",
            "status": "CONFIRMED",
            "property_name": arguments.get("property_name", "Prestige Highline"),
            "slot": arguments.get("slot", "Saturday 11:00 AM"),
            "confirmation_sms_sent": True
        }


class MockScheduleCallbackTool(BaseToolHandler):
    """Mock sales callback scheduling tool."""
    @property
    def tool_id(self) -> str:
        return "schedule_callback"

    def execute(self, arguments: Dict[str, Any], timeout: int = 15) -> Dict[str, Any]:
        return {
            "callback_id": "cb_54129",
            "status": "SCHEDULED",
            "preferred_time": arguments.get("preferred_time", "Tomorrow 2:00 PM"),
            "assigned_manager": "Pooja Verma"
        }
