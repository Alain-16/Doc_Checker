"""Cut a document's stored pages into chunks for search, using one of four strategies."""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

import tiktoken

from src.llm.models import EMBEDDING_MODEL
from src.models.chunk import ChunkingStrategy

# --- OCR noise (Unit 8) ---
# Logos and stamps OCR'd as text ("Westie", "“yy", "Aan", "9"). Measured on the
# test bundle: every such line scored under 0.8 with fewer than 8 letters or
# digits; every real short line ("Rev. 5", "10 HALAL", "TABLE 1") scored 0.82+.
NOISE_MAX_CONFIDENCE = 0.8
NOISE_MAX_ALPHANUMERIC = 7

# --- Section headings (Unit 6) ---
# "4 NATURAL RUBBER LATEX", "4. COMPLIANCE INFORMATION", "2.1 SCOPE"
DIGIT_HEADING = re.compile(r"^\d{1,2}(?:\.\d{1,2})*[.)]?\s+(\S+)")
# "IV. FluroTec Product Nomenclature", "I. Background"
ROMAN_HEADING = re.compile(r"^[IVX]{1,4}[.)]\s+(\S.*)$")
# List items: a bullet ("•", which OCR often reads as "e", "«" or "©") then a space.
BULLET = re.compile(r"^[•●▪*«©eo-]\s")
HEADING_MAX_CHARS = 90
# Unnumbered headings are written in capitals: "TYPICAL EXTRACTION CHARACTERISTICS".
CAPITALS_HEADING_MIN_LETTERS = 8
CAPITALS_HEADING_MIN_UPPER_SHARE = 0.85
CAPITALS_HEADING_MAX_CHARS = 70
# Contents pages list every heading with dot leaders ("3 HEAVY METALS ....... 3");
# OCR often turns the dots into one long run of letters ("ccccscsss...").
DOT_LEADER = re.compile(r"\.{3,}|\S{25,}")
# On digital pages font size is exact, so text this much bigger than the body is a heading.
NATIVE_HEADING_SIZE_RATIO = 1.2
# A line that repeats on at least half of a document's pages (and on 2+ pages)
# is page furniture, like "Compliance Bulletin" in every page header.
FURNITURE_MIN_PAGE_SHARE = 0.5
FURNITURE_MIN_PAGES = 2

# --- Chunk sizes (Units 7-8) ---
# text-embedding-3-large reads at most 8191 tokens. Structure-aware chunks keep
# whole sections, so this is the only limit they have; a little is kept spare.
EMBEDDING_MAX_TOKENS = 8000


# =============================================================================
# Unit 4: a document's text, in reading order, with page numbers
# =============================================================================


class StoredPage(Protocol):
    """What chunking reads from a pages row (src.models.Page fits this)."""

    page_number: int
    layout_data: dict[str, Any]


@dataclass(frozen=True)
class ContentLine:
    page_number: int
    text: str
    # Font size in points on digital pages; line height on scanned ones (less exact).
    size: float
    from_text_layer: bool  # True when read from the PDF's own text, not OCR


@dataclass(frozen=True)
class ContentTable:
    page_number: int
    rows: list[list[str]]
    header_rows: int
    # How many lines come before the table, so we know which section it sits in.
    lines_before: int


@dataclass
class DocumentContent:
    lines: list[ContentLine]
    tables: list[ContentTable]


def document_content(pages: list[StoredPage]) -> DocumentContent:
    """Gather the text lines and tables of a document's pages, page by page.

    Lines come from layout_data["blocks"], which (since table detection) no
    longer contain table text: tables come separately, from layout_data["tables"],
    so no text is read twice. Each table is placed before the first line that
    starts below its top edge.
    """
    lines: list[ContentLine] = []
    tables: list[ContentTable] = []
    for page in sorted(pages, key=lambda page: page.page_number):
        layout = page.layout_data
        page_tables = sorted(layout.get("tables", []), key=lambda table: table["bbox"][1])
        for block in layout.get("blocks", []):
            # Place every table whose top is above this block before the block.
            while page_tables and page_tables[0]["bbox"][1] <= block["bbox"][1]:
                tables.append(table_at(page.page_number, page_tables.pop(0), len(lines)))
            text = " ".join(block["text"].split())
            if text and not is_ocr_noise(block):
                lines.append(ContentLine(page.page_number, text, block["size"], block["source"] == "native"))
        # Tables below the last block of the page.
        tables.extend(table_at(page.page_number, table, len(lines)) for table in page_tables)
    return DocumentContent(lines, tables)


