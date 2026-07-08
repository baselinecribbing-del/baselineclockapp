from datetime import datetime, timedelta, timezone
import os

import jwt
from sqlalchemy.orm import Session

JWT_ALGORITHM = "HS256"
JWT_EXP_HOURS = 8


def _get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise ValueError("JWT_SECRET is required")
    if len(secret) < 32:
        raise ValueError("JWT_SECRET must be at least 32 characters")
    return secret


def create_access_token(
    user_id: str,
    company_id: int,
    role: str = "MANAGER",
    *,
    mfa_authenticated: bool = False,
    mfa_authenticated_at=None,
) -> str:
    """Mint a signed access token.

    A ``role`` claim is always stamped (default MANAGER, preserving the prior
    implicit behaviour) so the legacy role ladder is meaningful and
    ``require_role`` can fail closed on tokens that carry no role. Optional MFA
    claims support sensitive-action freshness checks.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "company_id": int(company_id),
        "role": str(role),
        "exp": now + timedelta(hours=JWT_EXP_HOURS),
    }
    if mfa_authenticated:
        payload["mfa_authenticated"] = True
    if mfa_authenticated_at is not None:
        payload["mfa_authenticated_at"] = (
            mfa_authenticated_at.isoformat()
            if hasattr(mfa_authenticated_at, "isoformat")
            else str(mfa_authenticated_at)
        )
    return jwt.encode(payload, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except Exception as exc:
        raise ValueError("Invalid or expired token") from exc

    if "sub" not in payload or "company_id" not in payload:
        raise ValueError("Invalid token claims")

    return payload


def revoke_refresh_tokens_for_user(*, db: Session, user_id: str, company_id: int) -> int:
    """Revoke all currently-active refresh tokens for a user within a company.

    Marks every non-revoked ``user_refresh_tokens`` row for ``(user_id,
    company_id)`` as revoked (sets ``revoked_at``). Used when a PIN is set/reset
    to invalidate existing sessions. Returns the number of tokens revoked.
    """
    # Deferred import keeps this low-level auth module free of model/import cycles.
    from app.models.user_refresh_token import UserRefreshToken

    revoked_count = (
        db.query(UserRefreshToken)
        .filter(
            UserRefreshToken.user_account_id == str(user_id),
            UserRefreshToken.company_id == int(company_id),
            UserRefreshToken.revoked_at.is_(None),
        )
        .update({"revoked_at": datetime.now(timezone.utc)}, synchronize_session=False)
    )
    return int(revoked_count or 0)
