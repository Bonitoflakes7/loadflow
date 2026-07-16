import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from ..database import get_db
from .. import models, schemas
from ..auth import get_current_user
from ..permissions import require_permission, require_account_type, enforce_load_scope, user_has_permission, _log_denied

router = APIRouter(prefix="/loads", tags=["loads"])

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _record_history(db: Session, load: models.Load, from_status: Optional[str], to_status: str,
                     user: models.User, note: str = ""):
    hist = models.LoadStatusHistory(load_id=load.id, from_status=from_status, to_status=to_status,
                                     changed_by_user_id=user.id, note=note)
    db.add(hist)


def _check_compliance(db: Session, load: models.Load) -> tuple[bool, str]:
    """Returns (is_flagged, reason). Called whenever a carrier is
    (re)assigned to a load, so the flag always reflects current state."""
    if not load.carrier_org_id:
        return False, ""
    record = db.query(models.ComplianceRecord).filter(
        models.ComplianceRecord.carrier_org_id == load.carrier_org_id).first()
    if not record:
        return True, "No compliance record on file for this carrier."

    reasons = []
    if record.authority_status != "active":
        reasons.append(f"MC/DOT authority status is '{record.authority_status}', not active.")
    if not record.insurance_expiry or record.insurance_expiry < datetime.utcnow():
        reasons.append("Insurance is expired or missing.")
    if load.equipment_type not in (record.approved_equipment or []):
        reasons.append(f"Carrier not approved for equipment type '{load.equipment_type}'.")
    if load.commodity_type not in (record.approved_commodities or []):
        reasons.append(f"Carrier not approved for commodity type '{load.commodity_type}'.")

    if reasons:
        return True, " ".join(reasons)
    return False, ""


def _get_load_or_404(db: Session, load_id: int) -> models.Load:
    load = db.query(models.Load).filter(models.Load.id == load_id).first()
    if not load:
        raise HTTPException(404, "Load not found")
    return load


@router.post("", response_model=schemas.LoadOut)
def create_load(payload: schemas.LoadCreate,
                 current_user: models.User = Depends(require_permission("load.create")),
                 db: Session = Depends(get_db)):
    if current_user.account_type != "broker":
        raise HTTPException(403, "Only broker staff may create loads")
    shipper = db.query(models.User).filter(models.User.id == payload.shipper_id,
                                            models.User.account_type == "shipper").first()
    if not shipper:
        raise HTTPException(404, "Shipper not found")

    load = models.Load(
        broker_org_id=current_user.org_id,
        shipper_id=payload.shipper_id,
        origin=payload.origin,
        destination=payload.destination,
        pickup_date=payload.pickup_date,
        delivery_date=payload.delivery_date,
        equipment_type=payload.equipment_type,
        commodity_type=payload.commodity_type,
        status="Posted",
    )
    db.add(load)
    db.flush()
    _record_history(db, load, None, "Posted", current_user, "Load posted")
    db.commit()
    db.refresh(load)
    return load


