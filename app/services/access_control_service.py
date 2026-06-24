from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from app.models.user_account import UserAccount


class AccessDomain(StrEnum):
    OPERATIONS = "operations"
    EMPLOYEE_SELF_SERVICE = "employee_self_service"


class PrivilegedPermission(StrEnum):
    SECURITY_POLICY_VIEW = "security.policy.view"
    SECURITY_POLICY_MANAGE = "security.policy.manage"
    SECURITY_AUDIT_VIEW = "security.audit.view"
    USERS_VIEW = "users.view"
    USERS_INVITE = "users.invite"
    USERS_MANAGE_ROLES = "users.manage_roles"
    USERS_DISABLE_ACCESS = "users.disable_access"
    EMPLOYEES_VIEW = "employees.view"
    EMPLOYEES_CREATE = "employees.create"
    EMPLOYEES_EDIT = "employees.edit"
    EMPLOYEES_TERMINATE = "employees.terminate"
    EMPLOYEES_PAYROLL_PRIVATE_VIEW = "employees.payroll_private.view"
    FIELD_VIEW = "field.view"
    FIELD_SCHEDULE_CREWS = "field.schedule_crews"
    FIELD_CLOCK_ENTRIES_VIEW = "field.clock_entries.view"
    FIELD_CLOCK_ENTRIES_REVIEW = "field.clock_entries.review"
    DISPATCH_VIEW = "dispatch.view"
    DISPATCH_MANAGE = "dispatch.manage"
    JOBS_VIEW = "jobs.view"
    JOBS_MANAGE = "jobs.manage"
    PAYROLL_VIEW = "payroll.view"
    PAYROLL_INPUTS_MANAGE = "payroll.inputs.manage"
    PAYROLL_RUNS_CREATE = "payroll.runs.create"
    PAYROLL_RUNS_REVIEW = "payroll.runs.review"
    PAYROLL_RUNS_FINALIZE = "payroll.runs.finalize"
    PAYROLL_RUNS_POST = "payroll.runs.post"
    PAYROLL_PAYSTUBS_GENERATE = "payroll.paystubs.generate"
    PAYROLL_PAYSTUBS_MARK_SENT = "payroll.paystubs.mark_sent"
    PAYROLL_T4_GENERATE = "payroll.t4.generate"
    PAYROLL_SOURCE_DEDUCTIONS_VIEW = "payroll.source_deductions.view"
    COSTING_VIEW = "costing.view"
    COSTING_MANAGE = "costing.manage"
    COSTING_ESTIMATES_MANAGE = "costing.estimates.manage"
    INVOICES_VIEW = "invoices.view"
    INVOICES_MANAGE = "invoices.manage"
    FINANCE_REPORTS_VIEW = "finance.reports.view"
    LEDGER_JOURNALS_POST = "ledger.journals.post"
    SELF_CLOCK = "self.clock"
    SELF_HOURS_VIEW = "self.hours.view"
    SELF_PAYSTUBS_VIEW = "self.paystubs.view"
    SELF_T4S_VIEW = "self.t4s.view"
    SELF_PROFILE_VIEW = "self.profile.view"
    SELF_PROFILE_EDIT_LIMITED = "self.profile.edit_limited"
    SELF_PIN_MANAGE = "self.pin.manage"


CANONICAL_ACCOUNT_ROLES = {
    "OWNER",
    "ACCOUNTANT",
    "ADMIN",
    "HR",
    "MANAGER",
    "ESTIMATOR",
    "EMPLOYEE_SELF_SERVICE",
}

LEGACY_ROLE_ALIASES = {
    "PAYROLL": "ACCOUNTANT",
    "DISPATCH": "MANAGER",
    "COSTING": "ESTIMATOR",
    "MEMBER": "MANAGER",
    "EMPLOYEE": "EMPLOYEE_SELF_SERVICE",
}

VALID_ACCOUNT_ROLES = CANONICAL_ACCOUNT_ROLES | set(LEGACY_ROLE_ALIASES)

