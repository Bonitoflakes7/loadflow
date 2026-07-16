from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user, hash_password
from ..permissions import require_permission

router = APIRouter(prefix="/orgs", tags=["orgs"])


def _require_org_admin(current_user: models.User = Depends(get_current_user)) -> models.User:
    if current_user.account_type not in ("broker", "carrier") or not current_user.is_admin:
        raise HTTPException(403, "Only a Broker/Carrier org Admin may perform this action")
    return current_user


@router.get("/permission-catalog", response_model=List[str])
def get_permission_catalog():
    return models.PERMISSION_CATALOG


@router.post("/roles", response_model=schemas.RoleOut)
def create_role(payload: schemas.RoleCreate, admin: models.User = Depends(_require_org_admin),
                 db: Session = Depends(get_db)):
    bad = [p for p in payload.permissions if p not in models.PERMISSION_CATALOG]
    if bad:
        raise HTTPException(400, f"Unknown permissions: {bad}")
    role = models.Role(org_id=admin.org_id, name=payload.name, permissions=payload.permissions)
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


@router.get("/roles", response_model=List[schemas.RoleOut])
def list_roles(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.account_type not in ("broker", "carrier"):
        raise HTTPException(403, "Not applicable to shipper accounts")
    return db.query(models.Role).filter(models.Role.org_id == current_user.org_id).all()


@router.post("/staff", response_model=schemas.StaffOut)
def invite_staff(payload: schemas.StaffInvite, admin: models.User = Depends(_require_org_admin),
                  db: Session = Depends(get_db)):
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(400, "Email already registered")
    role = db.query(models.Role).filter(models.Role.id == payload.role_id,
                                         models.Role.org_id == admin.org_id).first()
    if not role:
        raise HTTPException(404, "Role not found in your org")
    staff = models.User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        account_type=admin.account_type,
        org_id=admin.org_id,
        role_id=role.id,
        is_admin=payload.is_admin,
        full_name=payload.full_name,
    )
    db.add(staff)
    db.commit()
    db.refresh(staff)
    return staff


@router.get("/staff", response_model=List[schemas.StaffOut])
def list_staff(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if current_user.account_type not in ("broker", "carrier"):
        raise HTTPException(403, "Not applicable to shipper accounts")
    return db.query(models.User).filter(models.User.org_id == current_user.org_id).all()


@router.get("/carriers", response_model=List[dict])
def list_carrier_orgs(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Used by brokers to pick a carrier org when assigning a load."""
    if current_user.account_type != "broker":
        raise HTTPException(403, "Broker accounts only")
    carriers = db.query(models.Org).filter(models.Org.type == "carrier").all()
    return [{"id": c.id, "name": c.name} for c in carriers]


@router.get("/shippers", response_model=List[dict])
def list_shippers(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Used by brokers when creating a load on a shipper's behalf."""
    if current_user.account_type != "broker":
        raise HTTPException(403, "Broker accounts only")
    shippers = db.query(models.User).filter(models.User.account_type == "shipper").all()
    return [{"id": s.id, "email": s.email, "full_name": s.full_name, "company_name": s.company_name}
            for s in shippers]
