from typing import Tuple

from fastapi import HTTPException, Request

from app.services.auth_service import verify_token


def _parse_bearer_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    return parts[1].strip()


def require_auth(request: Request) -> Tuple[str, int]:
    token = _parse_bearer_token(request)

    try:
        claims = verify_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc

    user_id = str(claims.get("sub"))
    token_company_id = int(claims.get("company_id"))

    header_company_id = request.headers.get("X-Company-Id")
    if header_company_id is None:
        raise HTTPException(status_code=403, detail="Missing X-Company-Id header")

    try:
        header_company_id_int = int(header_company_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Invalid X-Company-Id header") from exc

    if header_company_id_int != token_company_id:
        raise HTTPException(status_code=403, detail="Company mismatch")

    request.state.user_id = user_id
    request.state.company_id = token_company_id

    return user_id, token_company_id
