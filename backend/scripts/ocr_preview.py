"""Read a local PDF with the pipeline's page reader and print the results.

Nothing is saved: no database rows, no upload to object storage.

    uv run python scripts/ocr_preview.py path/to/file.pdf
    uv run python scripts/ocr_preview.py path/to/file.pdf --pages 1-5 --text
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Make `src` importable when the script is run from the backend folder.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymupdf  # noqa: E402

from src.config.settings import get_settings  # noqa: E402
from src.ingestion.page_reading import needs_review, read_page  # noqa: E402


def page_numbers(spec: str | None, page_count: int) -> list[int]:
    """'3' -> [3], '2-5' -> [2, 3, 4, 5], None -> every page."""
    if spec is None:
        return list(range(1, page_count + 1))
    first, _, last = spec.partition("-")
    return list(range(int(first), int(last or first) + 1))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--pages", help="one page or a range, e.g. 7 or 1-5 (default: all)")
    parser.add_argument("--text", action="store_true", help="print each page's full text")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    print(f"review threshold={settings.ocr_confidence_threshold:.2f}")

    started = time.perf_counter()
    flagged, figures = [], []
    with pymupdf.open(args.pdf) as pdf:
        for number in page_numbers(args.pages, pdf.page_count):
            page_started = time.perf_counter()
            reading = read_page(pdf[number - 1])
            seconds = time.perf_counter() - page_started
            if needs_review(reading, settings.ocr_confidence_threshold):
                flagged.append(number)
            is_figure = reading.layout.get("figure", False)
            if is_figure:
                figures.append(number)
            print(
                f"page {number:3d}  {seconds:5.1f}s  {reading.source_type:8s} {reading.engine:20s} "
                f"confidence={reading.confidence:.2f}  blocks={len(reading.layout['blocks'])}"
                + (f"  FIGURE (dropped {reading.layout['dropped_lines']} junk lines)" if is_figure else "")
            )
            if args.text:
                print(reading.text.strip() + "\n" + "-" * 80)

    print(f"total {time.perf_counter() - started:.0f}s")
    print(f"figures: {figures or 'none'}")
    print(f"pages that would go to review: {flagged or 'none'}")


if __name__ == "__main__":
    main()
