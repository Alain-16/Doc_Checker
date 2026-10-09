import uuid
from typing import TYPE_CHECKING, Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, Computed, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models.base import EMPTY_JSONB, Base

if TYPE_CHECKING:
    from src.models.document import Document

# text-embedding-3-large shortened to 1536 numbers. Postgres can only index
# vectors of up to 2000 dimensions, so the full 3072 couldn't be indexed.
EMBEDDING_DIMENSIONS = 1536
SEARCH_TEXT_CONFIG = "simple"

class Chunk(Base):
        __tablename__ = "chunks"
        __table_args__ =(
        # One position per document per strategy. Also indexes document_id.
        UniqueConstraint("document_id", "chunking_strategy", "chunk_index"),
        CheckConstraint("page_start >= 1 AND page_start <= page_end", name="page_range_valid"),
        CheckConstraint("chunk_index >= 0", name="chunk_index_not_negative"),
        CheckConstraint("token_count > 0", name="token_count_positive"),
        # An embedding is always stored together with the model that produced it.
        CheckConstraint(
            "(embedding IS NULL) = (embedding_model IS NULL)",
            name="embedding_has_model",
        ),

        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},

        ),

        Index(
            "ix_chunks_search_vector_gin", "search_vector", postgresql_using="gin"
        )
         )

        document_id: Mapped[uuid.UUID] = mapped_column(
            ForeignKey("documents.id", ondelete="RESTRICT")
        )
        chunking_strategy: Mapped[str] = mapped_column(index=True)
        chunk_index: Mapped[int]

        page_start: Mapped[int]
        page_end: Mapped[int]
        # e.g. "Natural Rubber Latex". Empty for fixed-size chunks that ignore sections.
        section_name: Mapped[str | None]
        content: Mapped[str] = mapped_column(Text)
        token_count: Mapped[int]

        # Empty until the embedding stage runs, so that stage can resume on its own.
        # Reading it back gives a numpy array of 1536 numbers, hence Any.
        embedding: Mapped[Any] = mapped_column(Vector(EMBEDDING_DIMENSIONS), nullable=True)
        embedding_model: Mapped[str | None]

        # Computed: Postgres builds this from `content` on every insert/update.
        # Our code never writes it, so it can never disagree with the text.
        search_vector: Mapped[str] = mapped_column(
            TSVECTOR,
            Computed(f"to_tsvector('{SEARCH_TEXT_CONFIG}', content)", persisted=True),
        )

        # Facts about the chunk's structure, e.g. {"is_table": true}. The column is
        # named "metadata" but the attribute can't be: SQLAlchemy reserves that name.
        chunk_metadata: Mapped[dict[str, Any]] = mapped_column(
            "metadata", default=dict, server_default=EMPTY_JSONB
        )

        # One-way link: code goes from a chunk to its document, never the reverse,
        # so Document doesn't need a `chunks` list.
        document: Mapped["Document"] = relationship()
