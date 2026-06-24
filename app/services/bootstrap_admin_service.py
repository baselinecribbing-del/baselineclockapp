from __future__ import annotations

from dataclasses import dataclass
import logging
import os

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company_profile import CompanyProfile
from app.models.user_account import UserAccount
from app.services.account_security_service import create_user_account
from app.services.company_entitlements import SUPPORTED_MODULE_ORDER

logger = logging.getLogger(__name__)

SAFE_DEFAULT_ENVS = {"dev", "local"}
PRODUCTION_ENVS = {"prod", "production"}


@dataclass(frozen=True)
class BootstrapAdminConfig:
    company_id: int
    username: str
    email: str
    password: str


@dataclass(frozen=True)
class BootstrapAdminResult:
    status: str
    company_id: int | None = None
    username: str | None = None
    email: str | None = None
    password: str | None = None
    profile_created: bool = False
    account_created: bool = False
    reason: str | None = None


def _current_env() -> str:
    return str(os.getenv("ENV", "dev")).strip().lower() or "dev"


def _env_flag(name: str) -> bool:
    return str(os.getenv(name, "0")).strip().lower() in {"1", "true", "yes", "on"}


def _is_production_env(env: str) -> bool:
    return env in PRODUCTION_ENVS


def _is_bootstrap_allowed(env: str) -> bool:
    if _is_production_env(env):
        return False
    if env in SAFE_DEFAULT_ENVS:
        return True
    return _env_flag("BOOTSTRAP_ADMIN_ENABLED")


def _safe_default_value(env: str, env_name: str, default: str) -> str | None:
    configured = str(os.getenv(env_name, "")).strip()
    if configured:
        return configured
    if env in SAFE_DEFAULT_ENVS:
        return default
    return None


def _resolve_company_id(env: str) -> int | None:
    raw = _safe_default_value(env, "BOOTSTRAP_COMPANY_ID", "1")
    if raw is None:
        return None
    try:
        company_id = int(raw)
    except ValueError:
        raise ValueError("BOOTSTRAP_COMPANY_ID must be an integer") from None
    if company_id <= 0:
        raise ValueError("BOOTSTRAP_COMPANY_ID must be positive")
    return company_id


def get_bootstrap_admin_config() -> BootstrapAdminConfig | None:
    env = _current_env()
    if not _is_bootstrap_allowed(env):
        return None

    company_id = _resolve_company_id(env)
    username = _safe_default_value(env, "BOOTSTRAP_ADMIN_USERNAME", "owner")
    email = _safe_default_value(env, "BOOTSTRAP_ADMIN_EMAIL", "owner@frontier.local")
    password = _safe_default_value(env, "BOOTSTRAP_ADMIN_PASSWORD", "ChangeMeDev#1")

    if company_id is None or username is None or email is None or password is None:
        return None

    return BootstrapAdminConfig(
        company_id=company_id,
        username=username,
        email=email,
        password=password,
    )


def ensure_bootstrap_company_profile(*, db: Session, company_id: int) -> bool:
    row = db.query(CompanyProfile).filter(CompanyProfile.company_id == int(company_id)).one_or_none()
    if row is not None:
        return False

    db.add(
        CompanyProfile(
            company_id=int(company_id),
            company_name=f"Frontier Dev Company {company_id}",
            primary_trade="Foundations",
            country="CA",
            province_or_state="AB",
            selected_tier="tier_3_full_system",
            enabled_modules=list(SUPPORTED_MODULE_ORDER),
            onboarding_completed=True,
        )
    )
    db.flush()
    return True


def bootstrap_owner_admin_account() -> BootstrapAdminResult:
    env = _current_env()
    if not _is_bootstrap_allowed(env):
        return BootstrapAdminResult(status="skipped", reason="bootstrap_not_allowed", company_id=None)

    config = get_bootstrap_admin_config()
    if config is None:
        return BootstrapAdminResult(status="skipped", reason="bootstrap_not_configured", company_id=None)

    db = SessionLocal()
    try:
        existing_account = db.query(UserAccount.user_account_id).first()
        if existing_account is not None:
            return BootstrapAdminResult(
                status="skipped",
                reason="existing_user_accounts_present",
                company_id=config.company_id,
                username=config.username,
                email=config.email,
            )

        profile_created = ensure_bootstrap_company_profile(db=db, company_id=config.company_id)
        account = create_user_account(
            db=db,
            company_id=config.company_id,
            username=config.username,
            email=config.email,
            password=config.password,
            email_verified=True,
            role="OWNER",
            commit=False,
        )
        db.commit()
        db.refresh(account)
        return BootstrapAdminResult(
            status="created",
            company_id=config.company_id,
            username=account.username,
            email=account.email,
            password=config.password,
            profile_created=profile_created,
            account_created=True,
        )
    finally:
        db.close()


def log_bootstrap_owner_admin_result(result: BootstrapAdminResult) -> None:
    env = _current_env()
    if result.status == "created":
        logger.info(
            "Bootstrap owner account created for company_id=%s username=%s email=%s env=%s",
            result.company_id,
            result.username,
            result.email,
            env,
        )
        return

    if result.reason not in {"bootstrap_not_allowed", "bootstrap_not_configured", "existing_user_accounts_present"}:
        logger.info("Bootstrap owner account skipped: %s", result.reason)
