from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models.frontier_ai_conversation import FrontierAIConversation
from app.models.frontier_ai_message import FrontierAIMessage
from app.models.job import Job

client = TestClient(app)


def _auth_headers(company_id: int, user_id: str = "frontier-user") -> dict[str, str]:
    resp = client.post("/auth/token", json={"user_id": user_id, "company_id": company_id})
    assert resp.status_code == 200, f"token request failed: {resp.status_code} {resp.text}"
    token = resp.json()["access_token"]
    return {"X-Company-Id": str(company_id), "Authorization": f"Bearer {token}"}


def _save_profile(
    *,
    company_id: int,
    selected_tier: str,
    enabled_modules: list[str],
    primary_trade: str = "Foundations",
) -> None:
    resp = client.put(
        "/company/profile",
        headers=_auth_headers(company_id),
        json={
            "company_name": f"Company {company_id}",
            "primary_trade": primary_trade,
            "country": "CA",
            "province_or_state": "AB",
            "selected_tier": selected_tier,
            "enabled_modules": enabled_modules,
            "onboarding_completed": True,
        },
    )
    assert resp.status_code == 200, resp.text


def _seed_job(*, company_id: int, name: str) -> int:
    db = SessionLocal()
    try:
        row = Job(company_id=company_id, name=name, status="ACTIVE", is_active=True)
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    finally:
        db.close()


def test_entitled_company_can_query_frontier_ai_and_persist_conversation():
    company_id = 65101
    _save_profile(
        company_id=company_id,
        selected_tier="tier_3_full_system",
        enabled_modules=["jobs", "payroll", "field", "credentials"],
        primary_trade="Electrical",
    )
    job_id = _seed_job(company_id=company_id, name="Distribution Panel Upgrade")

    response = client.post(
        "/frontier-ai/query",
        headers=_auth_headers(company_id, user_id="dispatcher-a"),
        json={
            "message": "What context do you have for this job?",
            "surface_context": "jobs/workspace",
            "page_context": {"tab": "overview", "job_id": job_id},
            "selected_record": {"record_type": "job", "record_id": str(job_id), "label": "Panel Upgrade"},
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["company_id"] == company_id
    assert body["capability_status"] == "enabled"
    assert body["conversation_id"]
    assert "Distribution Panel Upgrade" in body["reply"]
    assert "jobs/workspace" in body["reply"]
    assert body["warning"]

    db = SessionLocal()
    try:
        conversations = db.query(FrontierAIConversation).all()
        messages = (
            db.query(FrontierAIMessage)
            .filter(FrontierAIMessage.conversation_id == body["conversation_id"])
            .order_by(FrontierAIMessage.created_at.asc(), FrontierAIMessage.frontier_ai_message_id.asc())
            .all()
        )
        assert len(conversations) == 1
        assert conversations[0].company_id == company_id
        assert conversations[0].user_id == "dispatcher-a"
        assert [row.role for row in messages] == ["USER", "ASSISTANT"]
    finally:
        db.close()


def test_non_entitled_company_is_blocked_from_frontier_ai():
    company_id = 65102
    _save_profile(
        company_id=company_id,
        selected_tier="tier_2_clock_in_payroll",
        enabled_modules=["field", "payroll"],
        primary_trade="Roofing",
    )

    response = client.post(
        "/frontier-ai/query",
        headers=_auth_headers(company_id),
        json={"message": "Can I use Frontier AI here?"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "capability_not_enabled"


def test_frontier_ai_conversation_reuse_and_company_isolation():
    owner_company_id = 65103
    other_company_id = 65104
    _save_profile(
        company_id=owner_company_id,
        selected_tier="tier_3_full_system",
        enabled_modules=["jobs", "payroll", "field"],
    )
    _save_profile(
        company_id=other_company_id,
        selected_tier="tier_3_full_system",
        enabled_modules=["jobs", "payroll", "field"],
    )

    headers = _auth_headers(owner_company_id, user_id="ops-a")
    create_response = client.post(
        "/frontier-ai/query",
        headers=headers,
        json={"message": "Start a Frontier AI conversation", "surface_context": "settings/frontier-ai"},
    )
    assert create_response.status_code == 200, create_response.text
    conversation_id = create_response.json()["conversation_id"]

    reuse_response = client.post(
        "/frontier-ai/query",
        headers=headers,
        json={"message": "Continue the same conversation", "conversation_id": conversation_id},
    )
    assert reuse_response.status_code == 200, reuse_response.text
    assert reuse_response.json()["conversation_id"] == conversation_id
    assert "Conversation continuity confirmed." in reuse_response.json()["reply"]

    blocked = client.post(
        "/frontier-ai/query",
        headers=_auth_headers(other_company_id, user_id="ops-b"),
        json={"message": "Try to read another company's conversation", "conversation_id": conversation_id},
    )
    assert blocked.status_code == 404
    assert blocked.json()["detail"]["code"] == "frontier_ai_conversation_not_found"

    db = SessionLocal()
    try:
        messages = (
            db.query(FrontierAIMessage)
            .filter(FrontierAIMessage.conversation_id == conversation_id)
            .order_by(FrontierAIMessage.created_at.asc(), FrontierAIMessage.frontier_ai_message_id.asc())
            .all()
        )
        assert len(messages) == 4
        assert [row.role for row in messages] == ["USER", "ASSISTANT", "USER", "ASSISTANT"]
        assert {row.company_id for row in messages} == {owner_company_id}
    finally:
        db.close()
