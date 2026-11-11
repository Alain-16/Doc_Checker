"""Re-chunk and re-embed processed files from their stored pages. No OCR is re-run.

Use it after changing the chunking settings, or to try other ones without
touching .env (the flags override the settings for this run only).

    uv run python scripts/reindex.py                       # every processed file, settings from .env
    uv run python scripts/reindex.py --file <vendor_file_id>
    uv run python scripts/reindex.py --strategy structure --max-tokens 1024 --overlap-percent 20
    uv run python scripts/reindex.py --no-embed            # chunks only, no OpenAI cost
"""

import argparse
import sys
import time
import uuid
from pathlib import Path

# Make `src` importable when the script is run from the backend folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from src.config.database import SessionLocal
from src.config.settings import get_settings
from src.models import VendorFile
from src.models.chunk import ChunkingStrategy
from src.models.vendor_file import ProcessingStatus
from src.retrieval.indexing import chunk_vendor_file, embed_chunks


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", type=uuid.UUID, help="one vendor_file id (default: every processed file)")
    parser.add_argument("--strategy", type=ChunkingStrategy, default=settings.chunking_strategy,
                        choices=list(ChunkingStrategy))
    parser.add_argument("--max-tokens", type=int, default=settings.chunk_max_tokens)
    parser.add_argument("--overlap-percent", type=int, default=settings.chunk_overlap_percent)
    parser.add_argument("--no-embed", action="store_true", help="save chunks without embedding them")
    args = parser.parse_args()

    with SessionLocal() as session:
        query = select(VendorFile).where(VendorFile.processing_status == ProcessingStatus.COMPLETED)
        if args.file:
            query = query.where(VendorFile.id == args.file)
        vendor_files = session.scalars(query.order_by(VendorFile.created_at)).all()
        print(f"{len(vendor_files)} file(s); strategy={args.strategy} max_tokens={args.max_tokens} "
              f"overlap={args.overlap_percent}%")

        for vendor_file in vendor_files:
            started = time.perf_counter()
            made = chunk_vendor_file(session, vendor_file, args.strategy, args.max_tokens, args.overlap_percent)
            session.commit()
            if not args.no_embed:
                embed_chunks(session, vendor_file)
            print(f"  {vendor_file.filename}: {made} chunks in {time.perf_counter() - started:.1f}s")


if __name__ == "__main__":
    main()
