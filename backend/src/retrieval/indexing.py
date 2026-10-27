"""Pipeline stages that build the search index: cut documents into chunks, then embed them."""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.llm.models import EMBEDDING_MODEL, embedding_model
from src.models import Chunk, Document, Page, VendorFile
from src.models.chunk import ChunkingStrategy
from src.retrieval.chunking import chunk_document, document_content

# Chunks sent to OpenAI per embedding request. Each batch is committed, so a
# crash or a rate limit loses at most one batch of work.
EMBEDDING_BATCH_SIZE = 64


# =============================================================================
# Unit 9: the chunk stage
# =============================================================================


def chunk_vendor_file(
    session: Session,
    vendor_file: VendorFile,
    strategy: ChunkingStrategy,
    max_tokens: int,
    overlap_percent: int,
) -> int:
    """Replace the chunks of every document in the file. Returns how many were made.

    Only one strategy is kept in the table at a time (your decision, 2026-10-27),
    so a document's old chunks are deleted whatever strategy made them. That
    also makes a re-run safe: it replaces instead of adding duplicates.
    """
    overlap_tokens = max_tokens * overlap_percent // 100  # 512 x 10% = 51 tokens
    pages = session.scalars(select(Page).where(Page.vendor_file_id == vendor_file.id)).all()
    documents = session.scalars(select(Document).where(Document.vendor_file_id == vendor_file.id)).all()

    made = 0
    for document in documents:
        session.execute(delete(Chunk).where(Chunk.document_id == document.id))
        document_pages = [page for page in pages if document.start_page <= page.page_number <= document.end_page]
        drafts = chunk_document(document_content(document_pages), strategy, max_tokens, overlap_tokens)
        for index, draft in enumerate(drafts):
            session.add(
                Chunk(
                    document_id=document.id,
                    chunking_strategy=strategy,
                    chunk_index=index,
                    page_start=draft.page_start,
                    page_end=draft.page_end,
                    section_name=draft.section_name,
                    content=draft.content,
                    token_count=draft.token_count,
                    chunk_metadata=draft.metadata,
                )
            )
        made += len(drafts)
    return made


def chunk_documents(session: Session, vendor_file: VendorFile) -> None:
    """Pipeline stage: chunk every document of the file with the configured strategy."""
    settings = get_settings()
    chunk_vendor_file(
        session, vendor_file, settings.chunking_strategy, settings.chunk_max_tokens, settings.chunk_overlap_percent
    )


# =============================================================================
# Unit 10: the embedding stage
# =============================================================================


def embed_chunks(session: Session, vendor_file: VendorFile) -> None:
    """Pipeline stage: embed the file's chunks that have no embedding yet.

    Commits after every batch (like read_pages does per page), so a resume
    only embeds what is still missing and never pays twice for the same chunk.
    """
    embedder = embedding_model()
    while True:
        batch = session.scalars(
            select(Chunk)
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.vendor_file_id == vendor_file.id, Chunk.embedding.is_(None))
            .order_by(Chunk.document_id, Chunk.chunk_index)
            .limit(EMBEDDING_BATCH_SIZE)
        ).all()
        if not batch:
            return
        vectors = embedder.embed_documents([chunk.content for chunk in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_model = EMBEDDING_MODEL
        session.commit()