def table_at(page_number: int, table: dict[str, Any], lines_before: int) -> ContentTable:
    return ContentTable(page_number, table["rows"], table["header_rows"], lines_before)


def is_ocr_noise(block: dict[str, Any]) -> bool:
    """A short, badly read OCR line: a logo or stamp read as letters, not text."""
    if block["source"] == "native":
        return False  # the PDF's own text is exactly what was written
    alphanumeric = sum(char.isalnum() for char in block["text"])
    return block.get("confidence", 1.0) < NOISE_MAX_CONFIDENCE and alphanumeric <= NOISE_MAX_ALPHANUMERIC



# =============================================================================
# Unit 5: counting tokens, and fixed-size chunks (strategies 1 and 2)
# =============================================================================


@dataclass
class ChunkDraft:
    """A chunk before it is saved: what becomes one row of the chunks table."""

    content: str
    page_start: int
    page_end: int
    token_count: int
    section_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@lru_cache
def tokenizer() -> tiktoken.Encoding:
    """The tokenizer of our embedding model, loaded once per process.

    Tokens are the pieces of text the model reads (roughly 3/4 of a word each).
    Chunk sizes are measured in tokens because that is what the model's limits
    and prices are measured in.
    """
    return tiktoken.encoding_for_model(EMBEDDING_MODEL)


def count_tokens(text: str) -> int:
    return len(tokenizer().encode(text))


def fixed_size_chunks(
    lines: list[ContentLine], chunk_tokens: int, overlap_tokens: int, section_name: str | None = None
) -> list[ChunkDraft]:
    """Cut text into chunks of `chunk_tokens` tokens; each repeats the last
    `overlap_tokens` tokens of the one before it.

    With overlap_tokens=0 this is strategy 1 (fixed size); above 0 it is
    strategy 2 (fixed size with overlap). Cuts fall wherever the count says,
    even mid-sentence: that is the baseline the other strategies are compared to.
    """
    if not 0 <= overlap_tokens < chunk_tokens:
        raise ValueError(f"Overlap ({overlap_tokens}) must be at least 0 and smaller than the chunk ({chunk_tokens}).")

    # One long list of tokens, and next to it the page each token came from.
    tokens: list[int] = []
    token_pages: list[int] = []
    for line in lines:
        line_tokens = tokenizer().encode(line.text + "\n")
        tokens.extend(line_tokens)
        token_pages.extend([line.page_number] * len(line_tokens))

    chunks = []
    step = chunk_tokens - overlap_tokens
    for start in range(0, len(tokens), step):
        end = min(start + chunk_tokens, len(tokens))
        content = tokenizer().decode(tokens[start:end]).strip()
        if content:
            chunks.append(
                ChunkDraft(
                    content=content,
                    page_start=min(token_pages[start:end]),
                    page_end=max(token_pages[start:end]),
                    token_count=count_tokens(content),
                    section_name=section_name,
                )
            )
        if end == len(tokens):
            break  # without this, overlap would add a last chunk that only repeats text
    return chunks


# =============================================================================
# Unit 6: finding the document's sections
# =============================================================================


@dataclass
class Section:
    title: str | None  # None for text before the first heading
    lines: list[ContentLine] = field(default_factory=list)
    tables: list[ContentTable] = field(default_factory=list)


def furniture_key(text: str) -> str:
    """Text reduced to its letters, so a header repeated with different page
    numbers or OCR spacing still counts as the same line."""
    return re.sub(r"[^a-z]", "", text.lower())


def page_furniture(lines: list[ContentLine]) -> set[str]:
    """Keys of lines that repeat on most pages: headers and footers, not headings."""
    pages_by_key: dict[str, set[int]] = defaultdict(set)
    for line in lines:
        pages_by_key[furniture_key(line.text)].add(line.page_number)
    page_count = len({line.page_number for line in lines})
    return {
        key
        for key, pages in pages_by_key.items()
        if key and len(pages) >= FURNITURE_MIN_PAGES and len(pages) >= page_count * FURNITURE_MIN_PAGE_SHARE
    }


