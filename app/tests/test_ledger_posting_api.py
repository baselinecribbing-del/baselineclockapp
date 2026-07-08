from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.chart_of_account import ChartOfAccount
from app.models.fiscal_period import FiscalPeriod
from app.models.journal_entry import JournalEntry
from app.models.journal_entry_line import JournalEntryLine
from app.models.journal_posting_audit_event import JournalPostingAuditEvent
from app.services.journal_posting_service import JournalPostingApplicationError
from app.services.account_security_service import create_user_account

client = TestClient(app)


def _auth_headers(company_id: int) -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": "test", "company_id": int(company_id)})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    return {
        "X-Company-Id": str(company_id),
        "Authorization": f"Bearer {token}",
    }


def _create_account(
    *,
    company_id: int,
    username: str,
    email: str,
    password: str,
    role: str,
    granted_permissions: list[str] | None = None,
):
    db = SessionLocal()
    try:
        create_user_account(
            db=db,
            company_id=int(company_id),
            username=username,
            email=email,
            password=password,
            role=role,
            granted_permissions=granted_permissions,
            commit=True,
        )
    finally:
        db.close()


def _login_headers(*, username: str, password: str, company_id: int) -> dict[str, str]:
    resp = client.post("/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {
        "Authorization": f"Bearer {token}",
        "X-Company-Id": str(company_id),
    }


def _insert_account(*, db, company_id: int, code: str, normal_balance: str) -> ChartOfAccount:
    row = ChartOfAccount(
        company_id=int(company_id),
        code=str(code),
        name=f"Account {code}",
        account_type="ASSET" if normal_balance == "DEBIT" else "LIABILITY",
        normal_balance=str(normal_balance),
        allow_posting=True,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def _insert_period(*, db, company_id: int, status: str) -> FiscalPeriod:
    row = FiscalPeriod(
        company_id=int(company_id),
        name=f"2026-Q1-{status}-{company_id}",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 3, 31),
        status=str(status),
    )
    db.add(row)
    db.flush()
    return row


def _insert_entry(*, db, company_id: int, fiscal_period_id: str | None = None) -> JournalEntry:
    row = JournalEntry(
        company_id=int(company_id),
        entry_date=date(2026, 3, 15),
        status="DRAFT",
        fiscal_period_id=fiscal_period_id,
        source_type="MANUAL",
        source_reference_id=f"src-{company_id}",
        reference_number=f"JE-{company_id}",
        memo="api test",
    )
    db.add(row)
    db.flush()
    return row


def _insert_line(
    *,
    db,
    company_id: int,
    journal_entry_id: str,
    line_number: int,
    account_id: str,
    debit_amount_cents: int = 0,
    credit_amount_cents: int = 0,
) -> JournalEntryLine:
    row = JournalEntryLine(
        company_id=int(company_id),
        journal_entry_id=str(journal_entry_id),
        line_number=int(line_number),
        account_id=str(account_id),
        debit_amount_cents=int(debit_amount_cents),
        credit_amount_cents=int(credit_amount_cents),
    )
    db.add(row)
    db.flush()
    return row


def _assert_error_contract(resp, *, status_code: int, code: str):
    assert resp.status_code == int(status_code)
    body = resp.json()
    assert set(body.keys()) == {"code", "message"}
    assert body["code"] == str(code)
    assert isinstance(body["message"], str)
    assert body["message"]


def _count_success_post_audits(*, company_id: int, journal_entry_id: str) -> int:
    db = SessionLocal()
    try:
        return (
            db.query(JournalPostingAuditEvent)
            .filter(JournalPostingAuditEvent.company_id == int(company_id))
            .filter(JournalPostingAuditEvent.journal_entry_id == str(journal_entry_id))
            .filter(JournalPostingAuditEvent.event_type == "POST_ATTEMPT")
            .filter(JournalPostingAuditEvent.result == "SUCCESS")
            .count()
        )
    finally:
        db.close()


