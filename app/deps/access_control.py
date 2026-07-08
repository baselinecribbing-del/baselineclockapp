from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.auth import get_authenticated_account_id, get_actor_user_id, require_auth
from app.models.employee import Employee
from app.models.user_account import UserAccount
from app.services.access_control_service import (
    PrivilegedPermission,
    SensitiveActionPolicy,
    account_has_permission,
)
from app.services.account_security_service import create_user_account, get_account_for_company
from app.services.employee_pin_service import EmployeePinError, verify_employee_pin


@dataclass(frozen=True)
class AuthenticatedAccountContext:
    account: UserAccount
    linked_employee_id: int | None


def _dev_token_username(company_id: int, user_id: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "-" for ch in str(user_id or "").strip().lower()).strip("-")
    if not normalized:
        normalized = "dev-user"
    return f"dev-{int(company_id)}-{normalized}"[:128]


def _dev_token_email(company_id: int, user_id: str) -> str:
    normalized = "".join(ch if ch.isalnum() else "-" for ch in str(user_id or "").strip().lower()).strip("-")
    if not normalized:
        normalized = "dev-user"
    return f"{normalized}+{int(company_id)}@frontier.local"


def _ensure_dev_account_context(*, db: Session, company_id: int, actor_user_id: str) -> UserAccount:
    account_id = f"dev:{int(company_id)}:{str(actor_user_id)}"
    try:
        return get_account_for_company(db=db, user_account_id=account_id, company_id=company_id)
    except LookupError:
        create_user_account(
            db=db,
            user_account_id=account_id,
            company_id=int(company_id),
            username=_dev_token_username(company_id, actor_user_id),
            email=_dev_token_email(company_id, actor_user_id),
            password="DevTokenOnlyPass#1",
            email_verified=True,
            role="OWNER",
            can_access_operations=True,
            can_access_employee_self_service=False,
            granted_permissions=[],
            commit=True,
        )
        return get_account_for_company(db=db, user_account_id=account_id, company_id=company_id)


def _load_linked_employee(*, db: Session, account: UserAccount) -> Employee | None:
    if account.linked_employee_id is None:
        return None
    return (
        db.query(Employee)
        .filter(
            Employee.company_id == int(account.company_id),
            Employee.id == int(account.linked_employee_id),
        )
        .one_or_none()
    )


def require_authenticated_account_context(
    request: Request,
    _auth: tuple[str, int] = Depends(require_auth),
    db: Session = Depends(get_db),
) -> AuthenticatedAccountContext:
    try:
        account = get_account_for_company(
            db=db,
            user_account_id=get_authenticated_account_id(request),
            company_id=int(request.state.company_id),
        )
    except LookupError:
        env = os.getenv("ENV", "dev").lower()
        if env not in {"dev", "local", "test"}:
            raise
        account = _ensure_dev_account_context(
            db=db,
            company_id=int(request.state.company_id),
            actor_user_id=get_actor_user_id(request),
        )
    linked_employee = _load_linked_employee(db=db, account=account)
    if account.linked_employee_id is not None and linked_employee is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "linked_employee_not_found", "message": "Linked employee record is invalid."},
        )
    request.state.user_account = account
    request.state.linked_employee_id = None if linked_employee is None else int(linked_employee.id)
    return AuthenticatedAccountContext(
        account=account,
        linked_employee_id=None if linked_employee is None else int(linked_employee.id),
    )


def require_operations_access(
    context: AuthenticatedAccountContext = Depends(require_authenticated_account_context),
) -> AuthenticatedAccountContext:
    if not bool(context.account.can_access_operations):
        raise HTTPException(
            status_code=403,
            detail={"code": "operations_access_required", "message": "Operations platform access is required."},
        )
    return context


def require_operations_permission(permission: PrivilegedPermission | str):
    def dependency(
        context: AuthenticatedAccountContext = Depends(require_operations_access),
    ) -> AuthenticatedAccountContext:
        if not account_has_permission(context.account, permission):
            raise HTTPException(
                status_code=403,
                detail={"code": "permission_required", "message": f"Permission {permission} is required."},
            )
        return context

    return dependency


