from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.main import app
from app.models.credential_type import CredentialType
from app.models.employee import Employee
from app.models.job import Job
from app.models.scope import Scope
from app.models.trade_type import TradeType

client = TestClient(app)

TRADE_SEEDS: list[tuple[str, str]] = [
    ("FOUNDATIONS", "Foundations"),
    ("ELECTRICAL", "Electrical"),
    ("PLUMBING", "Plumbing"),
    ("GAS", "Gas"),
    ("EXCAVATION", "Excavation"),
    ("FRAMING", "Framing"),
    ("ROOFING", "Roofing"),
    ("WASTE_HAULING", "Waste Hauling"),
    ("GENERAL_CONTRACTING", "General Contracting"),
]

CREDENTIAL_SEEDS: list[tuple[str, str, str, bool]] = [
    ("FIRST_AID", "First Aid", "SAFETY", False),
    ("FALL_PROTECTION", "Fall Protection", "SAFETY", False),
    ("CONFINED_SPACE", "Confined Space", "SAFETY", False),
    ("ELECTRICAL_TICKET", "Electrical Ticket", "TRADE", False),
    ("GAS_TICKET", "Gas Ticket", "TRADE", False),
    ("PLUMBING_LICENSE", "Plumbing License", "TRADE", False),
    ("COR", "COR", "COMPANY", True),
    ("SECOR", "SECOR", "COMPANY", True),
]


def _auth_headers(company_id: int) -> dict:
    resp = client.post("/auth/token", json={"user_id": "test", "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    data = resp.json()
    assert isinstance(data, dict), f"token response not a JSON object: {data}"
    assert "access_token" in data, f"token response missing access_token: {data}"
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {data['access_token']}"}


def _seed_trade_types() -> dict[str, str]:
    db = SessionLocal()
    try:
        rows: list[TradeType] = []
        for code, name in TRADE_SEEDS:
            row = TradeType(code=code, name=name, is_active=True)
            db.add(row)
            rows.append(row)
        db.commit()
        for row in rows:
            db.refresh(row)
        return {row.code: row.trade_type_id for row in rows}
    finally:
        db.close()


def _seed_credential_types() -> dict[str, str]:
    db = SessionLocal()
    try:
        rows: list[CredentialType] = []
        for code, name, category, is_company_level in CREDENTIAL_SEEDS:
            row = CredentialType(
                code=code,
                name=name,
                category=category,
                is_company_level=is_company_level,
                is_active=True,
            )
            db.add(row)
            rows.append(row)
        db.commit()
        for row in rows:
            db.refresh(row)
        return {row.code: row.credential_type_id for row in rows}
    finally:
        db.close()


def _seed_employee_job_scope(company_id: int, suffix: str) -> tuple[int, int, int]:
    db = SessionLocal()
    try:
        employee = Employee(company_id=company_id, name=f"Emp {suffix}", is_active=True)
        db.add(employee)
        db.flush()

        job = Job(company_id=company_id, name=f"Job {suffix}", is_active=True)
        db.add(job)
        db.flush()

        scope = Scope(company_id=company_id, job_id=job.id, name=f"Scope {suffix}", is_active=True)
        db.add(scope)
        db.commit()

        return employee.id, job.id, scope.id
    finally:
        db.close()


def test_trade_type_seeds_and_unique_code_constraint():
    _seed_trade_types()

    db = SessionLocal()
    try:
        codes = {row.code for row in db.query(TradeType).all()}
        assert codes == {code for code, _name in TRADE_SEEDS}

        db.add(TradeType(code="FOUNDATIONS", name="Duplicate Foundations", is_active=True))
        try:
            db.commit()
            assert False, "Expected duplicate trade type code to fail"
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_credential_type_seeds_and_unique_code_constraint():
    _seed_credential_types()

    db = SessionLocal()
    try:
        codes = {row.code for row in db.query(CredentialType).all()}
        assert codes == {code for code, _name, _category, _company_level in CREDENTIAL_SEEDS}

        db.add(
            CredentialType(
                code="FIRST_AID",
                name="Duplicate First Aid",
                category="SAFETY",
                is_company_level=False,
                is_active=True,
            )
        )
        try:
            db.commit()
            assert False, "Expected duplicate credential type code to fail"
        except IntegrityError:
            db.rollback()
    finally:
        db.close()


def test_employee_credential_create_list_update_and_expires_before_filter():
    credential_ids = _seed_credential_types()
    company_id = 41001
    employee_id, _job_id, _scope_id = _seed_employee_job_scope(company_id=company_id, suffix="E1")

    create_1 = client.post(
        "/credentials/employee",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "credential_type_id": credential_ids["FIRST_AID"],
            "certificate_number": "FA-123",
            "issued_date": "2026-01-05",
            "expiry_date": "2026-06-01",
            "document_url": "https://docs.example/fa-123",
            "verification_status": "PENDING",
        },
    )
    assert create_1.status_code == 200, create_1.text
    created_1 = create_1.json()

    create_2 = client.post(
        "/credentials/employee",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "credential_type_id": credential_ids["FALL_PROTECTION"],
            "expiry_date": "2027-01-01",
            "verification_status": "VERIFIED",
        },
    )
    assert create_2.status_code == 200, create_2.text

    listed = client.get(
        f"/credentials/employee?employee_id={employee_id}&verification_status=PENDING",
        headers=_auth_headers(company_id),
    )
    assert listed.status_code == 200
    listed_rows = listed.json()
    assert len(listed_rows) == 1
    assert listed_rows[0]["employee_credential_id"] == created_1["employee_credential_id"]

    expires_before = client.get(
        "/credentials/employee?expires_before=2026-12-31",
        headers=_auth_headers(company_id),
    )
    assert expires_before.status_code == 200
    rows = expires_before.json()
    assert len(rows) == 1
    assert rows[0]["credential_type_id"] == credential_ids["FIRST_AID"]

    patch = client.patch(
        f"/credentials/employee/{created_1['employee_credential_id']}",
        headers=_auth_headers(company_id),
        json={
            "verification_status": "VERIFIED",
            "expiry_date": "2026-12-15",
        },
    )
    assert patch.status_code == 200
    patched = patch.json()
    assert patched["verification_status"] == "VERIFIED"
    assert patched["expiry_date"] == "2026-12-15"


