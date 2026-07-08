from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps.auth import get_actor_user_id
from app.deps.entitlements import CompanyAccessContext, require_company_capability
from app.schemas.frontier_ai import FrontierAIQueryRequest, FrontierAIQueryResponse
from app.services.frontier_ai import FrontierAIConversationNotFoundError, handle_query

router = APIRouter(prefix="/frontier-ai", tags=["Frontier AI"])


@router.post("/query", response_model=FrontierAIQueryResponse)
def query_frontier_ai(
    payload: FrontierAIQueryRequest,
    request: Request,
    context: CompanyAccessContext = Depends(require_company_capability("frontier_ai")),
    db: Session = Depends(get_db),
) -> FrontierAIQueryResponse:
    try:
        result = handle_query(
            db=db,
            company_id=context.company_id,
            user_id=get_actor_user_id(request),
            profile=context.profile,
            payload=payload,
        )
    except FrontierAIConversationNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "frontier_ai_conversation_not_found",
                "message": "Conversation was not found for the current company context.",
            },
        ) from exc

    return FrontierAIQueryResponse(
        conversation_id=result.conversation.conversation_id,
        reply=result.reply,
        capability_status="enabled",
        company_id=context.company_id,
        warning=result.warning,
        created_at=result.conversation.created_at,
        updated_at=result.conversation.updated_at,
    )
