import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Document, Page, ReviewItem, VendorFile
from src.models.review import ReviewItemKind

TITLE_ZONE = 0.25  # titles sit in the top quarter
HEADER_ZONE = 0.20  # document numbers and revisions live in headers...
FOOTER_ZONE = 0.15  # ...and footers
TITLE_SIZE_RATIO = 1.25  # a title is at least 25% bigger than the page's usual text
TITLE_MIN_CHARS, TITLE_MAX_CHARS = 4, 120
DRAWING_MIN_VECTOR_PATHS = 500  # engineering drawings are thousands of drawn lines

# --- How much each signal counts. Starting guesses: tune them against labeled
# files in Feature 13 rather than by feel. ---
SIGNAL_WEIGHTS = {
    "page_counter_reset": 0.60,  # "Page 1 of 7"
    "previous_counter_completed": 0.50,  # the page before said "Page 7 of 7"
    "new_title": 0.35,
    "document_number_change": 0.35,
    "document_number_appears": 0.15,
    "layout_change": 0.20,
    "page_counter_continues": -0.60,  # "Page 3 of 7" right after "Page 2 of 7"
    "same_document_number": -0.30,
}
BOUNDARY_SCORE = 0.5  # a total at or above this starts a new document
REVIEW_BELOW_CONFIDENCE = 0.7

