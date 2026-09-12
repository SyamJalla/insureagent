"""Conversation endpoints."""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.agents.runner import AgentRunner
from app.auth.dependency import get_request_context
from app.auth.models import RequestContext
from app.config import get_settings
from app.conversations.models import Conversation, Message
from app.conversations.service import ConversationNotFound, ConversationService
from app.conversations.store import PostgresConversationStore

router = APIRouter(prefix="/conversations", tags=["conversations"])


def get_service() -> ConversationService:
    store = PostgresConversationStore(get_settings().app_db_url)
    return ConversationService(store, AgentRunner())


class SendMessageRequest(BaseModel):
    content: str


@router.post("", status_code=status.HTTP_201_CREATED)
def start_conversation(
    ctx: RequestContext = Depends(get_request_context),
    svc: ConversationService = Depends(get_service),
) -> Conversation:
    return svc.start(ctx)


@router.get("")
def list_conversations(
    ctx: RequestContext = Depends(get_request_context),
    svc: ConversationService = Depends(get_service),
) -> list[Conversation]:
    return svc.list_for_user(ctx)


@router.get("/{conversation_id}/messages")
def get_messages(
    conversation_id: str,
    ctx: RequestContext = Depends(get_request_context),
    svc: ConversationService = Depends(get_service),
) -> list[Message]:
    try:
        return svc.history(ctx, conversation_id)
    except ConversationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")


@router.post("/{conversation_id}/messages")
def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    ctx: RequestContext = Depends(get_request_context),
    svc: ConversationService = Depends(get_service),
) -> Message:
    try:
        return svc.send_message(ctx, conversation_id, body.content)
    except ConversationNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "conversation not found")
