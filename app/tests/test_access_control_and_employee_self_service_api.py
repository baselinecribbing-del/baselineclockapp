from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.company_profile import CompanyProfile
from app.models.employee import Employee
from app.models.job import Job
from app.models.pay_period import PayPeriod
from app.models.payroll_item import PayrollItem
from app.models.payroll_run import PayrollRun
from app.models.paystub import Paystub
from app.models.scope import Scope
from app.models.time_entry import TimeEntry
from app.models.user_account import UserAccount
from app.services.account_security_service import create_user_account
from app.services.auth_service import create_access_token

client = TestClient(app)


def _save_company_profile(company_id: int, modules: list[str] | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(
            CompanyProfile(
                company_id=int(company_id),
                company_name=f"Company {company_id}",
                primary_trade="Foundations",
                country="CA",
                province_or_state="AB",
                selected_tier="tier_3_full_system",
                enabled_modules=list(modules or ["jobs", "field", "payroll"]),
                onboarding_completed=True,
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_employee(company_id: int, name: str, email: str | None = None) -> Employee:
    db = SessionLocal()
    try:
        employee = Employee(
            company_id=int(company_id),
            name=name,
            legal_name=name,
            email=email,
            is_active=True,
            employment_status="ACTIVE",
            hourly_rate_cents=3000,
        )
        db.add(employee)
        db.commit()
        db.refresh(employee)
        return employee
    finally:
        db.close()


def _seed_job_scope(company_id: int, suffix: str) -> tuple[int, int]:
    db = SessionLocal()
    try:
        job = Job(company_id=int(company_id), name=f"Job {suffix}", address_label=f"{suffix} Main", is_active=True)
        db.add(job)
        db.flush()
        scope = Scope(company_id=int(company_id), job_id=int(job.id), name=f"Scope {suffix}", is_active=True)
        db.add(scope)
        db.commit()
        db.refresh(job)
        db.refresh(scope)
        return int(job.id), int(scope.id)
    finally:
        db.close()


def _create_account(
    *,
    company_id: int,
    username: str,
    email: str,
    password: str,
    role: str,
    linked_employee_id: int | None = None,
    granted_permissions: list[str] | None = None,
    can_access_operations: bool | None = None,
    can_access_employee_self_service: bool | None = None,
) -> UserAccount:
    db = SessionLocal()
    try:
        account = create_user_account(
            db=db,
            company_id=int(company_id),
            username=username,
            email=email,
            password=password,
            role=role,
            linked_employee_id=linked_employee_id,
            granted_permissions=granted_permissions,
            can_access_operations=can_access_operations,
            can_access_employee_self_service=can_access_employee_self_service,
        )
        return account
    finally:
        db.close()


def _login_headers(username: str, password: str, company_id: int) -> dict[str, str]:
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}", "X-Company-Id": str(company_id)}


def _set_pin(headers: dict[str, str], pin: str) -> None:
    response = client.post("/employee-self-service/pin/set", headers=headers, json={"new_pin": pin})
    assert response.status_code == 200, response.text


def test_employee_self_service_user_cannot_access_operations_routes():
    company_id = 67101
    _save_company_profile(company_id)
    employee = _seed_employee(company_id, "Field Worker", "field.worker@example.com")
    _create_account(
        company_id=company_id,
        username="field-worker",
        email="field-worker@example.com",
        password="FieldWorkerPass#1",
        role="EMPLOYEE_SELF_SERVICE",
        linked_employee_id=employee.id,
    )

    headers = _login_headers("field-worker", "FieldWorkerPass#1", company_id)

    command_center = client.get("/command-center/overview", headers=headers)
    assert command_center.status_code == 403
    assert command_center.json()["detail"]["code"] == "operations_access_required"

    payroll_runs = client.get("/payroll/runs", headers=headers)
    assert payroll_runs.status_code == 403
    assert payroll_runs.json()["detail"]["code"] == "operations_access_required"


def test_privileged_user_can_access_operations_route():
    company_id = 67102
    _save_company_profile(company_id)
    _create_account(
        company_id=company_id,
        username="ops-owner",
        email="ops-owner@example.com",
        password="OpsOwnerPass#1",
        role="OWNER",
    )

    headers = _login_headers("ops-owner", "OpsOwnerPass#1", company_id)
    response = client.get("/payroll/runs", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["rows"] == []


def test_privileged_permissions_allow_accountant_and_block_hr_finalize():
    company_id = 67103
    _save_company_profile(company_id, modules=["payroll"])
    today = date.today()

    db = SessionLocal()
    try:
        employee = _seed_employee(company_id, "Finalize Worker", "finalize.worker@example.com")
        pay_period = PayPeriod(
            pay_period_id=f"pp-{company_id}",
            company_id=company_id,
            start_date=today - timedelta(days=7),
            end_date=today,
            status="OPEN",
        )
        payroll_run = PayrollRun(
            payroll_run_id=f"pr-{company_id}",
            company_id=company_id,
            pay_period_id=pay_period.pay_period_id,
            status="DRAFT",
        )
        db.add(pay_period)
        db.add(payroll_run)
        db.flush()
        db.add(
            PayrollItem(
                company_id=company_id,
                payroll_run_id=payroll_run.payroll_run_id,
                employee_id=employee.id,
                hours=2,
                rate_cents=3000,
                gross_pay_cents=6000,
                meta={"job_id": 1},
            )
        )
        db.commit()
    finally:
        db.close()

    _create_account(
        company_id=company_id,
        username="hr-user",
        email="hr-user@example.com",
        password="HrUserPass#1",
        role="HR",
    )
    _create_account(
        company_id=company_id,
        username="payroll-user",
        email="payroll-user@example.com",
        password="PayrollUserPass#1",
        role="ACCOUNTANT",
    )

    hr_headers = _login_headers("hr-user", "HrUserPass#1", company_id)
    payroll_headers = _login_headers("payroll-user", "PayrollUserPass#1", company_id)

    hr_finalize = client.post(f"/payroll/runs/pr-{company_id}/finalize", headers=hr_headers)
    assert hr_finalize.status_code == 403
    assert hr_finalize.json()["detail"]["code"] == "permission_required"

    payroll_finalize = client.post(f"/payroll/runs/pr-{company_id}/finalize", headers=payroll_headers)
    assert payroll_finalize.status_code == 200, payroll_finalize.text
    assert payroll_finalize.json()["status"] == "FINALIZED"


def test_employee_pin_set_verify_change_and_reset_flow():
    company_id = 67104
    _save_company_profile(company_id)
    employee = _seed_employee(company_id, "Pin Worker", "pin.worker@example.com")
    _create_account(
        company_id=company_id,
        username="pin-worker",
        email="pin-worker@example.com",
        password="PinWorkerPass#1",
        role="EMPLOYEE_SELF_SERVICE",
        linked_employee_id=employee.id,
    )

    login = client.post("/auth/login", json={"username": "pin-worker", "password": "PinWorkerPass#1"})
    assert login.status_code == 200, login.text
    body = login.json()
    headers = {"Authorization": f"Bearer {body['access_token']}", "X-Company-Id": str(company_id)}

    set_response = client.post("/employee-self-service/pin/set", headers=headers, json={"new_pin": "1234"})
    assert set_response.status_code == 200, set_response.text

    verify_response = client.post("/employee-self-service/pin/verify", headers=headers, json={"pin": "1234"})
    assert verify_response.status_code == 200, verify_response.text
    assert verify_response.json()["status"] == "employee_pin_verified"

    refresh_after_set = client.post("/auth/refresh", json={"refresh_token": body["refresh_token"]})
    assert refresh_after_set.status_code == 401
    assert refresh_after_set.json()["detail"]["code"] == "invalid_refresh_token"

    relogin_headers = _login_headers("pin-worker", "PinWorkerPass#1", company_id)
    change_response = client.post(
        "/employee-self-service/pin/change",
        headers=relogin_headers,
        json={"current_pin": "1234", "new_pin": "2345"},
    )
    assert change_response.status_code == 200, change_response.text

    old_pin = client.post("/employee-self-service/pin/verify", headers=relogin_headers, json={"pin": "1234"})
    assert old_pin.status_code == 400
    assert old_pin.json()["detail"]["code"] == "invalid_employee_pin"

    reset_response = client.post(
        "/employee-self-service/pin/reset",
        headers=relogin_headers,
        json={"current_password": "PinWorkerPass#1", "new_pin": "3456"},
    )
    assert reset_response.status_code == 200, reset_response.text

    new_pin = client.post("/employee-self-service/pin/verify", headers=relogin_headers, json={"pin": "3456"})
    assert new_pin.status_code == 200, new_pin.text


def test_employee_pin_lockout_is_enforced_and_self_service_scope_is_preserved():
    company_id = 67105
    other_company_id = 67106
    _save_company_profile(company_id)
    _save_company_profile(other_company_id)
    employee = _seed_employee(company_id, "Scoped Worker", "scoped.worker@example.com")
    other_employee = _seed_employee(company_id, "Other Worker", "other.worker@example.com")
    _seed_employee(other_company_id, "Foreign Worker", "foreign.worker@example.com")
    job_id, scope_id = _seed_job_scope(company_id, "SELF")

    account = _create_account(
        company_id=company_id,
        username="scoped-worker",
        email="scoped-worker@example.com",
        password="ScopedWorkerPass#1",
        role="EMPLOYEE_SELF_SERVICE",
        linked_employee_id=employee.id,
    )
    headers = _login_headers("scoped-worker", "ScopedWorkerPass#1", company_id)
    _set_pin(headers, "1234")

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        db.add(
            TimeEntry(
                time_entry_id="te-self-owned",
                company_id=company_id,
                employee_id=employee.id,
                job_id=job_id,
                scope_id=scope_id,
                started_at=now - timedelta(hours=8),
                ended_at=now - timedelta(hours=1),
                status="completed",
                approval_status="approved",
            )
        )
        db.add(
            TimeEntry(
                time_entry_id="te-self-other",
                company_id=company_id,
                employee_id=other_employee.id,
                job_id=job_id,
                scope_id=scope_id,
                started_at=now - timedelta(hours=6),
                ended_at=now - timedelta(hours=2),
                status="completed",
                approval_status="approved",
            )
        )
        pay_period = PayPeriod(
            pay_period_id="pp-self-service",
            company_id=company_id,
            start_date=date.today() - timedelta(days=14),
            end_date=date.today() - timedelta(days=7),
            status="CLOSED",
        )
        payroll_run = PayrollRun(
            payroll_run_id="pr-self-service",
            company_id=company_id,
            pay_period_id=pay_period.pay_period_id,
            status="POSTED",
            posted_at=now - timedelta(days=6),
        )
        db.add(pay_period)
        db.add(payroll_run)
        db.flush()
        db.add(
            Paystub(
                paystub_id="ps-self-owned",
                company_id=company_id,
                payroll_run_id=payroll_run.payroll_run_id,
                employee_id=employee.id,
                gross_pay_cents=10000,
                total_deductions_cents=1500,
                net_pay_cents=8500,
                delivery_status="SENT",
                sent_at=now - timedelta(days=5),
                sent_by_user_id=account.user_account_id,
            )
        )
        db.add(
            Paystub(
                paystub_id="ps-self-other",
                company_id=company_id,
                payroll_run_id=payroll_run.payroll_run_id,
                employee_id=other_employee.id,
                gross_pay_cents=12000,
                total_deductions_cents=1800,
                net_pay_cents=10200,
                delivery_status="PENDING",
            )
        )
        db.commit()
    finally:
        db.close()

    wrong_pin_headers = dict(headers)
    wrong_pin_headers["X-Employee-Pin"] = "9999"
    for _ in range(5):
        attempt = client.get(f"/employee-self-service/employees/{employee.id}/dashboard", headers=wrong_pin_headers)
        assert attempt.status_code in {401, 423}
    locked = client.get(f"/employee-self-service/employees/{employee.id}/dashboard", headers=wrong_pin_headers)
    assert locked.status_code == 423
    assert locked.json()["detail"]["code"] == "employee_pin_locked"

    db = SessionLocal()
    try:
        refreshed = db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).one()
        refreshed.employee_pin_lockout_until = datetime.now(timezone.utc) - timedelta(minutes=1)
        refreshed.employee_pin_failed_attempt_count = 0
        db.add(refreshed)
        db.commit()
    finally:
        db.close()

    scoped_headers = dict(headers)
    scoped_headers["X-Employee-Pin"] = "1234"

    own_profile = client.get(f"/employee-self-service/employees/{employee.id}/profile", headers=headers)
    assert own_profile.status_code == 200, own_profile.text
    assert own_profile.json()["employee_id"] == employee.id

    other_profile = client.get(f"/employee-self-service/employees/{other_employee.id}/profile", headers=headers)
    assert other_profile.status_code == 403
    assert other_profile.json()["detail"]["code"] == "self_employee_access_required"

    own_time_entries = client.get(
        f"/employee-self-service/employees/{employee.id}/time-entries",
        headers=scoped_headers,
    )
    assert own_time_entries.status_code == 200, own_time_entries.text
    assert [row["time_entry_id"] for row in own_time_entries.json()["rows"]] == ["te-self-owned"]

    own_paystubs = client.get(
        f"/employee-self-service/employees/{employee.id}/paystubs",
        headers=scoped_headers,
    )
    assert own_paystubs.status_code == 200, own_paystubs.text
    assert [row["paystub_id"] for row in own_paystubs.json()["rows"]] == ["ps-self-owned"]

    own_t4s = client.get(
        f"/employee-self-service/employees/{employee.id}/t4s",
        headers=scoped_headers,
    )
    assert own_t4s.status_code == 200, own_t4s.text
    assert own_t4s.json()["rows"] == []

    other_t4s = client.get(
        f"/employee-self-service/employees/{other_employee.id}/t4s",
        headers=scoped_headers,
    )
    assert other_t4s.status_code == 403
    assert other_t4s.json()["detail"]["code"] == "self_employee_access_required"


def test_employee_self_service_t4s_require_self_service_account():
    company_id = 67110
    _save_company_profile(company_id, modules=["payroll"])
    employee = _seed_employee(company_id, "Payroll Viewer", "payroll.viewer@example.com")
    _create_account(
        company_id=company_id,
        username="ops-payroll-user",
        email="ops-payroll-user@example.com",
        password="OpsPayrollPass#1",
        role="ACCOUNTANT",
    )

    headers = _login_headers("ops-payroll-user", "OpsPayrollPass#1", company_id)
    headers["X-Employee-Pin"] = "1234"

    response = client.get(f"/employee-self-service/employees/{employee.id}/t4s", headers=headers)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "employee_self_service_required"


def test_employee_self_service_t4s_preserve_company_isolation():
    company_id = 67111
    other_company_id = 67112
    _save_company_profile(company_id, modules=["payroll"])
    _save_company_profile(other_company_id, modules=["payroll"])
    employee = _seed_employee(company_id, "Company Worker", "company.worker@example.com")
    foreign_employee = _seed_employee(other_company_id, "Foreign Worker", "foreign.t4@example.com")
    _create_account(
        company_id=company_id,
        username="company-worker",
        email="company-worker@example.com",
        password="CompanyWorkerPass#1",
        role="EMPLOYEE_SELF_SERVICE",
        linked_employee_id=employee.id,
    )
    _create_account(
        company_id=other_company_id,
        username="foreign-worker",
        email="foreign-worker@example.com",
        password="ForeignWorkerPass#1",
        role="EMPLOYEE_SELF_SERVICE",
        linked_employee_id=foreign_employee.id,
    )

    own_headers = _login_headers("company-worker", "CompanyWorkerPass#1", company_id)
    _set_pin(own_headers, "1234")
    own_headers["X-Employee-Pin"] = "1234"

    foreign_headers = _login_headers("foreign-worker", "ForeignWorkerPass#1", other_company_id)
    _set_pin(foreign_headers, "5678")
    foreign_headers["X-Employee-Pin"] = "5678"

    own_response = client.get(f"/employee-self-service/employees/{employee.id}/t4s", headers=own_headers)
    assert own_response.status_code == 200, own_response.text
    assert own_response.json()["rows"] == []

    cross_company_response = client.get(
        f"/employee-self-service/employees/{employee.id}/t4s",
        headers=foreign_headers,
    )
    assert cross_company_response.status_code == 403
    assert cross_company_response.json()["detail"]["code"] == "self_employee_access_required"


def test_canonical_role_permission_matrix_across_representative_routes():
    company_id = 67107
    _save_company_profile(company_id, modules=["jobs", "field", "payroll", "costing", "invoices", "dispatch"])
    employee = _seed_employee(company_id, "ESS Worker", "ess.worker@example.com")

    role_configs = {
        "OWNER": {"employees": 200, "field": 200, "jobs": 200, "payroll": 200, "costing": 200, "invoices": 200, "invite": 202},
        "ACCOUNTANT": {"employees": 200, "field": 403, "jobs": 403, "payroll": 200, "costing": 200, "invoices": 200, "invite": 403},
        "ADMIN": {"employees": 200, "field": 200, "jobs": 200, "payroll": 200, "costing": 403, "invoices": 200, "invite": 202},
        "HR": {"employees": 200, "field": 403, "jobs": 403, "payroll": 200, "costing": 403, "invoices": 403, "invite": 403},
        "MANAGER": {"employees": 403, "field": 200, "jobs": 200, "payroll": 403, "costing": 403, "invoices": 403, "invite": 403},
        "ESTIMATOR": {"employees": 403, "field": 403, "jobs": 403, "payroll": 403, "costing": 200, "invoices": 403, "invite": 403},
        "EMPLOYEE_SELF_SERVICE": {"employees": 403, "field": 403, "jobs": 403, "payroll": 403, "costing": 403, "invoices": 403, "invite": 403},
    }

    for index, (role, expected) in enumerate(role_configs.items(), start=1):
        username = f"matrix-{role.lower()}-{company_id}"
        account_kwargs = {"linked_employee_id": employee.id} if role == "EMPLOYEE_SELF_SERVICE" else {}
        _create_account(
            company_id=company_id,
            username=username,
            email=f"{username}@example.com",
            password="MatrixPass#1",
            role=role,
            **account_kwargs,
        )
        headers = _login_headers(username, "MatrixPass#1", company_id)

        employees = client.get("/employees", headers=headers)
        assert employees.status_code == expected["employees"], (role, employees.text)

        field = client.get("/field/crew-board", headers=headers)
        assert field.status_code == expected["field"], (role, field.text)

        jobs = client.post(
            "/jobs",
            headers=headers,
            json={"name": f"Matrix Job {role}", "address_label": f"{index} Test Ave"},
        )
        assert jobs.status_code == expected["jobs"], (role, jobs.text)

        payroll = client.get("/payroll/runs", headers=headers)
        assert payroll.status_code == expected["payroll"], (role, payroll.text)

        costing = client.get(
            "/costing/ledger/totals",
            headers=headers,
            params={"date_start": "2026-01-01T00:00:00Z", "date_end": "2026-01-02T00:00:00Z"},
        )
        assert costing.status_code == expected["costing"], (role, costing.text)

        invoices = client.get("/invoices", headers=headers)
        assert invoices.status_code == expected["invoices"], (role, invoices.text)

        invite = client.post(
            "/auth/invite-user",
            headers=headers,
            json={"email": f"invite-{role.lower()}-{company_id}@example.com", "role": "MANAGER"},
        )
        assert invite.status_code == expected["invite"], (role, invite.text)


def test_permission_overrides_grant_explicit_access_without_bypassing_access_domains():
    company_id = 67108
    _save_company_profile(company_id, modules=["jobs", "field", "payroll", "costing", "invoices"])
    employee = _seed_employee(company_id, "Override Worker", "override.worker@example.com")

    _create_account(
        company_id=company_id,
        username="estimator-no-override",
        email="estimator-no-override@example.com",
        password="OverridePass#1",
        role="ESTIMATOR",
    )
    _create_account(
        company_id=company_id,
        username="estimator-override",
        email="estimator-override@example.com",
        password="OverridePass#1",
        role="ESTIMATOR",
        granted_permissions=["invoices.view"],
    )
    _create_account(
        company_id=company_id,
        username="ess-override",
        email="ess-override@example.com",
        password="OverridePass#1",
        role="EMPLOYEE_SELF_SERVICE",
        linked_employee_id=employee.id,
        granted_permissions=["invoices.view"],
    )

    denied_headers = _login_headers("estimator-no-override", "OverridePass#1", company_id)
    denied = client.get("/invoices", headers=denied_headers)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_required"

    allowed_headers = _login_headers("estimator-override", "OverridePass#1", company_id)
    allowed = client.get("/invoices", headers=allowed_headers)
    assert allowed.status_code == 200, allowed.text

    ess_headers = _login_headers("ess-override", "OverridePass#1", company_id)
    ess_attempt = client.get("/invoices", headers=ess_headers)
    assert ess_attempt.status_code == 403
    assert ess_attempt.json()["detail"]["code"] == "operations_access_required"


def test_sensitive_payroll_routes_require_fresh_mfa_when_enabled():
    company_id = 67109
    _save_company_profile(company_id, modules=["payroll"])
    today = date.today()
    account = _create_account(
        company_id=company_id,
        username="mfa-accountant",
        email="mfa-accountant@example.com",
        password="MfaAccountantPass#1",
        role="ACCOUNTANT",
    )

    db = SessionLocal()
    try:
        db.query(UserAccount).filter(UserAccount.user_account_id == account.user_account_id).update({"mfa_enabled": True})
        employee = _seed_employee(company_id, "MFA Finalize Worker", "mfa.finalize.worker@example.com")
        pay_period = PayPeriod(
            pay_period_id=f"pp-mfa-{company_id}",
            company_id=company_id,
            start_date=today - timedelta(days=7),
            end_date=today,
            status="OPEN",
        )
        post_pay_period = PayPeriod(
            pay_period_id=f"pp-mfa-post-{company_id}",
            company_id=company_id,
            start_date=today - timedelta(days=21),
            end_date=today - timedelta(days=14),
            status="OPEN",
        )
        finalize_run = PayrollRun(
            payroll_run_id=f"pr-mfa-finalize-{company_id}",
            company_id=company_id,
            pay_period_id=pay_period.pay_period_id,
            status="DRAFT",
        )
        post_run = PayrollRun(
            payroll_run_id=f"pr-mfa-post-{company_id}",
            company_id=company_id,
            pay_period_id=post_pay_period.pay_period_id,
            status="FINALIZED",
        )
        db.add(pay_period)
        db.add(post_pay_period)
        db.add(finalize_run)
        db.add(post_run)
        db.flush()
        db.add(
            PayrollItem(
                company_id=company_id,
                payroll_run_id=finalize_run.payroll_run_id,
                employee_id=employee.id,
                hours=2,
                rate_cents=3000,
                gross_pay_cents=6000,
                meta={"job_id": 1},
            )
        )
        db.commit()
    finally:
        db.close()

    fresh_token = create_access_token(
        user_id=account.user_account_id,
        company_id=company_id,
        mfa_authenticated=True,
        mfa_authenticated_at=datetime.now(timezone.utc),
    )
    fresh_headers = {"Authorization": f"Bearer {fresh_token}", "X-Company-Id": str(company_id)}
    finalized = client.post(f"/payroll/runs/pr-mfa-finalize-{company_id}/finalize", headers=fresh_headers)
    assert finalized.status_code == 200, finalized.text

    stale_token = create_access_token(
        user_id=account.user_account_id,
        company_id=company_id,
        mfa_authenticated=True,
        mfa_authenticated_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    stale_headers = {"Authorization": f"Bearer {stale_token}", "X-Company-Id": str(company_id)}
    stale_finalize = client.post(f"/payroll/runs/pr-mfa-post-{company_id}/finalize", headers=stale_headers)
    assert stale_finalize.status_code == 403
    assert stale_finalize.json()["detail"]["code"] == "fresh_mfa_required"

    stale_post = client.post(f"/payroll/runs/pr-mfa-post-{company_id}/post", headers=stale_headers)
    assert stale_post.status_code == 403
    assert stale_post.json()["detail"]["code"] == "fresh_mfa_required"