def test_posting_endpoint_success_response():
    db = SessionLocal()
    try:
        company_id = 801
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_entry(db=db, company_id=company_id)
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=700,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=700,
        )
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=_auth_headers(company_id))
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {
        "ok",
        "journal_entry_id",
        "status",
        "line_count",
        "debit_total_cents",
        "credit_total_cents",
        "posted_at",
        "audit_event_id",
    }
    assert data["ok"] is True
    assert data["journal_entry_id"] == entry.journal_entry_id
    assert data["status"] == "POSTED"
    assert isinstance(data["audit_event_id"], str) and data["audit_event_id"]


def test_posting_endpoint_not_found_or_wrong_scope():
    db = SessionLocal()
    try:
        source_company = 802
        other_company = 803
        entry = _insert_entry(db=db, company_id=source_company)
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=_auth_headers(other_company))
    _assert_error_contract(resp, status_code=404, code="JOURNAL_NOT_FOUND")


def test_posting_endpoint_repeat_submit_is_idempotent_and_no_duplicate_success_side_effects():
    db = SessionLocal()
    try:
        company_id = 804
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_entry(db=db, company_id=company_id)
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=500,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=500,
        )
        db.commit()
    finally:
        db.close()

    headers = _auth_headers(company_id)
    first = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=headers)
    assert first.status_code == 200
    first_body = first.json()
    first_audit_count = _count_success_post_audits(company_id=company_id, journal_entry_id=entry.journal_entry_id)
    assert first_audit_count == 1

    second = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=headers)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["ok"] is True
    assert second_body["status"] == "POSTED"
    assert second_body["journal_entry_id"] == entry.journal_entry_id
    assert second_body["audit_event_id"] == first_body["audit_event_id"]
    second_audit_count = _count_success_post_audits(company_id=company_id, journal_entry_id=entry.journal_entry_id)
    assert second_audit_count == 1


def test_posting_endpoint_no_lines():
    db = SessionLocal()
    try:
        company_id = 805
        entry = _insert_entry(db=db, company_id=company_id)
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=_auth_headers(company_id))
    _assert_error_contract(resp, status_code=409, code="JOURNAL_NO_LINES")


def test_posting_endpoint_unbalanced():
    db = SessionLocal()
    try:
        company_id = 806
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_entry(db=db, company_id=company_id)
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=500,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=400,
        )
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=_auth_headers(company_id))
    _assert_error_contract(resp, status_code=409, code="JOURNAL_UNBALANCED")


@pytest.mark.parametrize("period_status", ["CLOSED", "LOCKED"])
def test_posting_endpoint_closed_locked_period(period_status: str):
    db = SessionLocal()
    try:
        company_id = 807 if period_status == "CLOSED" else 808
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        period = _insert_period(db=db, company_id=company_id, status=period_status)
        entry = _insert_entry(db=db, company_id=company_id, fiscal_period_id=period.fiscal_period_id)
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=1000,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=1000,
        )
        db.commit()
    finally:
        db.close()

    resp = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=_auth_headers(company_id))
    _assert_error_contract(resp, status_code=409, code="JOURNAL_PERIOD_CLOSED_OR_LOCKED")


def test_posting_endpoint_db_guard_maps_to_expected_code(monkeypatch):
    db = SessionLocal()
    try:
        company_id = 809
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        period = _insert_period(db=db, company_id=company_id, status="LOCKED")
        entry = _insert_entry(db=db, company_id=company_id, fiscal_period_id=period.fiscal_period_id)
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=400,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=400,
        )
        db.commit()
    finally:
        db.close()

    import app.services.journal_posting_service as svc

    monkeypatch.setattr(svc, "_load_period_for_entry", lambda **_kwargs: None)

    resp = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=_auth_headers(company_id))
    assert resp.status_code == 409
    body = resp.json()
    assert set(body.keys()) == {"code", "message"}
    assert body["code"] in {"JOURNAL_PERIOD_CLOSED_OR_LOCKED", "JOURNAL_DB_GUARD_VIOLATION"}


