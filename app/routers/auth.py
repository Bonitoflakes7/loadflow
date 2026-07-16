from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from .. import models, schemas
from ..auth import hash_password, verify_password, create_access_token
from ..permissions import user_has_permission

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(user: models.User) -> schemas.Token:
    perms = []
    if user.role:
        perms = user.role.permissions or []
    token = create_access_token({"sub": str(user.id)})
    return schemas.Token(
        access_token=token,
        account_type=user.account_type,
        is_admin=user.is_admin,
        org_id=user.org_id,
        org_name=user.org.name if user.org else None,
        permissions=perms,
        user_id=user.id,
        full_name=user.full_name,
    )


@router.post("/register-org", response_model=schemas.Token)
def register_org_admin(payload: schemas.RegisterOrgAdmin, db: Session = Depends(get_db)):
    """Bootstrap endpoint: creates a brand-new Broker or Carrier org along with
    its first Admin user. This is the ONLY way an org's first account is
    created — every subsequent staff member must be invited by that Admin
    via /orgs/staff, not through this endpoint."""
    if payload.org_type not in ("broker", "carrier"):
        raise HTTPException(400, "org_type must be 'broker' or 'carrier'")
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(400, "Email already registered")

    org = models.Org(name=payload.org_name, type=payload.org_type)
    db.add(org)
    db.flush()

    # Give the org a default full-access "Admin" role for visibility in the UI,
    # though is_admin=True already grants full permission checks.
    admin_role = models.Role(org_id=org.id, name="Admin", permissions=models.PERMISSION_CATALOG)
    db.add(admin_role)
    db.flush()

    user = models.User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        account_type=payload.org_type,
        org_id=org.id,
        role_id=admin_role.id,
        is_admin=True,
        full_name=payload.full_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/register-shipper", response_model=schemas.Token)
def register_shipper(payload: schemas.RegisterShipper, db: Session = Depends(get_db)):
    """Shippers self-register directly; they have no org and no sub-roles."""
    if db.query(models.User).filter(models.User.email == payload.email).first():
        raise HTTPException(400, "Email already registered")
    user = models.User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        account_type="shipper",
        org_id=None,
        role_id=None,
        is_admin=False,
        full_name=payload.full_name,
        company_name=payload.company_name,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.email == form_data.username).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    return _token_response(user)
