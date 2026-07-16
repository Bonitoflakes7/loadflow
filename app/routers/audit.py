from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List

from ..database import get_db
from .. import models
from ..auth import get_current_user

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/denied-log")
def get_denied_log(current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user.is_admin:
        raise HTTPException(403, "Org Admins only")
    q = db.query(models.PermissionDeniedLog)
    if current_user.account_type in ("broker", "carrier"):
        # Admins only see denials from their own org's users for privacy/scoping.
        org_user_ids = [u.id for u in db.query(models.User.id).filter(
            models.User.org_id == current_user.org_id).all()]
        q = q.filter(models.PermissionDeniedLog.user_id.in_(org_user_ids))
    rows = q.order_by(models.PermissionDeniedLog.timestamp.desc()).limit(200).all()
    return [{"id": r.id, "email": r.email, "endpoint": r.endpoint,
             "permission_required": r.permission_required, "reason": r.reason,
             "timestamp": r.timestamp} for r in rows]


@router.get("/loads/{load_id}/full-trail")
def get_full_trail(load_id: int, current_user: models.User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Combined status history + rate confirmation versions for one load —
    a single audit view. Same object-scoping rules as /loads/{id}."""
    from ..permissions import enforce_load_scope
    from fastapi import Request
    load = db.query(models.Load).filter(models.Load.id == load_id).first()
    if not load:
        raise HTTPException(404, "Load not found")

    allowed = (
        (current_user.account_type == "shipper" and load.shipper_id == current_user.id) or
        (current_user.account_type == "broker" and load.broker_org_id == current_user.org_id) or
        (current_user.account_type == "carrier" and load.carrier_org_id == current_user.org_id)
    )
    if not allowed:
        raise HTTPException(403, "Not authorized for this load")

    history = db.query(models.LoadStatusHistory).filter(models.LoadStatusHistory.load_id == load_id).order_by(
        models.LoadStatusHistory.timestamp).all()
    rates = db.query(models.RateConfirmation).filter(models.RateConfirmation.load_id == load_id).order_by(
        models.RateConfirmation.version).all()

    return {
        "status_history": [{"from": h.from_status, "to": h.to_status, "by": h.changed_by_user_id,
                             "note": h.note, "timestamp": h.timestamp} for h in history],
        "rate_versions": [{"version": r.version, "base_rate": r.base_rate, "accessorials": r.accessorials,
                            "is_current": r.is_current, "created_at": r.created_at} for r in rates],
    }
