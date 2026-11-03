import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.auth.dependencies import current_user
from src.config.database import get_session
from src.copilot.assistant import ask
from src.models import Conversation, User
from src.models.copilot import MessageRole, QuestionRoute

# Every signed-in role uses the assistant (PRD roles table). Conversations are private.
router = APIRouter(prefix="/conversations", tags=["compliance assistant"], dependencies=[Depends(current_user)])
TITLE_CHARS = 80


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: MessageRole
    content: str
    route: QuestionRoute | None
    sources: list[dict[str, Any]]
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime


class ConversationDetailOut(ConversationOut):
    messages: list[MessageOut]


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


def own_conversation(session: Session, conversation_id: uuid.UUID, user: User) -> Conversation:
    conversation = session.scalar(
        select(Conversation).where(Conversation.id == conversation_id).options(selectinload(Conversation.messages))
    )
    # Someone else's conversation answers 404, not 403: don't confirm it exists.
    if conversation is None or conversation.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found.")
    return conversation



@router.get("", response_model=list[ConversationOut])
def my_conversations(user: User = Depends(current_user), session: Session = Depends(get_session)) -> list[Conversation]:

    return list(session.scalars(select(Conversation)).where(Conversation.user_id == user.id).order_by(Conversation.created_at.desc()))

@router.post("", response_model=ConversationDetailOut, status_code=status.HTTP_201_CREATED)
def start_conversation(body: Question, user: User = Depends(current_user), session: Session = Depends(get_session)) -> Conversation:
    """Start a conversation with its first question; the answer comes back in `messages`."""
    conversation = Conversation(user_id=user.id, title=body.question[:TITLE_CHARS])
    session.add(conversation)
    session.flush()
    ask(session, user, conversation, body.question)
    session.commit()
    return own_conversation(session, conversation.id, user)


@router.get("/{conversation_id}", response_model=ConversationDetailOut)
def read_conversation(conversation_id: uuid.UUID, user: User = Depends(current_user), session: Session = Depends(get_session)) -> Conversation:
    return own_conversation(session, conversation_id, user)


@router.post("/{conversation_id}/messages", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def ask_question(
    conversation_id: uuid.UUID, body: Question, user: User = Depends(current_user), session: Session = Depends(get_session)
):
    """A follow-up question: earlier messages are used to understand it ("what about their coating?")."""
    conversation = own_conversation(session, conversation_id, user)
    reply = ask(session, user, conversation, body.question)
    session.commit()
    return reply