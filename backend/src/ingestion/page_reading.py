import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pymupdf
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import get_settings
from src.ingestion.ocr import OcrResult, clean_scan, ocr_image
from src.ingestion.storage import download_original
from src.ingestion.tables import (
    erase_lines,
    find_digital_tables,
    find_grid_cells,
    find_scanned_tables,
    grid_lines,
    outside_tables,
)
from src.models import Page, ReviewItem, VendorFile
from src.models.review import ReviewItemKind
from src.models.vendor_file import PageSourceType

NATIVE_ENGINE = "pymupdf"
DIGITAL_CONFIDENCE = 1.0  # text taken straight from the PDF is exactly what was written

# --- Routing: is the text layer usable? (Feature 2 business logic) ---
MIN_TEXT_CHARS = 40  # fewer real characters than this = treat the page as scanned
MIN_READABLE_SHARE = 0.6  # below this share of letters/digits = garbage text layer

# --- Mixed pages: which embedded images might contain text worth OCR-ing ---
MIN_IMAGE_REGION_WIDTH_PT = 72  # 1 inch (PDF units are points, 72 per inch)
MIN_IMAGE_REGION_HEIGHT_PT = 18  # a quarter inch, about one line of text
# An image region already overlaid by this many text-layer words was OCR'd by the
# scanner; OCR-ing it again would duplicate its text.
COVERED_REGION_MIN_WORDS = 3

# --- Figures: charts and graphs scanned as images ---
# OCR on a chart reads axis labels and sideways text as junk. Such a page is a
# figure, not a reading problem, so it isn't sent to review. Measured on a real
# bundle: charts had 52-78% junk lines and under 40 well-read characters; text
# pages (signature pages included) had at most 28% junk and 290+ good characters.
JUNK_LINE_BELOW_CONFIDENCE = 0.5
FIGURE_MIN_JUNK_LINE_SHARE = 0.5
FIGURE_MAX_GOOD_CHARS = 100
# On a figure page, only lines read at least this well are kept (titles such as
# "Attachment 3"); the junk would only mislead the later LLM stages.
FIGURE_KEEP_LINE_CONFIDENCE = 0.8

RENDER_DPI = 300  # OCR engines are trained on roughly 300 dpi scans
POINTS_PER_INCH = 72


@dataclass
class PageReading:
    """The engine-independent page representation (PRD Architecture §4)."""

    text: str
    source_type: PageSourceType
    engine: str
    confidence: float
    layout: dict[str, Any] = field(default_factory=dict)



# native extraction + routing



def has_usable_text(text: str) -> bool:
    """True when the text layer has enough real characters to trust."""
    visible = [char for char in text if not char.isspace()]
    if len(visible) < MIN_TEXT_CHARS:
        return False
    readable = sum(char.isalnum() for char in visible)
    return readable / len(visible) >= MIN_READABLE_SHARE


