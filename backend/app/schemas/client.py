from datetime import datetime
from enum import Enum
from typing import List, Optional
import re
from pydantic import BaseModel, Field, field_validator, ConfigDict


class BusinessTypeEnum(str, Enum):
    CLINIC = "CLINIC"
    HOSPITAL = "HOSPITAL"
    SALON = "SALON"
    REAL_ESTATE = "REAL_ESTATE"
    HOTEL = "HOTEL"
    RESTAURANT = "RESTAURANT"
    CORPORATE = "CORPORATE"
    OTHER = "OTHER"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper:
                    return member
            return cls.OTHER
        return cls.OTHER


class ClientStatusEnum(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            val_upper = value.strip().upper()
            for member in cls:
                if member.value == val_upper:
                    return member
            return cls.ACTIVE
        return cls.ACTIVE


class ClientBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=255, description="Business name")
    business_type: BusinessTypeEnum = Field(..., description="Industry/business classification")
    description: Optional[str] = Field(None, max_length=2000)
    contact_name: Optional[str] = Field(None, max_length=255)
    contact_email: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=64)
    timezone: str = Field("UTC", max_length=64)

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Business name cannot be blank")
        return clean

    @field_validator("contact_email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return None
        email = v.strip().lower()
        email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
        if not re.match(email_regex, email):
            raise ValueError("Invalid contact email format")
        return email

    @field_validator("contact_phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if not v or not v.strip():
            return None
        phone = v.strip()
        # Reasonable international phone validation (digits, +, -, (), spaces, length 7-25)
        phone_cleaned = re.sub(r"[\s\-\(\)\+\.]", "", phone)
        if not phone_cleaned.isdigit() or len(phone_cleaned) < 7 or len(phone_cleaned) > 20:
            raise ValueError("Invalid contact phone format")
        return phone


class ClientCreate(ClientBase):
    pass


class ClientUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=255)
    business_type: Optional[BusinessTypeEnum] = None
    description: Optional[str] = Field(None, max_length=2000)
    contact_name: Optional[str] = Field(None, max_length=255)
    contact_email: Optional[str] = Field(None, max_length=255)
    contact_phone: Optional[str] = Field(None, max_length=64)
    timezone: Optional[str] = Field(None, max_length=64)
    status: Optional[ClientStatusEnum] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            clean = v.strip()
            if not clean:
                raise ValueError("Business name cannot be blank")
            return clean
        return None

    @field_validator("contact_email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip():
            email = v.strip().lower()
            email_regex = r"^[\w\.-]+@[\w\.-]+\.\w+$"
            if not re.match(email_regex, email):
                raise ValueError("Invalid contact email format")
            return email
        return None

    @field_validator("contact_phone")
    @classmethod
    def validate_phone(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v.strip():
            phone = v.strip()
            phone_cleaned = re.sub(r"[\s\-\(\)\+\.]", "", phone)
            if not phone_cleaned.isdigit() or len(phone_cleaned) < 7 or len(phone_cleaned) > 20:
                raise ValueError("Invalid contact phone format")
            return phone
        return None


class ClientResponse(ClientBase):
    id: str
    status: ClientStatusEnum
    agent_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ClientListResponse(BaseModel):
    items: List[ClientResponse]
    total: int
