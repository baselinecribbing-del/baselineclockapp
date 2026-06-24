from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.auth import require_auth
from app.models.company_profile import CompanyProfile
from app.schemas.company import CompanyEntitlementsResponse, CompanyProfileResponse, CompanyProfileUpsert
from app.services.company_entitlements import resolve_company_entitlements

router = APIRouter(prefix="/company", tags=["Company"])


def _ensure_company(request: Request, x_company_id: int) -> int:
    if int(x_company_id) != int(request.state.company_id):
        raise HTTPException(status_code=403, detail="Company mismatch")
    return int(request.state.company_id)


def _get_company_profile_or_404(db: Session, company_id: int) -> CompanyProfile:
    row = db.query(CompanyProfile).filter(CompanyProfile.company_id == int(company_id)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Company profile not found")
    return row


def _serialize_company_profile(row: CompanyProfile) -> CompanyProfileResponse:
    return CompanyProfileResponse(
        company_id=int(row.company_id),
        company_name=str(row.company_name),
        primary_trade=str(row.primary_trade),
        country=str(row.country),
        province_or_state=str(row.province_or_state),
        selected_tier=str(row.selected_tier),
        enabled_modules=list(row.enabled_modules or []),
        onboarding_completed=bool(row.onboarding_completed),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


@router.get("/profile", response_model=CompanyProfileResponse)
def get_company_profile(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth=Depends(require_auth),
    db: Session = Depends(get_db),
) -> CompanyProfileResponse:
    company_id = _ensure_company(request, x_company_id)
    row = _get_company_profile_or_404(db, company_id)
    return _serialize_company_profile(row)


@router.put("/profile", response_model=CompanyProfileResponse)
def upsert_company_profile(
    payload: CompanyProfileUpsert,
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth=Depends(require_auth),
    db: Session = Depends(get_db),
) -> CompanyProfileResponse:
    company_id = _ensure_company(request, x_company_id)
    try:
        entitlements = resolve_company_entitlements(
            selected_tier=payload.selected_tier,
            enabled_modules=payload.enabled_modules,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    row = db.query(CompanyProfile).filter(CompanyProfile.company_id == company_id).one_or_none()
    if row is None:
        row = CompanyProfile(company_id=company_id)
        db.add(row)

    row.company_name = payload.company_name
    row.primary_trade = payload.primary_trade
    row.country = payload.country
    row.province_or_state = payload.province_or_state
    row.selected_tier = payload.selected_tier
    row.enabled_modules = list(entitlements.enabled_modules)
    row.onboarding_completed = payload.onboarding_completed

    db.commit()
    db.refresh(row)

    return _serialize_company_profile(row)


@router.get("/entitlements", response_model=CompanyEntitlementsResponse)
def get_company_entitlements(
    request: Request,
    x_company_id: int = Header(..., alias="X-Company-Id"),
    _auth=Depends(require_auth),
    db: Session = Depends(get_db),
) -> CompanyEntitlementsResponse:
    company_id = _ensure_company(request, x_company_id)
    row = _get_company_profile_or_404(db, company_id)
    entitlements = resolve_company_entitlements(
        selected_tier=row.selected_tier,
        enabled_modules=list(row.enabled_modules or []),
    )
    return CompanyEntitlementsResponse(
        company_id=company_id,
        selected_tier=entitlements.selected_tier,
        entitled_modules=entitlements.entitled_modules,
        enabled_modules=entitlements.enabled_modules,
        entitled_capabilities=entitlements.entitled_capabilities,
        onboarding_completed=bool(row.onboarding_completed),
    )