BASE_PERMISSIONS_BY_ROLE: dict[str, set[PrivilegedPermission]] = {
    "OWNER": {
        permission for permission in PrivilegedPermission
    },
    "ACCOUNTANT": {
        PrivilegedPermission.PAYROLL_VIEW,
        PrivilegedPermission.PAYROLL_INPUTS_MANAGE,
        PrivilegedPermission.PAYROLL_RUNS_CREATE,
        PrivilegedPermission.PAYROLL_RUNS_REVIEW,
        PrivilegedPermission.PAYROLL_RUNS_FINALIZE,
        PrivilegedPermission.PAYROLL_RUNS_POST,
        PrivilegedPermission.PAYROLL_PAYSTUBS_GENERATE,
        PrivilegedPermission.PAYROLL_PAYSTUBS_MARK_SENT,
        PrivilegedPermission.PAYROLL_T4_GENERATE,
        PrivilegedPermission.PAYROLL_SOURCE_DEDUCTIONS_VIEW,
        PrivilegedPermission.COSTING_VIEW,
        PrivilegedPermission.COSTING_MANAGE,
        PrivilegedPermission.INVOICES_VIEW,
        PrivilegedPermission.INVOICES_MANAGE,
        PrivilegedPermission.FINANCE_REPORTS_VIEW,
        PrivilegedPermission.LEDGER_JOURNALS_POST,
        PrivilegedPermission.EMPLOYEES_VIEW,
        PrivilegedPermission.EMPLOYEES_PAYROLL_PRIVATE_VIEW,
        PrivilegedPermission.SECURITY_AUDIT_VIEW,
    },
    "ADMIN": {
        PrivilegedPermission.USERS_VIEW,
        PrivilegedPermission.USERS_INVITE,
        PrivilegedPermission.USERS_MANAGE_ROLES,
        PrivilegedPermission.USERS_DISABLE_ACCESS,
        PrivilegedPermission.EMPLOYEES_VIEW,
        PrivilegedPermission.EMPLOYEES_CREATE,
        PrivilegedPermission.EMPLOYEES_EDIT,
        PrivilegedPermission.EMPLOYEES_TERMINATE,
        PrivilegedPermission.EMPLOYEES_PAYROLL_PRIVATE_VIEW,
        PrivilegedPermission.FIELD_VIEW,
        PrivilegedPermission.FIELD_SCHEDULE_CREWS,
        PrivilegedPermission.FIELD_CLOCK_ENTRIES_VIEW,
        PrivilegedPermission.FIELD_CLOCK_ENTRIES_REVIEW,
        PrivilegedPermission.DISPATCH_VIEW,
        PrivilegedPermission.DISPATCH_MANAGE,
        PrivilegedPermission.JOBS_VIEW,
        PrivilegedPermission.JOBS_MANAGE,
        PrivilegedPermission.PAYROLL_VIEW,
        PrivilegedPermission.PAYROLL_INPUTS_MANAGE,
        PrivilegedPermission.PAYROLL_RUNS_CREATE,
        PrivilegedPermission.PAYROLL_RUNS_REVIEW,
        PrivilegedPermission.PAYROLL_PAYSTUBS_GENERATE,
        PrivilegedPermission.PAYROLL_T4_GENERATE,
        PrivilegedPermission.INVOICES_VIEW,
        PrivilegedPermission.SECURITY_AUDIT_VIEW,
    },
    "HR": {
        PrivilegedPermission.EMPLOYEES_VIEW,
        PrivilegedPermission.EMPLOYEES_CREATE,
        PrivilegedPermission.EMPLOYEES_EDIT,
        PrivilegedPermission.EMPLOYEES_TERMINATE,
        PrivilegedPermission.EMPLOYEES_PAYROLL_PRIVATE_VIEW,
        PrivilegedPermission.FIELD_CLOCK_ENTRIES_VIEW,
        PrivilegedPermission.FIELD_CLOCK_ENTRIES_REVIEW,
        PrivilegedPermission.PAYROLL_VIEW,
        PrivilegedPermission.PAYROLL_INPUTS_MANAGE,
        PrivilegedPermission.PAYROLL_RUNS_REVIEW,
        PrivilegedPermission.PAYROLL_PAYSTUBS_GENERATE,
        PrivilegedPermission.PAYROLL_T4_GENERATE,
        PrivilegedPermission.JOBS_VIEW,
    },
    "MANAGER": {
        PrivilegedPermission.FIELD_VIEW,
        PrivilegedPermission.FIELD_SCHEDULE_CREWS,
        PrivilegedPermission.FIELD_CLOCK_ENTRIES_VIEW,
        PrivilegedPermission.FIELD_CLOCK_ENTRIES_REVIEW,
        PrivilegedPermission.DISPATCH_VIEW,
        PrivilegedPermission.DISPATCH_MANAGE,
        PrivilegedPermission.JOBS_VIEW,
        PrivilegedPermission.JOBS_MANAGE,
        PrivilegedPermission.EMPLOYEES_VIEW,
    },
    "ESTIMATOR": {
        PrivilegedPermission.JOBS_VIEW,
        PrivilegedPermission.COSTING_VIEW,
        PrivilegedPermission.COSTING_MANAGE,
        PrivilegedPermission.COSTING_ESTIMATES_MANAGE,
    },
    "EMPLOYEE_SELF_SERVICE": {
        PrivilegedPermission.SELF_CLOCK,
        PrivilegedPermission.SELF_HOURS_VIEW,
        PrivilegedPermission.SELF_PAYSTUBS_VIEW,
        PrivilegedPermission.SELF_T4S_VIEW,
        PrivilegedPermission.SELF_PROFILE_VIEW,
        PrivilegedPermission.SELF_PROFILE_EDIT_LIMITED,
        PrivilegedPermission.SELF_PIN_MANAGE,
    },
}


