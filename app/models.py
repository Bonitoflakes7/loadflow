from sqlalchemy import (
    Column, Integer, String, Boolean, Float, DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

# ---------------------------------------------------------------------------
# Fixed permission catalog. Code checks against these strings, never role
# names. Admins compose roles as bundles of these permissions via the API/UI.
# ---------------------------------------------------------------------------
PERMISSION_CATALOG = [
    "load.create",
    "load.assign_carrier",
    "load.override_compliance_flag",
    "rate.confirm",
    "load.update_status",
    "staff.manage",
    "pod.upload",
    "load.accept_decline",  # carrier-side accept/decline of an assigned load
]

LOAD_STATES = [
    "Posted",
    "Carrier Assigned",
    "Rate Confirmed",
    "Dispatched",
    "In Transit",
    "Delivered",
    "POD Verified",
    "Invoiced/Closed",
]


class Org(Base):
    __tablename__ = "orgs"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False)  # 'broker' | 'carrier'
    created_at = Column(DateTime, default=datetime.utcnow)

    users = relationship("User", back_populates="org")
    roles = relationship("Role", back_populates="org")


class Role(Base):
    __tablename__ = "roles"
    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("orgs.id"), nullable=False)
    name = Column(String, nullable=False)
    permissions = Column(JSON, default=list)  # list[str] subset of PERMISSION_CATALOG

    org = relationship("Org", back_populates="roles")
    users = relationship("User", back_populates="role")


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    account_type = Column(String, nullable=False)  # 'broker' | 'carrier' | 'shipper'
    org_id = Column(Integer, ForeignKey("orgs.id"), nullable=True)  # null for shipper
    role_id = Column(Integer, ForeignKey("roles.id"), nullable=True)  # null for shipper
    is_admin = Column(Boolean, default=False)  # org admin (broker/carrier only)
    full_name = Column(String, default="")
    company_name = Column(String, default="")  # for shipper display
    created_at = Column(DateTime, default=datetime.utcnow)

    org = relationship("Org", back_populates="users")
    role = relationship("Role", back_populates="users")


class ComplianceRecord(Base):
    __tablename__ = "compliance_records"
    id = Column(Integer, primary_key=True)
    carrier_org_id = Column(Integer, ForeignKey("orgs.id"), nullable=False, unique=True)
    insurance_expiry = Column(DateTime, nullable=True)
    authority_status = Column(String, default="pending")  # active | inactive | pending
    approved_equipment = Column(JSON, default=list)   # e.g. ["Dry Van","Reefer"]
    approved_commodities = Column(JSON, default=list)  # e.g. ["General","Frozen"]
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Load(Base):
    __tablename__ = "loads"
    id = Column(Integer, primary_key=True)
    broker_org_id = Column(Integer, ForeignKey("orgs.id"), nullable=False)
    shipper_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    carrier_org_id = Column(Integer, ForeignKey("orgs.id"), nullable=True)

    origin = Column(String, nullable=False)
    destination = Column(String, nullable=False)
    pickup_date = Column(DateTime, nullable=True)
    delivery_date = Column(DateTime, nullable=True)
    equipment_type = Column(String, default="Dry Van")
    commodity_type = Column(String, default="General")

    status = Column(String, default="Posted")

    compliance_flag = Column(Boolean, default=False)
    compliance_flag_reason = Column(Text, default="")
    compliance_override_by = Column(Integer, ForeignKey("users.id"), nullable=True)

    current_rate_confirmation_id = Column(Integer, ForeignKey("rate_confirmations.id"), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RateConfirmation(Base):
    __tablename__ = "rate_confirmations"
    id = Column(Integer, primary_key=True)
    load_id = Column(Integer, ForeignKey("loads.id"), nullable=False)
    version = Column(Integer, nullable=False)
    base_rate = Column(Float, nullable=False)
    accessorials = Column(JSON, default=list)  # list[{"name":str,"amount":float}]
    confirmed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    is_current = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LoadStatusHistory(Base):
    __tablename__ = "load_status_history"
    id = Column(Integer, primary_key=True)
    load_id = Column(Integer, ForeignKey("loads.id"), nullable=False)
    from_status = Column(String, nullable=True)
    to_status = Column(String, nullable=False)
    changed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    note = Column(Text, default="")
    timestamp = Column(DateTime, default=datetime.utcnow)


class PODFile(Base):
    __tablename__ = "pod_files"
    id = Column(Integer, primary_key=True)
    load_id = Column(Integer, ForeignKey("loads.id"), nullable=False)
    filename = Column(String, nullable=False)
    stored_path = Column(String, nullable=False)
    uploaded_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    uploaded_at = Column(DateTime, default=datetime.utcnow)


class PermissionDeniedLog(Base):
    __tablename__ = "permission_denied_log"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    email = Column(String, default="")
    endpoint = Column(String, nullable=False)
    permission_required = Column(String, default="")
    reason = Column(String, default="")
    timestamp = Column(DateTime, default=datetime.utcnow)