def is_title_case(text: str) -> bool:
    """Every word of 3+ letters starts with a capital: "FluroTec Product Nomenclature"."""
    words = [word for word in re.findall(r"[A-Za-z]+", text) if len(word) >= 3]
    return bool(words) and all(word[0].isupper() for word in words)


def is_capitals(text: str) -> bool:
    """Mostly capital letters, and enough of them: "TYPICAL JP DATA"."""
    letters = [char for char in text if char.isalpha()]
    upper_share = sum(char.isupper() for char in letters) / len(letters) if letters else 0
    return len(letters) >= CAPITALS_HEADING_MIN_LETTERS and upper_share >= CAPITALS_HEADING_MIN_UPPER_SHARE


def is_heading(line: ContentLine, body_size: float) -> bool:
    """True when a line looks like a section heading."""
    text = line.text
    if len(text) > HEADING_MAX_CHARS or DOT_LEADER.search(text) or BULLET.match(text):
        return False

    # After a digit the heading is in capitals: "3 HEAVY METALS". Not "16 Dec 2014"
    # or "1. This formulation meets...", which are dates and numbered sentences.
    digit = DIGIT_HEADING.match(text)
    if digit:
        first_word = digit.group(1)
        return len(first_word) >= 2 and first_word.isupper()

    roman = ROMAN_HEADING.match(text)
    if roman:
        return is_title_case(roman.group(1)) or is_capitals(roman.group(1))

    if is_capitals(text) and len(text) <= CAPITALS_HEADING_MAX_CHARS and len(text.split()) >= 2:
        return True

    # Font size only counts where it is exact: the PDF's own text layer.
    return (
        line.from_text_layer
        and line.size >= body_size * NATIVE_HEADING_SIZE_RATIO
        and not text.endswith(".")
        and any(char.isalpha() for char in text)
    )


