from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user

router = APIRouter(prefix="/compliance", tags=["compliance"])


@router.post("", response_model=schemas.ComplianceOut)
def upsert_compliance(payload: schemas.ComplianceUpsert,
                       current_user: models.User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    # Only the carrier org's own admin/staff-with-staff.manage may edit its record.
    if current_user.account_type != "carrier":
        raise HTTPException(403, "Only carrier accounts manage compliance records")
    if current_user.org_id != payload.carrier_org_id:
        raise HTTPException(403, "Cannot edit another carrier org's compliance record")
    if not current_user.is_admin:
        from ..permissions import user_has_permission
        if not user_has_permission(current_user, "staff.manage"):
            raise HTTPException(403, "Missing required permission: staff.manage")

    record = db.query(models.ComplianceRecord).filter(
        models.ComplianceRecord.carrier_org_id == payload.carrier_org_id).first()
    if not record:
        record = models.ComplianceRecord(carrier_org_id=payload.carrier_org_id)
        db.add(record)

    record.insurance_expiry = payload.insurance_expiry
    record.authority_status = payload.authority_status
    record.approved_equipment = payload.approved_equipment
    record.approved_commodities = payload.approved_commodities
    db.commit()
    db.refresh(record)
    return record


@router.get("/{carrier_org_id}", response_model=schemas.ComplianceOut)
def get_compliance(carrier_org_id: int, current_user: models.User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    # Brokers may view any carrier's record (needed to assign loads safely);
    # carrier staff may only view their own org's record.
    if current_user.account_type == "carrier" and current_user.org_id != carrier_org_id:
        raise HTTPException(403, "Cannot view another carrier org's compliance record")
    if current_user.account_type == "shipper":
        raise HTTPException(403, "Not applicable to shipper accounts")

    record = db.query(models.ComplianceRecord).filter(
        models.ComplianceRecord.carrier_org_id == carrier_org_id).first()
    if not record:
        raise HTTPException(404, "No compliance record for this carrier yet")
    return record


@router.get("", response_model=List[schemas.ComplianceOut])
def list_all_compliance(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Broker-wide compliance visibility, e.g. for renewal-alert dashboards."""
    if current_user.account_type != "broker":
        raise HTTPException(403, "Broker accounts only")
    return db.query(models.ComplianceRecord).all()