def _fresh_mfa_window() -> timedelta:
    raw_minutes = os.getenv("SENSITIVE_ACTION_MFA_MAX_AGE_MINUTES", "15").strip()
    try:
        minutes = int(raw_minutes)
    except ValueError as exc:
        raise RuntimeError("SENSITIVE_ACTION_MFA_MAX_AGE_MINUTES must be an integer") from exc
    if minutes <= 0:
        raise RuntimeError("SENSITIVE_ACTION_MFA_MAX_AGE_MINUTES must be positive")
    return timedelta(minutes=minutes)


def _parse_mfa_authenticated_at(request: Request) -> datetime | None:
    claims = getattr(request.state, "auth_claims", {}) or {}
    raw_value = claims.get("mfa_authenticated_at")
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_value))
    except ValueError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": "invalid_auth_token", "message": "Authentication token is invalid."},
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def require_fresh_mfa(action: SensitiveActionPolicy | str):
    policy = action if isinstance(action, SensitiveActionPolicy) else SensitiveActionPolicy(str(action), PrivilegedPermission(str(action)))

    def dependency(
        request: Request,
        context: AuthenticatedAccountContext = Depends(require_operations_permission(policy.permission)),
    ) -> AuthenticatedAccountContext:
        if not bool(context.account.mfa_enabled):
            return context
        authenticated_at = _parse_mfa_authenticated_at(request)
        if authenticated_at is None:
            raise HTTPException(
                status_code=403,
                detail={"code": "fresh_mfa_required", "message": f"Fresh MFA is required for {policy.action}."},
            )
        if authenticated_at < datetime.now(timezone.utc) - _fresh_mfa_window():
            raise HTTPException(
                status_code=403,
                detail={"code": "fresh_mfa_required", "message": f"Fresh MFA is required for {policy.action}."},
            )
        return context

    return dependency


def require_employee_self_service(
    context: AuthenticatedAccountContext = Depends(require_authenticated_account_context),
) -> AuthenticatedAccountContext:
    if not bool(context.account.can_access_employee_self_service) or context.linked_employee_id is None:
        raise HTTPException(
            status_code=403,
            detail={"code": "employee_self_service_required", "message": "Employee self-service access is required."},
        )
    return context


def require_self_employee_access(employee_id_param: str = "employee_id"):
    def dependency(
        request: Request,
        context: AuthenticatedAccountContext = Depends(require_employee_self_service),
    ) -> AuthenticatedAccountContext:
        raw_employee_id = request.path_params.get(employee_id_param)
        if raw_employee_id is None:
            raw_employee_id = request.query_params.get(employee_id_param)
        if raw_employee_id is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "employee_id_required", "message": f"{employee_id_param} is required."},
            )
        try:
            employee_id = int(raw_employee_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_employee_id", "message": f"{employee_id_param} must be an integer."},
            ) from exc
        if employee_id != int(context.linked_employee_id):
            raise HTTPException(
                status_code=403,
                detail={"code": "self_employee_access_required", "message": "Self employee access is required."},
            )
        return context

    return dependency


def require_employee_pin_verified(
    request: Request,
    context: AuthenticatedAccountContext = Depends(require_employee_self_service),
    db: Session = Depends(get_db),
) -> AuthenticatedAccountContext:
    pin = request.headers.get("X-Employee-Pin")
    if not pin:
        raise HTTPException(
            status_code=401,
            detail={"code": "employee_pin_required", "message": "X-Employee-Pin header is required."},
        )
    try:
        verify_employee_pin(
            db=db,
            user_account_id=str(context.account.user_account_id),
            company_id=int(context.account.company_id),
            pin=pin,
        )
    except EmployeePinError as exc:
        detail = {"code": exc.code, "message": exc.message}
        if exc.lockout_until is not None:
            detail["lockout_until"] = exc.lockout_until.isoformat()
        raise HTTPException(
            status_code=423 if exc.code == "employee_pin_locked" else 401,
            detail=detail,
        ) from exc
    return context
