import copy
from typing import Any, Dict, List, Optional
from app.core.security import generate_unique_id


class MockBusinessState:
    """
    Isolated, thread-safe, transactional business state for mock voice-agent testing.
    Ensures tests execute against real mock business data stores and assertions verify
    actual persisted records rather than just agent speech claims.
    """

    def __init__(
        self,
        doctor_schedules: Optional[Dict[str, List[str]]] = None,
        appointments: Optional[List[Dict[str, Any]]] = None,
        leads: Optional[List[Dict[str, Any]]] = None,
        custom_records: Optional[Dict[str, Any]] = None,
        configured_failures: Optional[Dict[str, str]] = None,
    ):
        self.doctor_schedules: Dict[str, List[str]] = (
            doctor_schedules
            if doctor_schedules is not None
            else {
                "Dr. Rao": ["2026-10-10 09:00 AM", "2026-10-10 10:00 AM", "2026-10-10 02:30 PM"],
                "Dr. Smith": [],
            }
        )
        self.appointments: List[Dict[str, Any]] = appointments if appointments is not None else []
        self.leads: List[Dict[str, Any]] = leads if leads is not None else []
        self.custom_records: Dict[str, Any] = custom_records if custom_records is not None else {}
        self.configured_failures: Dict[str, str] = configured_failures if configured_failures is not None else {}

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]] = None) -> "MockBusinessState":
        if not data:
            return cls()
        return cls(
            doctor_schedules=copy.deepcopy(data.get("doctor_schedules")),
            appointments=copy.deepcopy(data.get("appointments", [])),
            leads=copy.deepcopy(data.get("leads", [])),
            custom_records=copy.deepcopy(data.get("custom_records", {})),
            configured_failures=copy.deepcopy(data.get("configured_failures", {})),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "doctor_schedules": copy.deepcopy(self.doctor_schedules),
            "appointments": copy.deepcopy(self.appointments),
            "leads": copy.deepcopy(self.leads),
            "custom_records": copy.deepcopy(self.custom_records),
            "configured_failures": copy.deepcopy(self.configured_failures),
        }

    def clone(self) -> "MockBusinessState":
        return MockBusinessState.from_dict(self.to_dict())

    def check_availability(self, doctor: str = "Dr. Rao", date_str: str = "2026-10-10") -> Dict[str, Any]:
        if "check_availability" in self.configured_failures:
            error_msg = self.configured_failures["check_availability"]
            raise RuntimeError(f"Simulated tool failure: {error_msg}")

        # Check explicit doctor schedule
        if doctor in self.doctor_schedules:
            available_slots = [s for s in self.doctor_schedules[doctor] if date_str in s or not date_str]
        else:
            # Fallback for generic doctor inquiry
            available_slots = [
                f"{date_str} 09:00 AM",
                f"{date_str} 10:00 AM",
                f"{date_str} 02:30 PM",
            ]

        is_available = len(available_slots) > 0
        return {
            "available": is_available,
            "doctor": doctor,
            "date": date_str,
            "slots": available_slots,
        }

    def book_appointment(
        self,
        customer_name: str,
        slot: str,
        contact_phone: Optional[str] = None,
        doctor: Optional[str] = None,
    ) -> Dict[str, Any]:
        if "book_appointment" in self.configured_failures:
            error_msg = self.configured_failures["book_appointment"]
            raise RuntimeError(f"Simulated tool failure: {error_msg}")

        # Verify not already booked
        for existing in self.appointments:
            if existing.get("slot") == slot and existing.get("doctor") == (doctor or "Dr. Rao"):
                raise ValueError(f"Appointment slot '{slot}' is already booked.")

        confirmation_id = generate_unique_id("apt_conf_")
        resolved_doctor = doctor or "Dr. Rao"
        record = {
            "confirmation_id": confirmation_id,
            "status": "CONFIRMED",
            "customer_name": customer_name,
            "contact_phone": contact_phone or "+15550001111",
            "doctor": resolved_doctor,
            "slot": slot,
        }
        self.appointments.append(record)

        # Remove from available slots if present
        if resolved_doctor in self.doctor_schedules:
            self.doctor_schedules[resolved_doctor] = [
                s for s in self.doctor_schedules[resolved_doctor] if s != slot
            ]

        return record

    def cancel_appointment(self, confirmation_id: str, reason: str = "") -> Dict[str, Any]:
        if "cancel_appointment" in self.configured_failures:
            error_msg = self.configured_failures["cancel_appointment"]
            raise RuntimeError(f"Simulated tool failure: {error_msg}")

        for apt in self.appointments:
            if apt.get("confirmation_id") == confirmation_id:
                apt["status"] = "CANCELLED"
                apt["cancellation_reason"] = reason
                return {"success": True, "confirmation_id": confirmation_id, "status": "CANCELLED"}

        return {"success": False, "error": f"Confirmation ID '{confirmation_id}' not found."}

    def create_lead(
        self,
        name: str,
        phone: str,
        email: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        if "create_lead" in self.configured_failures:
            error_msg = self.configured_failures["create_lead"]
            raise RuntimeError(f"Simulated tool failure: {error_msg}")

        lead_id = generate_unique_id("lead_")
        record = {
            "lead_id": lead_id,
            "status": "RECORDED",
            "name": name,
            "phone": phone,
            "email": email or "",
            "notes": notes or "",
        }
        self.leads.append(record)
        return record
