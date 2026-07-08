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


def get_actor_user_id(request: Request) -> str:
    """Return the authenticated principal's user id.

    Prefers the value populated on ``request.state`` by ``require_auth``; falls
    back to decoding the bearer token directly so the helper is safe to call
    even when ``require_auth`` has not run earlier in the dependency chain.
    """
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return str(user_id)

    token = _parse_bearer_token(request)
    try:
        claims = verify_token(token)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return str(claims.get("sub"))


def get_authenticated_account_id(request: Request) -> str:
    """Return the authenticated account id.

    In the legacy JWT model the account principal is the token subject, so this
    resolves to the same identity as :func:`get_actor_user_id`.
    """
    return get_actor_user_id(request)
