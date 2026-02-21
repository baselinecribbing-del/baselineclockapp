from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import os
from app.services.auth_service import create_access_token

router = APIRouter(prefix="/auth", tags=["auth"])


class TokenRequest(BaseModel):
    user_id: str
    company_id: int


@router.post("/token")
def issue_token(payload: TokenRequest):
    env = os.getenv("ENV", "dev").lower()
    if env not in {"dev", "local", "test"}:
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        token = create_access_token(user_id=str(payload.user_id), company_id=int(payload.company_id))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "access_token": token,
        "token_type": "bearer",
    }