def split_into_sections(content: DocumentContent) -> list[Section]:
    """Cut the document at every heading; each table joins the section it sits in."""
    native_sizes = sorted(line.size for line in content.lines if line.from_text_layer)
    body_size = native_sizes[len(native_sizes) // 2] if native_sizes else 0.0  # the median
    furniture = page_furniture(content.lines)

    sections = [Section(title=None)]
    waiting_tables = list(content.tables)  # in reading order, like the lines
    previous: ContentLine | None = None  # the last line that wasn't page furniture
    for index, line in enumerate(content.lines):
        # Tables that sit before this line belong to the section we're in now.
        while waiting_tables and waiting_tables[0].lines_before <= index:
            sections[-1].tables.append(waiting_tables.pop(0))
        if furniture_key(line.text) in furniture:
            continue  # page headers and footers aren't section text

        # A capitals line right after a capitals line that wasn't a heading is
        # its wrapped second half ("e EUROPEAN DIRECTIVE ... ON PACKAGING" /
        # "AND PACKAGING WASTE"), not a new heading.
        current = sections[-1]
        continues_text = previous is not None and is_capitals(previous.text) and current.lines[-1:] == [previous]
        if is_heading(line, body_size) and not continues_text:
            if current.title and not current.lines and not current.tables:
                # Two headings in a row are one title over two lines.
                current.title = f"{current.title} {line.text}"
            else:
                sections.append(Section(title=line.text))
        else:
            current.lines.append(line)
        previous = line
    sections[-1].tables.extend(waiting_tables)  # tables after the last line

    # Drop the "before the first heading" section when nothing is in it.
    return [section for section in sections if section.title or section.lines or section.tables]


# =============================================================================
# Unit 7: table chunks
# =============================================================================


def table_row_text(row: list[str]) -> str:
    """One table row as a line of text: "| Lead | NMT 2 ppm | <=2 |"."""
    return "| " + " | ".join(cell for cell in row) + " |"


def table_chunks(table: ContentTable, max_tokens: int, section_name: str | None = None) -> list[ChunkDraft]:
    """Turn a table into chunks of whole rows, each starting with the table's header.

    A row of values means nothing without its column names ("0.0 | 0.0 | 0.1"),
    so every piece repeats the header, and the section title above it says what
    the table is about. A row is never cut: a single row bigger than the limit
    becomes a chunk of its own, slightly over size.
    """
    header = [table_row_text(row) for row in table.rows[: table.header_rows]]
    body = [table_row_text(row) for row in table.rows[table.header_rows :] if any(row)]
    prefix = "\n".join(([section_name] if section_name else []) + header)
    prefix_tokens = count_tokens(prefix + "\n")

    pieces: list[list[str]] = [[]]
    piece_tokens = prefix_tokens
    for row in body:
        row_tokens = count_tokens(row + "\n")
        if pieces[-1] and piece_tokens + row_tokens > max_tokens:
            pieces.append([])  # this row would overflow the piece: start the next one
            piece_tokens = prefix_tokens
        pieces[-1].append(row)
        piece_tokens += row_tokens

    chunks = []
    for rows in pieces:
        content = "\n".join([prefix, *rows])
        chunks.append(
            ChunkDraft(
                content=content,
                page_start=table.page_number,
                page_end=table.page_number,
                token_count=count_tokens(content),
                section_name=section_name,
                metadata={"is_table": True},
            )
        )
    return chunks


# =============================================================================
# Unit 8: structure-aware and hybrid chunks (strategies 3 and 4)
# =============================================================================


def section_chunks(section: Section, max_tokens: int, overlap_tokens: int) -> list[ChunkDraft]:
    """One section as chunks: its text first, then its tables.

    Text that fits is one chunk, the title on top. Text that doesn't fit is cut
    with overlap, and the title is repeated on every piece so none of them
    loses its context ("...not present" means nothing without "4 NATURAL RUBBER LATEX").
    """
    chunks = []
    if section.lines:
        title = f"{section.title}\n" if section.title else ""
        content = title + "\n".join(line.text for line in section.lines)
        if count_tokens(content) <= max_tokens:
            chunks.append(
                ChunkDraft(
                    content=content,
                    page_start=min(line.page_number for line in section.lines),
                    page_end=max(line.page_number for line in section.lines),
                    token_count=count_tokens(content),
                    section_name=section.title,
                )
            )
        else:
            # Leave room for the title, which goes back on top of each piece.
            pieces = fixed_size_chunks(section.lines, max_tokens - count_tokens(title), overlap_tokens, section.title)
            for piece in pieces:
                piece.content = title + piece.content
                piece.token_count = count_tokens(piece.content)
            chunks.extend(pieces)
    for table in section.tables:
        chunks.extend(table_chunks(table, max_tokens, section.title))
    return chunks


def structure_chunks(content: DocumentContent) -> list[ChunkDraft]:
    """Strategy 3: one chunk per section, however long, and one per table.

    The only size limit is what the embedding model can read at all; a section
    longer than that (very rare) is cut like the hybrid strategy, without overlap.
    """
    return [
        chunk
        for section in split_into_sections(content)
        for chunk in section_chunks(section, EMBEDDING_MAX_TOKENS, overlap_tokens=0)
    ]


def hybrid_chunks(content: DocumentContent, max_tokens: int, overlap_tokens: int) -> list[ChunkDraft]:
    """Strategy 4 (the default): sections as the unit, long ones cut to size with overlap."""
    return [
        chunk
        for section in split_into_sections(content)
        for chunk in section_chunks(section, max_tokens, overlap_tokens)
    ]


def chunk_document(
    content: DocumentContent, strategy: ChunkingStrategy, max_tokens: int, overlap_tokens: int
) -> list[ChunkDraft]:
    """Cut one document into chunks with the chosen strategy."""
    if strategy == ChunkingStrategy.STRUCTURE:
        return structure_chunks(content)
    if strategy == ChunkingStrategy.HYBRID:
        return hybrid_chunks(content, max_tokens, overlap_tokens)

    # Fixed-size strategies ignore structure, but tables are no longer among the
    # lines (Unit 4), so they still get their own chunks or their text would be lost.
    overlap = overlap_tokens if strategy == ChunkingStrategy.FIXED_OVERLAP else 0
    text_chunks = fixed_size_chunks(content.lines, max_tokens, overlap)
    return text_chunks + [chunk for table in content.tables for chunk in table_chunks(table, max_tokens)]
