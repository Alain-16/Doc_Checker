import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import Base, enum_check, string_enum

EMPTY_JSON_LIST = text("'[]'::jsonb")


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class QuestionRoute(StrEnum):
    """How a question is answered (PRD Feature 12)."""

    CONTENT = "content"  # what the documents say: search + passages
    AGGREGATE = "aggregate"  # counting and listing: the database
    FINDINGS = "findings"  # why something was flagged: the rules engine's findings
    CROSS_DOCUMENT = "cross_document"  # find documents in the database, then read each
    OUT_OF_SCOPE = "out_of_scope"  # not about the documentation (or a regulatory opinion)


class Conversation(Base):
    """One chat thread. Private to the user who started it."""

    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str]

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", order_by="Message.created_at"
    )


class Message(Base):
    """One turn: the user's question, or the assistant's answer with its sources."""

    __tablename__ = "messages"
    __table_args__ = (enum_check("role", MessageRole), enum_check("route", QuestionRoute))

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[MessageRole] = mapped_column(string_enum(MessageRole))
    content: Mapped[str] = mapped_column(Text)
    # Answers only: how it was answered and the numbered sources it cites
    # (document, pages, compliance status), exactly as shown to the user.
    route: Mapped[QuestionRoute | None] = mapped_column(string_enum(QuestionRoute))
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default=EMPTY_JSON_LIST)

    # The question and its answer are saved in one transaction, where now() returns
    # the same time for both; clock_timestamp() is the real time of each insert, so
    # ordering by created_at keeps every answer after its question.
    created_at: Mapped[datetime] = mapped_column(server_default=func.clock_timestamp(), sort_order=1)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class QueryLog(Base):
    """Everything about how one answer was produced (PRD: every question, route,
    retrieved source and answer is logged for audit). Append-only: a database
    trigger blocks UPDATE and DELETE."""

    __tablename__ = "query_logs"
    __table_args__ = (enum_check("route", QuestionRoute),)

    # The answer this log explains (one log per answer).
    message_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("messages.id", ondelete="RESTRICT"), unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    question: Mapped[str] = mapped_column(Text)
    # The question rewritten to stand alone ("What about their coating?" -> full question).
    standalone_question: Mapped[str] = mapped_column(Text)
    route: Mapped[QuestionRoute] = mapped_column(string_enum(QuestionRoute))
    # What was understood and how names were matched, e.g. {"vendors": ["West"], "matched": {...}}.
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # Every candidate looked at, with its scores, and whether it was kept.
    retrieved: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default=EMPTY_JSON_LIST)
    # Database tools called (aggregate / findings / cross-document routes) and their arguments.
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default=EMPTY_JSON_LIST)
    answer: Mapped[str] = mapped_column(Text)
    # Claims the grounding check removed, with the reason.
    removed_claims: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, server_default=EMPTY_JSON_LIST)
    not_found: Mapped[bool]
    # The model used for each step, e.g. {"route_question": "gpt-5-mini", ...}.
    models: Mapped[dict[str, Any]] = mapped_column(JSONB)
    duration_ms: Mapped[int]