def native_blocks(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Text blocks from the PDF's own text layer, with position and font size.

    The font size helps segmentation spot titles (big text at the top of a page).
    """
    blocks = []
    for block in page.get_text("dict")["blocks"]:
        if block["type"] != 0:  # type 1 = image block, no text
            continue
        spans = [span for line in block["lines"] for span in line["spans"]]
        text = " ".join(span["text"].strip() for span in spans if span["text"].strip())
        if text:
            blocks.append(
                {
                    "bbox": [round(v, 1) for v in block["bbox"]],
                    "text": text,
                    "size": round(max(span["size"] for span in spans), 1),
                    "source": "native",
                }
            )
    return blocks


def image_regions(page: pymupdf.Page) -> list[pymupdf.Rect]:
    """Embedded images big enough to hold text (signatures, stamps, pasted scans)."""
    regions = []
    for image in page.get_image_info():
        rect = pymupdf.Rect(image["bbox"]) & page.rect  # & = keep the part on the page
        if rect.width >= MIN_IMAGE_REGION_WIDTH_PT and rect.height >= MIN_IMAGE_REGION_HEIGHT_PT:
            regions.append(rect)
    return regions


def route_page(native_text: str, regions: list[pymupdf.Rect]) -> PageSourceType:
    """Decide how to read the page: digital, scanned, or mixed."""
    if not has_usable_text(native_text):
        return PageSourceType.SCANNED
    if regions:
        return PageSourceType.MIXED
    return PageSourceType.DIGITAL



# rendering for OCR, and reading each kind of page



def render_gray(page: pymupdf.Page, clip: pymupdf.Rect | None = None) -> np.ndarray:
    """Draw the page (or one area of it) as a grayscale image for OCR."""
    pixmap = page.get_pixmap(dpi=RENDER_DPI, colorspace=pymupdf.csGRAY, clip=clip)
    # pixmap.samples is the raw pixel bytes; reshape them into rows x columns.
    return np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width)


def ocr_blocks(result: OcrResult, origin: pymupdf.Point) -> list[dict[str, Any]]:
    """Convert OCR lines into the same block shape and coordinates as native_blocks.

    OCR boxes are in pixels of the rendered image; native boxes are in PDF points.
    Dividing by the render scale and adding the region's top-left corner puts
    both in page points, so later stages don't care which engine read a block.
    """
    scale = RENDER_DPI / POINTS_PER_INCH
    blocks = []
    for line in result.lines:
        x0, y0, x1, y1 = (value / scale for value in line.bbox)
        blocks.append(
            {
                "bbox": [round(x0 + origin.x, 1), round(y0 + origin.y, 1), round(x1 + origin.x, 1), round(y1 + origin.y, 1)],
                "text": line.text,
                # No font sizes from OCR: line height in points is a close stand-in.
                "size": round(y1 - y0, 1),
                "source": result.engine,
                "confidence": round(line.confidence, 3),
                "handwriting": line.handwriting,
            }
        )
    return blocks


def is_figure(result: OcrResult) -> bool:
    """True when the OCR looks like a chart: mostly junk lines, little real text."""
    if not result.lines:
        return False
    junk_lines = sum(line.confidence < JUNK_LINE_BELOW_CONFIDENCE for line in result.lines)
    good_chars = sum(
        len(line.text) for line in result.lines if line.confidence >= FIGURE_KEEP_LINE_CONFIDENCE
    )
    return junk_lines / len(result.lines) >= FIGURE_MIN_JUNK_LINE_SHARE and good_chars < FIGURE_MAX_GOOD_CHARS


def needs_review(reading: PageReading, threshold: float) -> bool:
    """Low-confidence pages go to review, except figures (their text is expected junk)."""
    return reading.confidence < threshold and not reading.layout.get("figure", False)


def is_covered_by_text(page: pymupdf.Page, region: pymupdf.Rect) -> bool:
    """True when text-layer words already sit on top of this image region."""
    words = page.get_text("words", clip=region)
    return len(words) >= COVERED_REGION_MIN_WORDS


def read_page(page: pymupdf.Page) -> PageReading:
    """Read one page, choosing native extraction, OCR, or both."""
    native_text = page.get_text("text")
    regions = image_regions(page)
    source_type = route_page(native_text, regions)

    page_area = page.rect.width * page.rect.height
    layout: dict[str, Any] = {
        "width": round(page.rect.width, 1),
        "height": round(page.rect.height, 1),
        # Engineering drawings are made of thousands of vector lines: a layout signal.
        "vector_paths": len(page.get_drawings()),
        "image_coverage": round(min(1.0, sum(r.width * r.height for r in regions) / page_area), 3),
    }

    # --- Scanned: OCR the whole page ---
    if source_type == PageSourceType.SCANNED:
        cleaned = clean_scan(render_gray(page))
        # Ruled lines are found first, then erased so OCR doesn't read them as "|".
        rules = grid_lines(cleaned)
        grids = find_grid_cells(rules)
        result = ocr_image(erase_lines(cleaned, rules))
        tables = []
        if is_figure(result):
            kept = [line for line in result.lines if line.confidence >= FIGURE_KEEP_LINE_CONFIDENCE]
            layout["figure"] = True
            layout["dropped_lines"] = len(result.lines) - len(kept)
            result = OcrResult(result.engine, kept)
        else:
            # Not on figures: chart axes and gridlines look like table rules.
            tables = find_scanned_tables(grids, result, pixels_per_point=RENDER_DPI / POINTS_PER_INCH)
        layout["tables"] = tables
        layout["blocks"] = outside_tables(ocr_blocks(result, page.rect.tl), tables)
        return PageReading(result.text, source_type, result.engine, result.confidence, layout)

    # Ruled tables in the text layer, for digital and mixed pages alike.
    tables = find_digital_tables(page)
    layout["tables"] = tables
    blocks = outside_tables(native_blocks(page), tables)

    # --- Digital: the text layer is all we need ---
    if source_type == PageSourceType.DIGITAL:
        layout["blocks"] = blocks
        return PageReading(native_text, source_type, NATIVE_ENGINE, DIGITAL_CONFIDENCE, layout)

    # --- Mixed: text layer + OCR of image regions that don't already have text ---
    texts, confidences, engines = [native_text], [], {NATIVE_ENGINE}
    for region in regions:
        if is_covered_by_text(page, region):
            continue
        result = ocr_image(clean_scan(render_gray(page, clip=region)))
        if not result.lines:
            continue  # a logo or photo with no text: nothing to add
        blocks.extend(ocr_blocks(result, region.tl))
        texts.append(result.text)
        confidences.append(result.confidence)
        engines.add(result.engine)

    layout["blocks"] = blocks
    # The page is only as trustworthy as its weakest OCR'd region (often a signature).
    confidence = min(confidences, default=DIGITAL_CONFIDENCE)
    return PageReading("\n".join(texts), source_type, "+".join(sorted(engines)), confidence, layout)



# the pipeline stage that saves pages rows



def read_pages(session: Session, vendor_file: VendorFile) -> None:
    """Pipeline stage: read every page of the file and save one pages row each.

    Commits after every page, so if page 312 crashes, a resume starts at 312
    instead of redoing 311 pages of OCR.
    """
    already_read = set(
        session.scalars(select(Page.page_number).where(Page.vendor_file_id == vendor_file.id))
    )
    threshold = get_settings().ocr_confidence_threshold

    with tempfile.TemporaryDirectory() as temp_dir:
        local_path = Path(temp_dir) / "original.pdf"
        download_original(vendor_file.storage_key, local_path)

        # PyMuPDF loads one page at a time as we loop, so a 500-page file
        # never sits in memory all at once (Feature 1 edge case).
        with pymupdf.open(local_path) as pdf:
            for index, pdf_page in enumerate(pdf):
                page_number = index + 1
                if page_number in already_read:
                    continue

                reading = read_page(pdf_page)
                page = Page(
                    vendor_file_id=vendor_file.id,
                    page_number=page_number,
                    # Postgres text can't store the NUL character; some PDFs contain it.
                    text=reading.text.replace("\x00", ""),
                    source_type=reading.source_type,
                    extraction_engine=reading.engine,
                    confidence=round(reading.confidence, 4),
                    layout_data=reading.layout,
                )
                session.add(page)
                session.flush()  # send the INSERT now so page.id exists for the review item

                if needs_review(reading, threshold):
                    session.add(
                        ReviewItem(
                            vendor_file_id=vendor_file.id,
                            page_number=page_number,
                            item_kind=ReviewItemKind.PAGE_TEXT,
                            target_table=Page.__tablename__,
                            target_record_id=page.id,
                            reason=(
                                f"Page reading confidence {reading.confidence:.2f} is below "
                                f"{threshold:.2f} ({reading.engine}, {reading.source_type})."
                            ),
                        )
                    )
                session.commit()