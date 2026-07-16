from fastapi import Depends, HTTPException, status, Request
from sqlalchemy.orm import Session

from .database import get_db
from .auth import get_current_user
from . import models


def _log_denied(db: Session, request: Request, user: models.User | None, permission: str, reason: str):
    entry = models.PermissionDeniedLog(
        user_id=user.id if user else None,
        email=user.email if user else "anonymous",
        endpoint=str(request.url.path),
        permission_required=permission,
        reason=reason,
    )
    db.add(entry)
    db.commit()
    print(f"[PERMISSION DENIED] user={entry.email} endpoint={entry.endpoint} "
          f"perm={permission} reason={reason}")


def user_has_permission(user: models.User, permission: str) -> bool:
    """Pure check, reusable outside of the FastAPI dependency (e.g. for UI hints)."""
    if user.account_type == "shipper":
        return False  # shippers never hold catalog permissions
    if user.is_admin:
        return True  # org admins implicitly hold every permission within their org
    if user.role and permission in (user.role.permissions or []):
        return True
    return False


def require_permission(permission: str):
    """Dependency factory: blocks the request server-side unless the caller's
    role (or admin status) grants `permission`. This is enforced at the API
    layer, independent of anything the UI chooses to show/hide."""

    def dependency(
        request: Request,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> models.User:
        if not user_has_permission(current_user, permission):
            _log_denied(db, request, current_user, permission, "missing permission")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                 detail=f"Missing required permission: {permission}")
        return current_user

    return dependency


def require_account_type(*account_types: str):
    """Dependency factory: restricts endpoint to specific account types
    (broker / carrier / shipper) — used for org-scoping, not permission bundles."""

    def dependency(
        request: Request,
        current_user: models.User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> models.User:
        if current_user.account_type not in account_types:
            _log_denied(db, request, current_user, f"account_type in {account_types}", "wrong account type")
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                 detail="Not permitted for this account type")
        return current_user

    return dependency


def enforce_load_scope(load: models.Load, user: models.User, request: Request, db: Session):
    """Object-level scoping: shippers only see their own loads; carrier staff
    only see loads assigned to their own carrier org; broker staff only see
    loads belonging to their own broker org."""
    allowed = False
    if user.account_type == "shipper" and load.shipper_id == user.id:
        allowed = True
    elif user.account_type == "broker" and load.broker_org_id == user.org_id:
        allowed = True
    elif user.account_type == "carrier" and load.carrier_org_id == user.org_id:
        allowed = True

    if not allowed:
        _log_denied(db, request, user, "object-scope:load", "load not in caller's scope")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized for this load")
