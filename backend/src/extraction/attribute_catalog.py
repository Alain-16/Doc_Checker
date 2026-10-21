import re
from dataclasses import dataclass

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.llm.models import LlmTask, embedding_model, structured_llm
from src.models import CanonicalAttribute

# Embedding similarity (cosine, 0..1 in practice) below this = clearly a different
# attribute, so we create a new one without asking GPT. A starting guess:
# measure it on labeled pairs in Feature 13 before trusting it.
CANDIDATE_SIMILARITY = 0.55
CONFIRM_MIN_CONFIDENCE = 0.8  # GPT's "same" or "different" must be at least this sure
NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


@dataclass
class CatalogMatch:
    canonical: CanonicalAttribute | None  # None = waiting for a person to decide
    mapping_confidence: float | None
    review_reason: str | None = None


class MatchDecision(BaseModel):
    same_attribute: bool = Field(
        description="True if both names refer to the same compliance topic, even if worded "
        "differently or one is the negation of the other ('Latex-free' vs 'Contains natural rubber latex')."
    )
    confidence: float = Field(description="0 to 1")
    reason: str


def attribute_key(name: str) -> str:
    """"RoHS compliant" -> "rohs_compliant" (the stable key in canonical_attributes.name)."""
    return NON_ALPHANUMERIC.sub("_", name.casefold()).strip("_")


class AttributeCatalog:
    """The catalog loaded once per pipeline run, with its embeddings cached.

    A class (rather than plain functions) because it carries state across all the
    claims of a file: the loaded catalog, its embeddings, and the entries
    created during this run, so the second document reuses what the first one added.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._entries = list(session.scalars(select(CanonicalAttribute)))
        self._embedder = embedding_model()
        self._vectors: np.ndarray | None = None  # one row per entry, filled on first use

    # --- Lookup steps, cheapest first ---

    def _exact(self, topic: str, name_as_written: str) -> CanonicalAttribute | None:
        wanted = {attribute_key(topic), attribute_key(name_as_written)}
        for entry in self._entries:
            if entry.name in wanted or wanted & {attribute_key(alias) for alias in entry.aliases}:
                return entry
        return None

    def _catalog_vectors(self) -> np.ndarray:
        if self._vectors is None:
            self._vectors = np.array(self._embedder.embed_documents([e.display_name for e in self._entries]))
        return self._vectors

    def _confirm(self, topic: str, name_as_written: str, candidate: CanonicalAttribute) -> MatchDecision:
        known = ", ".join([candidate.display_name, *candidate.aliases])
        messages = [
            ("system", "You decide whether two compliance attribute names mean the same topic."),
            ("human", f"Existing attribute: {known}\nNew attribute: {topic} (written as '{name_as_written}')"),
        ]
        return structured_llm(LlmTask.CONFIRM_ATTRIBUTE_MATCH, MatchDecision).invoke(messages)

    # --- Changes to the catalog ---

    def _add_alias(self, entry: CanonicalAttribute, alias: str) -> None:
        if attribute_key(alias) not in {attribute_key(a) for a in [entry.display_name, *entry.aliases]}:
            entry.aliases = [*entry.aliases, alias]  # assign a new list so it gets saved

    def _create(self, topic: str, name_as_written: str) -> CatalogMatch:
        entry = CanonicalAttribute(
            name=attribute_key(topic),
            display_name=topic,
            aliases=[name_as_written] if attribute_key(name_as_written) != attribute_key(topic) else [],
        )
        self._session.add(entry)
        self._session.flush()  # entry.id is needed by the attribute row that points at it
        self._entries.append(entry)
        if self._vectors is not None:
            vector = np.array([self._embedder.embed_query(topic)])
            self._vectors = np.vstack([self._vectors, vector])
        return CatalogMatch(entry, 1.0)

    # --- The one public method ---

    def match(self, topic: str, name_as_written: str) -> CatalogMatch:
        """Find (or create) the canonical attribute for a discovered claim (Feature 6, step 2)."""
        exact = self._exact(topic, name_as_written)
        if exact is not None:
            self._add_alias(exact, name_as_written)
            return CatalogMatch(exact, 1.0)
        if not self._entries:
            return self._create(topic, name_as_written)

        # OpenAI embeddings have length 1, so a dot product IS the cosine similarity.
        similarities = self._catalog_vectors() @ np.array(self._embedder.embed_query(topic))
        best_index = int(np.argmax(similarities))
        best, similarity = self._entries[best_index], float(similarities[best_index])
        if similarity < CANDIDATE_SIMILARITY:
            return self._create(topic, name_as_written)

        decision = self._confirm(topic, name_as_written, best)
        confidence = max(0.0, min(1.0, decision.confidence))
        if confidence >= CONFIRM_MIN_CONFIDENCE and decision.same_attribute:
            self._add_alias(best, name_as_written)
            return CatalogMatch(best, round(confidence, 4))
        if confidence >= CONFIRM_MIN_CONFIDENCE:
            return self._create(topic, name_as_written)

        # Borderline: leave it unmapped and ask a person (Feature 6 criterion).
        return CatalogMatch(
            None,
            round(confidence, 4),
            f"Is '{name_as_written}' the same attribute as '{best.display_name}'? "
            f"(similarity {similarity:.2f}; {decision.reason})",
        )