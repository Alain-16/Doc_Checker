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
  "Is X compliant with Y?" is a content question too: the answer shows what the documents state.
- aggregate: counting or listing documents or their recorded fields. "Which bulletins are stale?",
  "How many documents need review?", "List the lot numbers on the quality certificate."
  A document's own recorded fields are aggregate, not content: its revision, document number,
  issue or governing date, signatory, lots ("What is the revision of the compliance bulletin?",
  "What is the TSB number?", "When was it last revised?"). So is which document is oldest or newest,
  even when the question then asks what that document contains.
- findings: why something was flagged or what the compliance checks found. "Why is the bulletin stale?",
  "What's wrong with the West stopper's documentation?"
- cross_document: the same question asked of many documents at once, needing both a list and
  each document's content. "Which bulletins don't mention Proposition 65?"
- out_of_scope: ONLY questions that are not about vendor documents or products at all ("What's the
  weather?"), or that ask us to make the decision ("Should we approve this vendor?", "Is it safe
  for our drug?"): a qualified person decides those.
A question about a product, material, test result or document is never out_of_scope, even if the
documents may not contain the answer: route it to content (the answer will then say "not found").

A request for the sources, pages or evidence of the assistant's previous answer ("Show me the source
page for that", "Where does it say that?"): route content, set about_previous_answer = true, and
rewrite it as the earlier question. Otherwise about_previous_answer = false.

Rewrite the question so it stands alone, resolving references to the conversation ("their", "it",
"that bulletin"). Copy vendor and component names as the user wrote them; leave a list empty if none.
Components are specific product names or part numbers ("4432/50 Grey", "V10-F597W"), never generic
words such as "stopper", "closure" or "the item". Coatings, materials, technologies and trademarks
("FluroTec", "B2 coating", "Teflon", "chlorobutyl") are NOT components: they belong in the topic.
document_types: only keys from this list (key = display name): {types}.
In the standalone question, write document types by their display name, never by their key.
topic: a short search phrase for the subject, e.g. "natural rubber latex content"."""


class QuestionPlan(BaseModel):
    route: Literal["content", "aggregate", "findings", "cross_document", "out_of_scope"]
    standalone_question: str
    vendors: list[str] = Field(description="Vendor names as written, e.g. 'West'.")
    components: list[str] = Field(description="Component names or part numbers as written, e.g. '4432/50 Grey'.")
    document_types: list[str]
    topic: str
    about_previous_answer: bool = Field(description="True only when asking for the previous answer's sources or pages.")


@dataclass
class Scope:
    """Where to look: the names in the question, matched to real records."""

    vendor_ids: list[uuid.UUID] = field(default_factory=list)
    component_ids: list[uuid.UUID] = field(default_factory=list)
    document_type_names: list[str] = field(default_factory=list)
    # Vendors and part numbers the user mentioned that match nothing: the answer stops and says so.
    unmatched: list[str] = field(default_factory=list)
    # Other unknown component names ("FluroTec"): searched as part of the topic, never a reason to stop.
    searched_as_topic: list[str] = field(default_factory=list)


def plan_question(question: str, history: list[tuple[MessageRole, str]], types: dict[str, str]) -> QuestionPlan:
    """types: document type key -> display name."""
    conversation = "\n".join(f"{role.value}: {content}" for role, content in history[-HISTORY_MESSAGES:])
    llm = structured_llm(LlmTask.ROUTE_QUESTION, QuestionPlan)
    return llm.invoke([
        ("system", ROUTER_PROMPT.format(types=", ".join(f"{key} = {name}" for key, name in types.items()))),
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


def looks_like_part_number(mention: str) -> bool:
    """'4432/40' or 'V10-F597W': an unknown one must stop the answer (it would be about another part)."""
    return any(character.isdigit() for character in mention)


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
        if found:
            continue
        if looks_like_part_number(mention):
            scope.unmatched.append(mention)
        else:
            scope.searched_as_topic.append(mention)
    # The router may answer with the key or the display name; both map to the key.
    type_keys = {}
    for key, display_name in session.execute(select(DocumentType.name, DocumentType.display_name)):
        type_keys[name_key(key.replace("_", " "))] = key
        type_keys[name_key(display_name)] = key
    found_types = (type_keys.get(name_key(mention.replace("_", " "))) for mention in plan.document_types)
    scope.document_type_names = list(dict.fromkeys(key for key in found_types if key))
    return scope