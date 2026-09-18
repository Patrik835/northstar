import json
import uuid

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import AppSettings, CurrentUser, DbSession
from app.integrations.ai.openai_provider import AIProviderError, OpenAIInvestmentAssistant
from app.schemas.assistant import (
    ChatRequest,
    ConversationRead,
    PortfolioContextRead,
    PortfolioReviewRead,
)
from app.services.assistant import (
    AssistantInputError,
    AssistantLimitError,
    AssistantService,
    PortfolioContextService,
)

router = APIRouter()


def _service(db: DbSession, settings: AppSettings) -> AssistantService:
    if not settings.ai_enabled or not settings.openai_api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI features are not enabled for this deployment",
        )
    return AssistantService(
        db,
        settings,
        OpenAIInvestmentAssistant(settings.openai_api_key, settings.openai_model),
    )


@router.get("/context", response_model=PortfolioContextRead)
async def portfolio_context(user: CurrentUser, db: DbSession) -> PortfolioContextRead:
    return await PortfolioContextService(db).read(user.id)


@router.get("/review", response_model=PortfolioReviewRead | None)
async def latest_review(
    user: CurrentUser, db: DbSession, settings: AppSettings
) -> PortfolioReviewRead | None:
    return await _service(db, settings).latest_review(user.id)


@router.post("/review", response_model=PortfolioReviewRead)
async def generate_review(
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
    force: bool = Query(default=False),
) -> PortfolioReviewRead:
    try:
        return await _service(db, settings).review(user.id, force=force)
    except AssistantLimitError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


@router.get("/conversations", response_model=list[ConversationRead])
async def conversations(
    user: CurrentUser, db: DbSession, settings: AppSettings
) -> list[ConversationRead]:
    return await _service(db, settings).conversations(user.id)


@router.post("/conversations", response_model=ConversationRead, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    user: CurrentUser, db: DbSession, settings: AppSettings
) -> ConversationRead:
    return await _service(db, settings).create_conversation(user.id)


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
):
    if not await _service(db, settings).delete_conversation(user.id, conversation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")


@router.post("/conversations/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: uuid.UUID,
    payload: ChatRequest,
    user: CurrentUser,
    db: DbSession,
    settings: AppSettings,
) -> StreamingResponse:
    service = _service(db, settings)
    try:
        context, history, message = await service.prepare_chat(
            user.id, conversation_id, payload.message
        )
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except AssistantInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except AssistantLimitError as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    async def events():
        try:
            async for chunk in service.stream_reply(
                user.id, conversation_id, context, history, message
            ):
                yield f"event: delta\ndata: {json.dumps({'text': chunk})}\n\n"
            yield "event: done\ndata: {}\n\n"
        except AIProviderError as exc:
            yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
