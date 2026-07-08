from enum import Enum

from fastapi import Depends, HTTPException, Request

from app.deps.auth import _parse_bearer_token, require_auth
from app.services.auth_service import verify_token


class Role(Enum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    EMPLOYEE = "EMPLOYEE"


def require_role(role: Role):
    def dependency(request: Request, _auth: tuple[str, int] = Depends(require_auth)):
        token = _parse_bearer_token(request)
        try:
            claims = verify_token(token)
        except ValueError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

        claim_role = claims.get("role")
        if not claim_role:
            # Fail closed: a token that carries no role claim is never granted a
            # privileged default. All tokens minted by this system stamp a role.
            raise HTTPException(status_code=403, detail="Missing role claim")

        try:
            user_role = Role(str(claim_role).upper())
        except ValueError as exc:
            raise HTTPException(status_code=403, detail="Invalid role claim") from exc

        rank = {
            Role.EMPLOYEE: 1,
            Role.MANAGER: 2,
            Role.ADMIN: 3,
        }

        if rank[user_role] < rank[role]:
            raise HTTPException(status_code=403, detail="Insufficient role")

        request.state.role = user_role.value
        return user_role

    return dependency
