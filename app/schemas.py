from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


# ---------- Auth ----------
class RegisterOrgAdmin(BaseModel):
    org_name: str
    org_type: str  # 'broker' | 'carrier'
    email: EmailStr
    password: str
    full_name: str = ""


class RegisterShipper(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""
    company_name: str = ""


class Login(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    account_type: str
    is_admin: bool
    org_id: Optional[int] = None
    org_name: Optional[str] = None
    permissions: List[str] = []
    user_id: int
    full_name: str = ""


# ---------- Roles / Staff ----------
class RoleCreate(BaseModel):
    name: str
    permissions: List[str]


class RoleOut(BaseModel):
    id: int
    name: str
    permissions: List[str]

    class Config:
        from_attributes = True


class StaffInvite(BaseModel):
    email: EmailStr
    password: str
    full_name: str = ""
    role_id: int
    is_admin: bool = False


class StaffOut(BaseModel):
    id: int
    email: str
    full_name: str
    is_admin: bool
    role_id: Optional[int]

    class Config:
        from_attributes = True


# ---------- Compliance ----------
class ComplianceUpsert(BaseModel):
    carrier_org_id: int
    insurance_expiry: Optional[datetime] = None
    authority_status: str = "pending"
    approved_equipment: List[str] = []
    approved_commodities: List[str] = []


class ComplianceOut(BaseModel):
    id: int
    carrier_org_id: int
    insurance_expiry: Optional[datetime]
    authority_status: str
    approved_equipment: List[str]
    approved_commodities: List[str]
    updated_at: datetime

    class Config:
        from_attributes = True


# ---------- Loads ----------
class LoadCreate(BaseModel):
    origin: str
    destination: str
    pickup_date: Optional[datetime] = None
    delivery_date: Optional[datetime] = None
    equipment_type: str = "Dry Van"
    commodity_type: str = "General"
    shipper_id: int


class LoadUpdate(BaseModel):
    origin: Optional[str] = None
    destination: Optional[str] = None
    pickup_date: Optional[datetime] = None
    delivery_date: Optional[datetime] = None
    equipment_type: Optional[str] = None
    commodity_type: Optional[str] = None


class LoadAssignCarrier(BaseModel):
    carrier_org_id: int


class AccessorialItem(BaseModel):
    name: str
    amount: float


class RateConfirmCreate(BaseModel):
    base_rate: float
    accessorials: List[AccessorialItem] = []


class StatusUpdate(BaseModel):
    to_status: str
    note: str = ""


class OverrideCompliance(BaseModel):
    note: str = ""


class LoadOut(BaseModel):
    id: int
    broker_org_id: int
    shipper_id: int
    carrier_org_id: Optional[int]
    origin: str
    destination: str
    pickup_date: Optional[datetime]
    delivery_date: Optional[datetime]
    equipment_type: str
    commodity_type: str
    status: str
    compliance_flag: bool
    compliance_flag_reason: str
    current_rate_confirmation_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RateConfirmationOut(BaseModel):
    id: int
    load_id: int
    version: int
    base_rate: float
    accessorials: list
    confirmed_by_user_id: int
    is_current: bool
    created_at: datetime

    class Config:
        from_attributes = True


class HistoryOut(BaseModel):
    id: int
    from_status: Optional[str]
    to_status: str
    changed_by_user_id: int
    note: str
    timestamp: datetime

    class Config:
        from_attributes = True
