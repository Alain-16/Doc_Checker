import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.llm.models import LlmTask, structured_llm
from src.models import Component, DocumentType, Vendor
from src.models.copilot import MessageRole


HISTORY_MESSAGES = 6
# Names shorter than this are too likely to match by accident ("AB" inside "LAB").
MIN_NAME_CHARS = 3
NOT_A_NAME_CHARACTER = re.compile(r"[^0-9a-z/]+")

ROUTER_PROMPT = """You route questions asked to a pharmaceutical QA team's document assistant.
The assistant only knows the organisation's vendor documents (quality certificates, compliance
bulletins, technical bulletins, formulation sheets, drawings) and the compliance checks run on them.

Routes:
- content: what a document SAYS. "Does the stopper contain latex?", "What storage conditions does the TSB give?"
- aggregate: counting or listing documents or their recorded fields. "Which bulletins are stale?",
  "How many documents need review?", "List the lot numbers on the quality certificate."
- findings: why something was flagged or what the compliance checks found. "Why is the bulletin stale?",
  "What's wrong with the West stopper's documentation?"
- cross_document: the same question asked of many documents at once, needing both a list and
  each document's content. "Which bulletins don't mention Proposition 65?"
- out_of_scope: ONLY questions that are not about vendor documents or products at all ("What's the
  weather?"), or that ask for a regulatory opinion or a compliance decision ("Is it safe to use?",
  "Should we approve this vendor?"): a qualified person decides those.
A question about a product, material, test result or document is never out_of_scope, even if the
documents may not contain the answer: route it to content (the answer will then say "not found").

Rewrite the question so it stands alone, resolving references to the conversation ("their", "it",
"that bulletin"). Copy vendor and component names as the user wrote them; leave a list empty if none.
Components are specific names or part numbers ("4432/50 Grey", "FluroTec"), never generic words
such as "stopper", "closure" or "the item".
document_types: only names from this list: {types}.
topic: a short search phrase for the subject, e.g. "natural rubber latex content"."""


class QuestionPlan(BaseModel):
    route: Literal["content", "aggregate", "findings", "cross_document", "out_of_scope"]
    standalone_question: str
    vendors: list[str] = Field(description="Vendor names as written, e.g. 'West'.")
    components: list[str] = Field(description="Component names or part numbers as written, e.g. '4432/50 Grey'.")
    document_types: list[str]
    topic: str


@dataclass
class Scope:
    """Where to look: the names in the question, matched to real records."""

    vendor_ids: list[uuid.UUID] = field(default_factory=list)
    component_ids: list[uuid.UUID] = field(default_factory=list)
    document_type_names: list[str] = field(default_factory=list)
    # Names the user mentioned that match nothing: the answer says so.
    unmatched: list[str] = field(default_factory=list)


def plan_question(question: str, history: list[tuple[MessageRole, str]], type_names: list[str]) -> QuestionPlan:
    conversation = "\n".join(f"{role.value}: {content}" for role, content in history[-HISTORY_MESSAGES:])
    llm = structured_llm(LlmTask.ROUTE_QUESTION, QuestionPlan)
    return llm.invoke([
        ("system", ROUTER_PROMPT.format(types=", ".join(type_names))),
        ("human", f"Conversation so far:\n{conversation or '(none)'}\n\nNew question: {question}"),
    ])


def name_key(text: str) -> str:
    """'4432/50 Grey' and '4432/50  grey.' compare equal: lowercase letters, digits and '/'."""
    return NOT_A_NAME_CHARACTER.sub(" ", text.casefold()).strip()


def names_match(mention: str, known: str) -> bool:
    """Whole words of one inside the other: 'West' matches 'West Pharmaceutical Services, Inc.'."""
    a, b = name_key(mention), name_key(known)
    if len(a) < MIN_NAME_CHARS or len(b) < MIN_NAME_CHARS:
        return False
    return f" {a} " in f" {b} " or f" {b} " in f" {a} "


def resolve_scope(session: Session, plan: QuestionPlan) -> Scope:
    """Match the plan's names against vendors, components (name, part numbers, aliases) and types."""
    scope = Scope()
    vendors = session.scalars(select(Vendor)).all()
    components = session.scalars(select(Component)).all()
    for mention in plan.vendors:
        found = [v.id for v in vendors if any(names_match(mention, name) for name in [v.name, *v.aliases])]
        scope.vendor_ids += found
        if not found:
            scope.unmatched.append(mention)
    for mention in plan.components:
        found = [
            c.id for c in components
            if any(names_match(mention, name) for name in [c.name, c.vendor_part_number or "", c.internal_part_number or "", *c.aliases])
        ]
        scope.component_ids += found
        if not found:
            scope.unmatched.append(mention)
    known_types = set(session.scalars(select(DocumentType.name)))
    scope.document_type_names = [name for name in plan.document_types if name in known_types]
    return scope