@router.get("", response_model=List[schemas.LoadOut])
def list_loads(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    origin: Optional[str] = None,
    destination: Optional[str] = None,
    carrier_org_id: Optional[int] = None,
    equipment_type: Optional[str] = None,
    compliance_flag: Optional[bool] = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The broker load board (with search/filter), and the equivalent
    org/object-scoped views for carrier staff and shippers."""
    q = db.query(models.Load)

    if current_user.account_type == "broker":
        q = q.filter(models.Load.broker_org_id == current_user.org_id)
    elif current_user.account_type == "carrier":
        q = q.filter(models.Load.carrier_org_id == current_user.org_id)
    elif current_user.account_type == "shipper":
        q = q.filter(models.Load.shipper_id == current_user.id)

    if status_filter:
        q = q.filter(models.Load.status == status_filter)
    if origin:
        q = q.filter(models.Load.origin.ilike(f"%{origin}%"))
    if destination:
        q = q.filter(models.Load.destination.ilike(f"%{destination}%"))
    if carrier_org_id is not None:
        q = q.filter(models.Load.carrier_org_id == carrier_org_id)
    if equipment_type:
        q = q.filter(models.Load.equipment_type == equipment_type)
    if compliance_flag is not None:
        q = q.filter(models.Load.compliance_flag == compliance_flag)

    return q.order_by(models.Load.created_at.desc()).all()


@router.get("/{load_id}", response_model=schemas.LoadOut)
def get_load(load_id: int, request: Request, current_user: models.User = Depends(get_current_user),
             db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    return load


@router.patch("/{load_id}", response_model=schemas.LoadOut)
def update_load(load_id: int, payload: schemas.LoadUpdate, request: Request,
                 current_user: models.User = Depends(require_permission("load.create")),
                 db: Session = Depends(get_db)):
    """Edit basic load fields. Only allowed while still 'Posted' — once a
    carrier is assigned/rate is confirmed, changing origin/destination/
    equipment could silently invalidate the compliance check or the rate,
    so those go through dedicated flows instead."""
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    if current_user.account_type != "broker":
        raise HTTPException(403, "Only broker staff may edit loads")
    if load.status != "Posted":
        raise HTTPException(400, "Load can only be edited while still 'Posted'")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(load, field, value)
    db.commit()
    db.refresh(load)
    return load


@router.delete("/{load_id}")
def delete_load(load_id: int, request: Request,
                 current_user: models.User = Depends(require_permission("load.create")),
                 db: Session = Depends(get_db)):
    """Delete/cancel a load. Only allowed while still 'Posted' (no carrier
    engaged yet) — once a carrier is assigned, cancellation should go through
    an explicit status transition instead of disappearing from history."""
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    if current_user.account_type != "broker":
        raise HTTPException(403, "Only broker staff may delete loads")
    if load.status != "Posted":
        raise HTTPException(400, "Only 'Posted' loads (no carrier engaged yet) can be deleted")

    db.query(models.LoadStatusHistory).filter(models.LoadStatusHistory.load_id == load_id).delete()
    db.delete(load)
    db.commit()
    return {"detail": f"Load #{load_id} deleted"}


@router.post("/{load_id}/assign-carrier", response_model=schemas.LoadOut)
def assign_carrier(load_id: int, payload: schemas.LoadAssignCarrier, request: Request,
                    current_user: models.User = Depends(require_permission("load.assign_carrier")),
                    db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    if load.status != "Posted":
        raise HTTPException(400, f"Cannot assign a carrier while load is in '{load.status}' state")

    carrier_org = db.query(models.Org).filter(models.Org.id == payload.carrier_org_id,
                                               models.Org.type == "carrier").first()
    if not carrier_org:
        raise HTTPException(404, "Carrier org not found")

    load.carrier_org_id = payload.carrier_org_id
    flagged, reason = _check_compliance(db, load)
    load.compliance_flag = flagged
    load.compliance_flag_reason = reason
    old_status = load.status
    load.status = "Carrier Assigned"
    _record_history(db, load, old_status, load.status, current_user,
                     f"Assigned carrier org {payload.carrier_org_id}" + (f" — FLAGGED: {reason}" if flagged else ""))
    db.commit()
    db.refresh(load)
    return load


@router.post("/{load_id}/decline", response_model=schemas.LoadOut)
def carrier_decline(load_id: int, request: Request,
                     current_user: models.User = Depends(require_permission("load.accept_decline")),
                     db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    if load.status != "Carrier Assigned":
        raise HTTPException(400, "Can only decline a load while in 'Carrier Assigned' state")
    old_status = load.status
    load.carrier_org_id = None
    load.compliance_flag = False
    load.compliance_flag_reason = ""
    load.status = "Posted"
    _record_history(db, load, old_status, load.status, current_user, "Carrier declined the load")
    db.commit()
    db.refresh(load)
    return load


@router.post("/{load_id}/override-compliance", response_model=schemas.LoadOut)
def override_compliance(load_id: int, payload: schemas.OverrideCompliance, request: Request,
                         current_user: models.User = Depends(require_permission("load.override_compliance_flag")),
                         db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    if not load.compliance_flag:
        raise HTTPException(400, "Load is not currently flagged")
    load.compliance_flag = False
    load.compliance_override_by = current_user.id
    note = f"Compliance flag manually overridden by {current_user.email}. {payload.note}".strip()
    load.compliance_flag_reason = f"[OVERRIDDEN] {load.compliance_flag_reason}"
    _record_history(db, load, load.status, load.status, current_user, note)
    db.commit()
    db.refresh(load)
    return load


@router.post("/{load_id}/rate-confirm", response_model=schemas.RateConfirmationOut)
def confirm_rate(load_id: int, payload: schemas.RateConfirmCreate, request: Request,
                  current_user: models.User = Depends(require_permission("rate.confirm")),
                  db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    if load.status not in ("Carrier Assigned", "Rate Confirmed"):
        raise HTTPException(400, f"Cannot confirm a rate while load is in '{load.status}' state")
    if load.compliance_flag:
        raise HTTPException(400, "Load is compliance-flagged; resolve or override before confirming a rate")

    prev = db.query(models.RateConfirmation).filter(models.RateConfirmation.load_id == load_id).order_by(
        models.RateConfirmation.version.desc()).first()
    next_version = (prev.version + 1) if prev else 1
    if prev:
        prev.is_current = False

    rc = models.RateConfirmation(
        load_id=load_id,
        version=next_version,
        base_rate=payload.base_rate,
        accessorials=[a.model_dump() for a in payload.accessorials],
        confirmed_by_user_id=current_user.id,
        is_current=True,
    )
    db.add(rc)
    db.flush()

    load.current_rate_confirmation_id = rc.id
    old_status = load.status
    load.status = "Rate Confirmed"
    _record_history(db, load, old_status, load.status, current_user, f"Rate confirmation v{next_version} created")
    db.commit()
    db.refresh(rc)
    return rc


@router.get("/{load_id}/rate-confirmations", response_model=List[schemas.RateConfirmationOut])
def list_rate_confirmations(load_id: int, request: Request, current_user: models.User = Depends(get_current_user),
                             db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    return db.query(models.RateConfirmation).filter(models.RateConfirmation.load_id == load_id).order_by(
        models.RateConfirmation.version).all()


STATE_ORDER = models.LOAD_STATES  # Posted ... Invoiced/Closed


@router.post("/{load_id}/status", response_model=schemas.LoadOut)
def update_status(load_id: int, payload: schemas.StatusUpdate, request: Request,
                   current_user: models.User = Depends(require_permission("load.update_status")),
                   db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)

    if payload.to_status not in STATE_ORDER:
        raise HTTPException(400, f"Unknown status '{payload.to_status}'")

    cur_idx = STATE_ORDER.index(load.status)
    new_idx = STATE_ORDER.index(payload.to_status)
    if new_idx != cur_idx + 1:
        raise HTTPException(400, f"Invalid transition: '{load.status}' -> '{payload.to_status}'. "
                                  f"Loads must move forward one state at a time.")

    # Compliance auto-flag blocks progression past "Carrier Assigned".
    if load.compliance_flag and cur_idx >= STATE_ORDER.index("Carrier Assigned"):
        _log_denied(db, request, current_user, "load.update_status",
                    "blocked by unresolved compliance flag")
        raise HTTPException(400, f"Blocked: load is compliance-flagged ({load.compliance_flag_reason}). "
                                  f"Resolve the carrier's compliance record or have an Ops Lead override it.")

    if payload.to_status == "Dispatched" and load.status != "Rate Confirmed":
        raise HTTPException(400, "A rate must be confirmed before dispatch")

    old_status = load.status
    load.status = payload.to_status
    _record_history(db, load, old_status, load.status, current_user, payload.note)
    db.commit()
    db.refresh(load)
    return load


@router.get("/{load_id}/history", response_model=List[schemas.HistoryOut])
def get_history(load_id: int, request: Request, current_user: models.User = Depends(get_current_user),
                 db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    return db.query(models.LoadStatusHistory).filter(models.LoadStatusHistory.load_id == load_id).order_by(
        models.LoadStatusHistory.timestamp).all()


@router.post("/{load_id}/pod")
def upload_pod(load_id: int, request: Request, file: UploadFile = File(...),
               current_user: models.User = Depends(require_permission("pod.upload")),
               db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    if load.status not in ("Delivered", "In Transit"):
        raise HTTPException(400, "POD can only be uploaded once the load is In Transit or Delivered")

    safe_name = f"load{load_id}_{datetime.utcnow().timestamp()}_{file.filename}"
    dest_path = os.path.join(UPLOAD_DIR, safe_name)
    with open(dest_path, "wb") as f:
        f.write(file.file.read())

    pod = models.PODFile(load_id=load_id, filename=file.filename, stored_path=dest_path,
                          uploaded_by_user_id=current_user.id)
    db.add(pod)

    if load.status == "Delivered":
        old_status = load.status
        load.status = "POD Verified"
        _record_history(db, load, old_status, load.status, current_user, f"POD uploaded: {file.filename}")

    db.commit()
    return {"detail": "POD uploaded", "filename": file.filename, "load_status": load.status}


@router.get("/{load_id}/pod")
def list_pods(load_id: int, request: Request, current_user: models.User = Depends(get_current_user),
              db: Session = Depends(get_db)):
    load = _get_load_or_404(db, load_id)
    enforce_load_scope(load, current_user, request, db)
    pods = db.query(models.PODFile).filter(models.PODFile.load_id == load_id).all()
    return [{"id": p.id, "filename": p.filename, "uploaded_at": p.uploaded_at} for p in pods]