def test_employee_credential_company_scoping():
    credential_ids = _seed_credential_types()
    c1 = 42001
    c2 = 42002

    employee_id_c1, _job_id_1, _scope_id_1 = _seed_employee_job_scope(company_id=c1, suffix="C1")
    _employee_id_c2, _job_id_2, _scope_id_2 = _seed_employee_job_scope(company_id=c2, suffix="C2")

    create = client.post(
        "/credentials/employee",
        headers=_auth_headers(c1),
        json={
            "employee_id": employee_id_c1,
            "credential_type_id": credential_ids["FIRST_AID"],
            "verification_status": "PENDING",
        },
    )
    assert create.status_code == 200
    employee_credential_id = create.json()["employee_credential_id"]

    c2_listing = client.get("/credentials/employee", headers=_auth_headers(c2))
    assert c2_listing.status_code == 200
    assert c2_listing.json() == []

    c2_patch = client.patch(
        f"/credentials/employee/{employee_credential_id}",
        headers=_auth_headers(c2),
        json={"verification_status": "VERIFIED"},
    )
    assert c2_patch.status_code == 404


def test_employee_credential_verification_status_validation():
    credential_ids = _seed_credential_types()
    company_id = 43001
    employee_id, _job_id, _scope_id = _seed_employee_job_scope(company_id=company_id, suffix="V1")

    create = client.post(
        "/credentials/employee",
        headers=_auth_headers(company_id),
        json={
            "employee_id": employee_id,
            "credential_type_id": credential_ids["FIRST_AID"],
            "verification_status": "NOT_A_REAL_STATUS",
        },
    )
    assert create.status_code == 422


def test_job_trade_requirement_create_list_filters_and_company_scoping():
    trade_ids = _seed_trade_types()
    credential_ids = _seed_credential_types()

    c1 = 44001
    c2 = 44002

    _employee_1, job_id_1, scope_id_1 = _seed_employee_job_scope(company_id=c1, suffix="JR1")
    _employee_2, job_id_2, scope_id_2 = _seed_employee_job_scope(company_id=c2, suffix="JR2")

    create = client.post(
        "/credentials/job-requirements",
        headers=_auth_headers(c1),
        json={
            "job_id": job_id_1,
            "scope_id": scope_id_1,
            "trade_type_id": trade_ids["FOUNDATIONS"],
            "credential_type_id": credential_ids["FIRST_AID"],
            "is_required": True,
        },
    )
    assert create.status_code == 200, create.text
    created = create.json()

    listing = client.get(
        (
            f"/credentials/job-requirements?job_id={job_id_1}"
            f"&scope_id={scope_id_1}"
            f"&trade_type_id={trade_ids['FOUNDATIONS']}"
            f"&credential_type_id={credential_ids['FIRST_AID']}"
        ),
        headers=_auth_headers(c1),
    )
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["job_trade_requirement_id"] == created["job_trade_requirement_id"]

    listing_other_company = client.get(
        f"/credentials/job-requirements?job_id={job_id_2}&scope_id={scope_id_2}",
        headers=_auth_headers(c2),
    )
    assert listing_other_company.status_code == 200
    assert listing_other_company.json() == []


def test_trade_and_credential_type_list_endpoints_return_seeded_rows_when_present():
    _seed_trade_types()
    _seed_credential_types()
    company_id = 45001

    trade_list = client.get("/credentials/trade-types", headers=_auth_headers(company_id))
    assert trade_list.status_code == 200
    assert len(trade_list.json()) == len(TRADE_SEEDS)

    credential_list = client.get("/credentials/credential-types", headers=_auth_headers(company_id))
    assert credential_list.status_code == 200
    assert len(credential_list.json()) == len(CREDENTIAL_SEEDS)

    company_only_list = client.get(
        "/credentials/credential-types?category=COMPANY&is_company_level=true",
        headers=_auth_headers(company_id),
    )
    assert company_only_list.status_code == 200
    assert {row["code"] for row in company_only_list.json()} == {"COR", "SECOR"}
