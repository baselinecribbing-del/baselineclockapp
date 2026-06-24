from __future__ import annotations

from datetime import datetime, timedelta, timezone
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.company_profile import CompanyProfile
from app.models.employee import Employee
from app.models.frontier_ai_conversation import FrontierAIConversation
from app.models.frontier_ai_message import FrontierAIMessage
from app.models.job import Job
from app.schemas.frontier_ai import FrontierAIQueryRequest, FrontierAISelectedRecord

LIMITATION_WARNING = (
    "Frontier AI is connected to the backend conversation path, but operational tool execution, "
    "streaming, and deep workflow automation are not wired in yet."
)


class FrontierAIConversationNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class FrontierAIQueryResult:
    conversation: FrontierAIConversation
    reply: str
    warning: str | None


def _get_recent_messages(*, db: Session, conversation_id: str, limit: int = 6) -> list[FrontierAIMessage]:
    return (
        db.query(FrontierAIMessage)
        .filter(FrontierAIMessage.conversation_id == conversation_id)
        .order_by(FrontierAIMessage.created_at.desc(), FrontierAIMessage.frontier_ai_message_id.desc())
        .limit(limit)
        .all()
    )


def _resolve_selected_record_summary(
    *,
    db: Session,
    company_id: int,
    selected_record: FrontierAISelectedRecord | None,
) -> str | None:
    if selected_record is None:
        return None

    record_type = selected_record.record_type.lower()
    record_id = selected_record.record_id

    if record_type == "job":
        try:
            job_id = int(record_id)
        except ValueError:
            return f"Selected job reference `{record_id}` is not a valid numeric job id."
        job = db.query(Job).filter(Job.id == job_id, Job.company_id == int(company_id)).one_or_none()
        if job is None:
            return f"Selected job `{record_id}` was not found for this company."
        return f"Selected job: {job.name} (status: {job.status}, id: {job.id})."

    if record_type == "employee":
        try:
            employee_id = int(record_id)
        except ValueError:
            return f"Selected employee reference `{record_id}` is not a valid numeric employee id."
        employee = (
            db.query(Employee)
            .filter(Employee.id == employee_id, Employee.company_id == int(company_id))
            .one_or_none()
        )
        if employee is None:
            return f"Selected employee `{record_id}` was not found for this company."
        return f"Selected employee: {employee.name} (status: {employee.employment_status}, id: {employee.id})."

    label = selected_record.label or record_id
    return f"Selected record context: {selected_record.record_type} `{label}`."


def _build_reply(
    *,
    profile: CompanyProfile,
    payload: FrontierAIQueryRequest,
    selected_record_summary: str | None,
    recent_messages: list[FrontierAIMessage],
) -> str:
    lines = [
        f"Frontier AI is active for company {profile.company_id} ({profile.company_name}).",
        f"Primary trade on file: {profile.primary_trade}.",
    ]

    if payload.surface_context:
        lines.append(f"Current surface: {payload.surface_context}.")

    if payload.page_context:
        visible_keys = sorted(str(key) for key in payload.page_context.keys())
        lines.append(f"Page context fields received: {', '.join(visible_keys[:6])}.")

    if selected_record_summary:
        lines.append(selected_record_summary)

    prior_user_messages = [row for row in recent_messages if row.role == "USER"]
    if prior_user_messages:
        lines.append(f"Conversation continuity confirmed. Prior user turns stored: {len(prior_user_messages)}.")

    lines.append(f"Latest request: {payload.message}")
    lines.append(
        "Current response mode is advisory only. I can preserve context and reflect scoped records, "
        "but I am not executing downstream payroll, dispatch, or document actions yet."
    )
    return " ".join(lines)


def _load_or_create_conversation(
    *,
    db: Session,
    company_id: int,
    user_id: str,
    conversation_id: str | None,
) -> FrontierAIConversation:
    if conversation_id:
        conversation = (
            db.query(FrontierAIConversation)
            .filter(
                FrontierAIConversation.conversation_id == conversation_id,
                FrontierAIConversation.company_id == int(company_id),
                FrontierAIConversation.user_id == str(user_id),
            )
            .one_or_none()
        )
        if conversation is None:
            raise FrontierAIConversationNotFoundError(conversation_id)
        return conversation

    conversation = FrontierAIConversation(company_id=int(company_id), user_id=str(user_id))
    db.add(conversation)
    db.flush()
    return conversation


def handle_query(
    *,
    db: Session,
    company_id: int,
    user_id: str,
    profile: CompanyProfile,
    payload: FrontierAIQueryRequest,
) -> FrontierAIQueryResult:
    conversation = _load_or_create_conversation(
        db=db,
        company_id=company_id,
        user_id=user_id,
        conversation_id=payload.conversation_id,
    )
    recent_messages = _get_recent_messages(db=db, conversation_id=conversation.conversation_id)
    selected_record_payload = payload.selected_record.model_dump() if payload.selected_record else None
    selected_record_summary = _resolve_selected_record_summary(
        db=db,
        company_id=company_id,
        selected_record=payload.selected_record,
    )
    user_message_created_at = datetime.now(timezone.utc)
    assistant_message_created_at = user_message_created_at + timedelta(microseconds=1)

    user_message = FrontierAIMessage(
        conversation_id=conversation.conversation_id,
        company_id=int(company_id),
        user_id=str(user_id),
        role="USER",
        content=payload.message,
        surface_context=payload.surface_context,
        page_context=payload.page_context,
        selected_record=selected_record_payload,
        created_at=user_message_created_at,
    )
    db.add(user_message)

    reply = _build_reply(
        profile=profile,
        payload=payload,
        selected_record_summary=selected_record_summary,
        recent_messages=recent_messages,
    )
    assistant_message = FrontierAIMessage(
        conversation_id=conversation.conversation_id,
        company_id=int(company_id),
        user_id=None,
        role="ASSISTANT",
        content=reply,
        surface_context=payload.surface_context,
        page_context=payload.page_context,
        selected_record=selected_record_payload,
        created_at=assistant_message_created_at,
    )
    db.add(assistant_message)

    conversation.updated_at = assistant_message_created_at
    db.add(conversation)
    db.commit()
    db.refresh(conversation)

    return FrontierAIQueryResult(
        conversation=conversation,
        reply=reply,
        warning=LIMITATION_WARNING,
    )
