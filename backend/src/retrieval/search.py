"""Hybrid search over the chunk index: keyword + vector search, fused by rank."""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import Select, Text, cast, func, select
from sqlalchemy.orm import Session

from src.llm.models import embedding_model
from src.models import Chunk, Component, Document, DocumentType, VendorFile
from src.models.chunk import SEARCH_TEXT_CONFIG

# Each search method returns this many candidates before they are fused.
CANDIDATES_PER_METHOD = 50
# Reciprocal rank fusion: a chunk scores 1 / (RRF_K + rank) in each list it
# appears in. 60 is the value from the original paper (Cormack et al., 2009);
# it stops the first one or two places from outweighing everything else.
RRF_K = 60
# Our text config is "simple", which keeps every word. Without this list,
# "Is it RoHS compliant?" ranked long chunks full of "is" and "it" above the
# RoHS sections (16th-20th place, measured). Only words that never identify
# a compliance topic go here.
QUESTION_STOP_WORDS = frozenset(
    "a an and any are as at be been by can could do does did for from has have how i in is it its "
    "me my of on or our should that the their there these this those to was we were what when where "
    "which who why will with would you your".split()
)
PUNCTUATION = "?!.,;:\"'()"


@dataclass
class SearchFilters:
    """What to search in. Empty lists mean "no restriction"."""

    document_ids: list[uuid.UUID] = field(default_factory=list)
    vendor_ids: list[uuid.UUID] = field(default_factory=list)
    component_ids: list[uuid.UUID] = field(default_factory=list)
    document_type_names: list[str] = field(default_factory=list)  # e.g. ["compliance_bulletin"]
    # Superseded files hold outdated versions, so they are left out unless asked
    # for (PRD Feature 11: "excluded unless the user asks about history").
    include_superseded: bool = False


@dataclass
class SearchHit:
    chunk: Chunk
    score: float  # the fused score: higher is better
    keyword_rank: int | None  # 1 = best keyword match; None = not found by keywords
    vector_rank: int | None  # 1 = closest in meaning; None = not among the candidates


# =============================================================================
# Unit 11: hybrid search
# =============================================================================


def filtered(query: Select, filters: SearchFilters) -> Select:
    """Restrict a chunk query by joining chunk -> document -> vendor_file.

    Vendor, component, type and superseded flag are never copied onto chunks
    (your decision, 2026-10-23); they are read here, so they are always current.
    """
    query = query.join(Document, Chunk.document_id == Document.id).join(
        VendorFile, Document.vendor_file_id == VendorFile.id
    )
    if filters.document_ids:
        query = query.where(Document.id.in_(filters.document_ids))
    if filters.component_ids:
        query = query.where(VendorFile.component_id.in_(filters.component_ids))
    if filters.vendor_ids:
        query = query.join(Component, VendorFile.component_id == Component.id).where(
            Component.vendor_id.in_(filters.vendor_ids)
        )
    if filters.document_type_names:
        query = query.join(DocumentType, Document.document_type_id == DocumentType.id).where(
            DocumentType.name.in_(filters.document_type_names)
        )
    if not filters.include_superseded:
        query = query.where(VendorFile.superseded_by_id.is_(None))
    return query


def content_words(text: str) -> str:
    """The question without its question words: "Is it RoHS compliant?" -> "RoHS compliant".

    Split on spaces only, so identifiers like "4432/50" and "<381>" stay whole.
    """
    return " ".join(word for word in text.split() if word.strip(PUNCTUATION).lower() not in QUESTION_STOP_WORDS)


def any_word_query(text: str):
    """A full-text query matching chunks that contain ANY of the question's content words.

    plainto_tsquery joins words with & (all must appear), so "contain latex"
    would miss a chunk saying "not made with latex". Swapping & for | (or) lets
    ts_rank do the work: chunks with more of the words rank higher.
    """
    all_words = func.plainto_tsquery(SEARCH_TEXT_CONFIG, content_words(text))  # 'contain' & 'latex'
    return func.to_tsquery(SEARCH_TEXT_CONFIG, func.replace(cast(all_words, Text), " & ", " | "))


def keyword_search(session: Session, text: str, filters: SearchFilters, limit: int) -> list[uuid.UUID]:
    """Chunk ids ranked by PostgreSQL full-text search (catches exact terms like "USP <381>")."""
    query = any_word_query(text)
    rank = func.ts_rank(Chunk.search_vector, query)
    statement = filtered(select(Chunk.id), filters).where(Chunk.search_vector.op("@@")(query))
    return list(session.scalars(statement.order_by(rank.desc()).limit(limit)))


def vector_search(session: Session, vector: list[float], filters: SearchFilters, limit: int) -> list[uuid.UUID]:
    """Chunk ids ranked by meaning: cosine distance between embeddings (catches paraphrases)."""
    statement = filtered(select(Chunk.id), filters).where(Chunk.embedding.is_not(None))
    return list(session.scalars(statement.order_by(Chunk.embedding.cosine_distance(vector)).limit(limit)))


def reciprocal_rank_fusion(rankings: list[list[uuid.UUID]]) -> dict[uuid.UUID, float]:
    """Combine ranked lists into one score per id: the sum of 1 / (RRF_K + rank).

    Only ranks are used, never the raw scores, because ts_rank and cosine
    distance are on different scales and can't be added directly.
    """
    scores: dict[uuid.UUID, float] = {}
    for ranking in rankings:
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
    return scores


def hybrid_search(
    session: Session,
    text: str,
    filters: SearchFilters | None = None,
    limit: int = 10,
    vector: list[float] | None = None,
) -> list[SearchHit]:
    """The best `limit` chunks for a question, by keyword and meaning together.

    `vector` is the text's embedding when the caller already has it: a search
    repeated over many documents then embeds the text once, not once per search.
    """
    filters = filters or SearchFilters()
    vector = vector if vector is not None else embedding_model().embed_query(text)
    keyword_ids = keyword_search(session, text, filters, CANDIDATES_PER_METHOD)
    vector_ids = vector_search(session, vector, filters, CANDIDATES_PER_METHOD)

    scores = reciprocal_rank_fusion([keyword_ids, vector_ids])
    best = sorted(scores, key=scores.__getitem__, reverse=True)[:limit]
    chunks = {chunk.id: chunk for chunk in session.scalars(select(Chunk).where(Chunk.id.in_(best)))}
    return [
        SearchHit(
            chunk=chunks[chunk_id],
            score=scores[chunk_id],
            keyword_rank=keyword_ids.index(chunk_id) + 1 if chunk_id in keyword_ids else None,
            vector_rank=vector_ids.index(chunk_id) + 1 if chunk_id in vector_ids else None,
        )
        for chunk_id in best
    ]