PAGE_COUNTER = re.compile(r"\bpage\s*(\d{1,3})\s*(?:of|/)\s*(\d{1,3})\b", re.IGNORECASE)
DOCUMENT_NUMBER = re.compile(
    r"\b(?:doc(?:ument)?|bulletin|certificate|drawing|dwg|ref(?:erence)?)\.?\s*"
    r"(?:no\.?|number|#)\s*[:.]?\s*([A-Z0-9][A-Z0-9./-]{2,30})",
    re.IGNORECASE,
)
REVISION = re.compile(r"\brev(?:ision)?\.?\s*[:.]?\s*([A-Z0-9]{1,4})\b", re.IGNORECASE)
TITLE_WORDS = re.compile(
    r"\b(certificate|bulletin|statement|declaration|specification|drawing|report|"
    r"characteristics|analysis|letter)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PageSignals:
    """What one page tells us about where documents start (Unit 11)."""

    page_number: int
    title: str | None
    counter: tuple[int, int] | None  # (3, 7) for "Page 3 of 7"
    document_number: str | None
    revision: str | None
    layout_kind: str  # "drawing", "scanned" or "text"


@dataclass
class BoundaryDecision:
    """Does a new document start on this page? With the evidence (Unit 12)."""

    page_number: int
    starts_document: bool
    score: float
    confidence: float
    signals: list[str] = field(default_factory=list)


# =============================================================================
# boundary signals, read from each page's text and layout
# =============================================================================


def find_title(blocks: list[dict[str, Any]], page_height: float) -> str | None:
    """The first big or title-worded line in the top of the page, if any."""
    if not blocks:
        return None
    usual_size = statistics.median(block["size"] for block in blocks)
    top_blocks = sorted(
        (block for block in blocks if block["bbox"][1] < page_height * TITLE_ZONE),
        key=lambda block: block["bbox"][1],
    )
    for block in top_blocks:
        text = " ".join(block["text"].split())
        if not TITLE_MIN_CHARS <= len(text) <= TITLE_MAX_CHARS:
            continue
        if block["size"] >= usual_size * TITLE_SIZE_RATIO or TITLE_WORDS.search(text):
            return text
    return None


def header_footer_text(blocks: list[dict[str, Any]], page_height: float) -> str:
    """Text from the top and bottom strips only. Document numbers in body text
    are usually citations of OTHER documents, so we ignore them."""
    return "\n".join(
        block["text"]
        for block in blocks
        if block["bbox"][1] < page_height * HEADER_ZONE
        or block["bbox"][3] > page_height * (1 - FOOTER_ZONE)
    )


def layout_kind(page: Page) -> str:
    if page.layout_data.get("vector_paths", 0) >= DRAWING_MIN_VECTOR_PATHS:
        return "drawing"
    return "scanned" if page.source_type == "scanned" else "text"


def page_signals(page: Page) -> PageSignals:
    blocks = page.layout_data.get("blocks", [])
    height = page.layout_data.get("height", 0) or 1
    margins = header_footer_text(blocks, height)

    counter_match = PAGE_COUNTER.search(page.text)
    number_match = DOCUMENT_NUMBER.search(margins)
    revision_match = REVISION.search(margins)
    return PageSignals(
        page_number=page.page_number,
        title=find_title(blocks, height),
        counter=(int(counter_match[1]), int(counter_match[2])) if counter_match else None,
        document_number=number_match[1].upper() if number_match else None,
        revision=revision_match[1].upper() if revision_match else None,
        layout_kind=layout_kind(page),
    )


# =============================================================================
# combine signals into decisions, then into page ranges
# =============================================================================


def fired_signals(previous: PageSignals, current: PageSignals) -> list[str]:
    """Names of the signals that fire when moving from `previous` to `current`."""
    fired = []
    if current.counter and current.counter[0] == 1:
        fired.append("page_counter_reset")
    if previous.counter and previous.counter[0] == previous.counter[1]:
        fired.append("previous_counter_completed")
    if (
        current.counter
        and previous.counter
        and current.counter == (previous.counter[0] + 1, previous.counter[1])
    ):
        fired.append("page_counter_continues")
    if current.title and current.title.casefold() != (previous.title or "").casefold():
        fired.append("new_title")
    if current.document_number and previous.document_number:
        same = current.document_number == previous.document_number
        fired.append("same_document_number" if same else "document_number_change")
    elif current.document_number:
        fired.append("document_number_appears")
    if current.layout_kind != previous.layout_kind:
        fired.append("layout_change")
    return fired


def decide_boundaries(signals: list[PageSignals]) -> list[BoundaryDecision]:
    """One decision per page. Page 1 always starts a document."""
    decisions = [BoundaryDecision(signals[0].page_number, True, 1.0, 1.0, ["first_page"])]
    for previous, current in zip(signals, signals[1:]):
        fired = fired_signals(previous, current)
        score = sum(SIGNAL_WEIGHTS[name] for name in fired)
        # Confidence = distance from the decision line. A score right on 0.5 is a
        # coin toss (0.5); far above or below it is a clear call (up to 1.0).
        confidence = min(1.0, 0.5 + abs(score - BOUNDARY_SCORE))
        decisions.append(
            BoundaryDecision(current.page_number, score >= BOUNDARY_SCORE, round(score, 2), round(confidence, 2), fired)
        )
    return decisions


def group_into_segments(decisions: list[BoundaryDecision]) -> list[list[BoundaryDecision]]:
    """Cut the page sequence at every "starts_document" decision.

    Every page lands in exactly one segment by construction (Feature 3 criterion).
    """
    segments: list[list[BoundaryDecision]] = []
    for decision in decisions:
        if decision.starts_document:
            segments.append([decision])
        else:
            segments[-1].append(decision)
    return segments


def first_found(values: list[str | None]) -> str | None:
    return next((value for value in values if value), None)


def segment_pages(session: Session, vendor_file: VendorFile) -> None:
    """Pipeline stage: create one documents row per detected segment."""
    pages = session.scalars(
        select(Page).where(Page.vendor_file_id == vendor_file.id).order_by(Page.page_number)
    ).all()
    if len(pages) != vendor_file.page_count:
        raise ValueError(f"Expected {vendor_file.page_count} pages, found {len(pages)}.")

    signals = [page_signals(page) for page in pages]
    signals_by_page = {s.page_number: s for s in signals}

    for segment in group_into_segments(decide_boundaries(signals)):
        start, end = segment[0], segment[-1]
        uncertain = [d for d in segment if d.confidence < REVIEW_BELOW_CONFIDENCE]
        segment_signals = [signals_by_page[d.page_number] for d in segment]

        document = Document(
            vendor_file_id=vendor_file.id,
            start_page=start.page_number,
            end_page=end.page_number,
            # A segment is as uncertain as its least certain decision: its start,
            # or any page we decided NOT to cut at.
            segmentation_confidence=min(d.confidence for d in segment),
            segmentation_evidence={
                "start": {"signals": start.signals, "score": start.score},
                "uncertain_pages": [
                    {"page": d.page_number, "signals": d.signals, "score": d.score} for d in uncertain
                ],
            },
            title=segment_signals[0].title,
            document_number=first_found([s.document_number for s in segment_signals]),
            revision=first_found([s.revision for s in segment_signals]),
        )
        session.add(document)
        session.flush()

        if uncertain:
            pages_text = ", ".join(str(d.page_number) for d in uncertain)
            session.add(
                ReviewItem(
                    vendor_file_id=vendor_file.id,
                    document_id=document.id,
                    page_number=uncertain[0].page_number,
                    item_kind=ReviewItemKind.SEGMENT_BOUNDARY,
                    target_table=Document.__tablename__,
                    target_record_id=document.id,
                    reason=f"Uncertain document boundary at page(s) {pages_text}.",
                )
            )