@dataclass(frozen=True)
class SensitiveActionPolicy:
    action: str
    permission: PrivilegedPermission


SENSITIVE_ACTION_POLICIES: dict[str, SensitiveActionPolicy] = {
    "payroll.finalize": SensitiveActionPolicy(
        action="payroll.finalize",
        permission=PrivilegedPermission.PAYROLL_RUNS_FINALIZE,
    ),
    "payroll.supersede": SensitiveActionPolicy(
        action="payroll.supersede",
        permission=PrivilegedPermission.PAYROLL_RUNS_REVIEW,
    ),
    "payroll.post": SensitiveActionPolicy(
        action="payroll.post",
        permission=PrivilegedPermission.PAYROLL_RUNS_POST,
    ),
    "payroll.t4.generate": SensitiveActionPolicy(
        action="payroll.t4.generate",
        permission=PrivilegedPermission.PAYROLL_T4_GENERATE,
    ),
    "users.manage_roles": SensitiveActionPolicy(
        action="users.manage_roles",
        permission=PrivilegedPermission.USERS_MANAGE_ROLES,
    ),
    "security.policy.manage": SensitiveActionPolicy(
        action="security.policy.manage",
        permission=PrivilegedPermission.SECURITY_POLICY_MANAGE,
    ),
}


def normalize_account_role(role: str) -> str:
    normalized_role = str(role or "").strip().upper()
    if not normalized_role:
        raise ValueError("role is required")
    normalized_role = LEGACY_ROLE_ALIASES.get(normalized_role, normalized_role)
    if normalized_role not in CANONICAL_ACCOUNT_ROLES:
        raise ValueError("role is not supported")
    return normalized_role


def default_access_domains_for_role(role: str) -> tuple[bool, bool]:
    normalized_role = normalize_account_role(role)
    if normalized_role == "EMPLOYEE_SELF_SERVICE":
        return False, True
    return True, False


def _normalize_permission_values(permissions: Iterable[PrivilegedPermission | str]) -> set[str]:
    return {str(permission).strip() for permission in permissions if str(permission).strip()}


def get_effective_permissions_for_account(account: UserAccount) -> set[str]:
    role = normalize_account_role(str(account.role or ""))
    permissions: set[str] = set()
    if bool(account.can_access_operations):
        permissions.update(_normalize_permission_values(BASE_PERMISSIONS_BY_ROLE.get(role, set())))
    extras = account.granted_permissions or []
    permissions.update(_normalize_permission_values(extras))
    return permissions


def account_has_permission(account: UserAccount, permission: PrivilegedPermission | str) -> bool:
    return str(permission) in get_effective_permissions_for_account(account)
