from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import os
from app.services.auth_service import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    user_id: str
    company_id: int
    role: str = "MANAGER"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.post("/token", response_model=TokenResponse)
def issue_token(payload: TokenRequest) -> TokenResponse:
    env = os.getenv("ENV", "dev").lower()
    if env not in {"dev", "local", "test"}:
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        token = create_access_token(
            user_id=str(payload.user_id),
            company_id=int(payload.company_id),
            role=str(payload.role or "MANAGER"),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return TokenResponse(access_token=token)
