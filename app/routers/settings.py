from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.auth import get_authenticated_account_id, require_auth
from app.schemas.settings import SecurityProfileResponse
from app.services.account_security_service import (
    get_available_mfa_methods_for_account,
    get_phone_number_hint_for_account,
    get_security_profile,
)

router = APIRouter(prefix="/settings", tags=["Settings"])


@router.get("/security-profile", response_model=SecurityProfileResponse)
def get_settings_security_profile(
    request: Request,
    _auth: tuple[str, int] = Depends(require_auth),
    db: Session = Depends(get_db),
) -> SecurityProfileResponse:
    try:
        account, profile = get_security_profile(
            db=db,
            user_account_id=get_authenticated_account_id(request),
            company_id=int(request.state.company_id),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    has_phone_number = bool(account.phone_number)
    available_mfa_methods = get_available_mfa_methods_for_account(account) if bool(account.mfa_enabled) else []
    preferred_mfa_method = (
        str(account.preferred_mfa_method)
        if bool(account.mfa_enabled) and str(account.preferred_mfa_method) in available_mfa_methods
        else None
    )

    return SecurityProfileResponse(
        user_account_id=account.user_account_id,
        company_id=int(account.company_id),
        company_name=str(profile.company_name),
        selected_tier=str(profile.selected_tier),
        role=str(account.role),
        username=str(account.username),
        email=str(account.email),
        email_verified=bool(account.email_verified),
        email_verified_at=account.email_verified_at,
        failed_login_attempt_count=int(account.failed_login_attempt_count or 0),
        lockout_until=account.lockout_until,
        password_changed_at=account.password_changed_at,
        phone_number_hint=get_phone_number_hint_for_account(account),
        has_phone_number=has_phone_number,
        phone_verified=bool(account.phone_verified),
        phone_verified_at=account.phone_verified_at,
        mfa_enabled=bool(account.mfa_enabled),
        sms_mfa_enabled=bool(account.sms_mfa_enabled),
        available_mfa_methods=available_mfa_methods,
        preferred_mfa_method=preferred_mfa_method,
    )
