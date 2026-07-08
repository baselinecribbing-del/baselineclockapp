from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.auth import require_auth
from app.models.company_profile import CompanyProfile
from app.schemas.company import CompanyModuleCode
from app.services.company_entitlements import ResolvedCompanyEntitlements, resolve_company_entitlements


@dataclass(frozen=True)
class CompanyAccessContext:
    company_id: int
    profile: CompanyProfile
    entitlements: ResolvedCompanyEntitlements


def _forbidden(*, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=403, detail={"code": code, "message": message})


def get_company_access_context(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth: tuple[str, int] = Depends(require_auth),
    db: Session = Depends(get_db),
) -> CompanyAccessContext:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")

    company_id = int(request.state.company_id)
    profile = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).one_or_none()
    if profile is None:
        raise _forbidden(
            code="company_profile_required",
            message="Company onboarding must be completed before accessing this route.",
        )

    try:
        entitlements = resolve_company_entitlements(
            selected_tier=profile.selected_tier,
            enabled_modules=list(profile.enabled_modules or []),
        )
    except ValueError as exc:
        raise _forbidden(
            code="entitlements_unavailable",
            message="Access is not available for the current subscription.",
        ) from exc

    context = CompanyAccessContext(
        company_id=company_id,
        profile=profile,
        entitlements=entitlements,
    )
    request.state.company_access_context = context
    return context


def require_company_module(module_code: CompanyModuleCode):
    def dependency(context: CompanyAccessContext = Depends(get_company_access_context)) -> CompanyAccessContext:
        if module_code not in set(context.entitlements.enabled_modules):
            raise _forbidden(
                code="module_not_enabled",
                message="Access to this module is not available for the current subscription.",
            )
        return context

    return dependency


def require_company_capability(capability_code: str):
    def dependency(context: CompanyAccessContext = Depends(get_company_access_context)) -> CompanyAccessContext:
        if capability_code not in set(context.entitlements.entitled_capabilities):
            raise _forbidden(
                code="capability_not_enabled",
                message="Access to this capability is not available for the current subscription.",
            )
        return context

    return dependency