def test_posting_endpoint_persistence_failure_contract(monkeypatch):
    import app.routers.ledger as ledger_router

    def _raise_persistence(**_kwargs):
        raise JournalPostingApplicationError(
            code="JOURNAL_PERSISTENCE_FAILURE",
            message="Unexpected persistence failure during journal posting",
        )

    monkeypatch.setattr(ledger_router, "post_journal_entry_with_audit", _raise_persistence)

    company_id = 810
    headers = _auth_headers(company_id)
    resp = client.post("/ledger/journal-entries/nonexistent/post", headers=headers)
    _assert_error_contract(resp, status_code=500, code="JOURNAL_PERSISTENCE_FAILURE")


def test_posting_endpoint_openapi_documents_error_models():
    spec = client.get("/openapi.json")
    assert spec.status_code == 200
    data = spec.json()
    route = data["paths"]["/ledger/journal-entries/{journal_entry_id}/post"]["post"]
    responses = route["responses"]

    assert responses["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/JournalPostResponse")
    assert responses["404"]["content"]["application/json"]["schema"]["$ref"].endswith("/JournalPostErrorResponse")
    assert responses["409"]["content"]["application/json"]["schema"]["$ref"].endswith("/JournalPostErrorResponse")
    assert responses["500"]["content"]["application/json"]["schema"]["$ref"].endswith("/JournalPostErrorResponse")


def test_posting_endpoint_permission_allowed_for_accountant():
    db = SessionLocal()
    try:
        company_id = 811
        debit = _insert_account(db=db, company_id=company_id, code="1000", normal_balance="DEBIT")
        credit = _insert_account(db=db, company_id=company_id, code="2000", normal_balance="CREDIT")
        entry = _insert_entry(db=db, company_id=company_id)
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=1,
            account_id=debit.account_id,
            debit_amount_cents=650,
        )
        _insert_line(
            db=db,
            company_id=company_id,
            journal_entry_id=entry.journal_entry_id,
            line_number=2,
            account_id=credit.account_id,
            credit_amount_cents=650,
        )
        db.commit()
    finally:
        db.close()

    _create_account(
        company_id=company_id,
        username="ledger-accountant",
        email="ledger-accountant@example.com",
        password="LedgerAccPass#1",
        role="ACCOUNTANT",
    )
    headers = _login_headers(username="ledger-accountant", password="LedgerAccPass#1", company_id=company_id)
    resp = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "POSTED"


def test_posting_endpoint_permission_denied_without_ledger_permission():
    db = SessionLocal()
    try:
        company_id = 812
        entry = _insert_entry(db=db, company_id=company_id)
        db.commit()
    finally:
        db.close()

    _create_account(
        company_id=company_id,
        username="ledger-manager",
        email="ledger-manager@example.com",
        password="LedgerMgrPass#1",
        role="MANAGER",
    )
    headers = _login_headers(username="ledger-manager", password="LedgerMgrPass#1", company_id=company_id)
    resp = client.post(f"/ledger/journal-entries/{entry.journal_entry_id}/post", headers=headers)
    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "permission_required"
    assert "ledger.journals.post" in detail["message"]


def test_posting_endpoint_rejects_company_header_mismatch():
    company_id = 813
    _create_account(
        company_id=company_id,
        username="ledger-header-test",
        email="ledger-header-test@example.com",
        password="LedgerHeaderPass#1",
        role="ACCOUNTANT",
    )
    headers = _login_headers(username="ledger-header-test", password="LedgerHeaderPass#1", company_id=company_id)
    headers["X-Company-Id"] = str(company_id + 1)
    resp = client.post("/ledger/journal-entries/nonexistent/post", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Company mismatch"
