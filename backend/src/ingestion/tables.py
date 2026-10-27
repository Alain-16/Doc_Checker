"""Find tables on a page and turn them into rows of cell text for layout_data["tables"]."""

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import pymupdf

from src.ingestion.ocr import OcrResult, OcrWord

# --- Building a grid from cells (digital and scanned) ---
# Cell edges closer than this (in PDF points, 72 per inch) are the same column
# or row line. 3 pt is about 1 mm: scans and PDF rounding never drift that far.
EDGE_TOLERANCE_PT = 3.0
MIN_TABLE_ROWS = 2
MIN_TABLE_COLUMNS = 2

# --- Finding grid lines in a scan (all sizes in pixels at 300 dpi) ---
# A horizontal ruled line is at least 1/30 of the page wide (about 7 mm).
HORIZONTAL_LINE_MIN_WIDTH_SHARE = 1 / 30
# Column lines can be as short as one table row, so we look at short vertical
# strokes and keep only those that run from one horizontal line to another.
VERTICAL_STROKE_MIN_PX = 20
LINE_END_REACH_PX = 4  # how far a column line's end may be from a horizontal line
# A grid narrower than 20% of the page or shorter than 60 px (5 mm) isn't a table.
TABLE_MIN_WIDTH_SHARE = 0.2
TABLE_MIN_HEIGHT_PX = 60
# Gaps smaller than this between lines are slivers (e.g. inside a double border), not cells.
CELL_MIN_SIDE_PX = 15
# A cell is a rectangle, so its empty area fills its box. The gap inside a
# double border is a thin frame: its box is huge but almost all of it is not gap.
CELL_MIN_FILL_SHARE = 0.6
# Cells whose tops and bottoms are this close (about 1 mm) sit in the same row.
SAME_ROW_TOLERANCE_PX = 10
# A real table has text in most cells; a framed diagram or chart axes don't.
MIN_FILLED_CELL_SHARE = 0.5
WHITE = 255


@dataclass(frozen=True)
class TableCell:
    # Box around the cell in page points: (x0, y0, x1, y1).
    bbox: tuple[float, float, float, float]
    text: str


# =============================================================================
# Unit 1: the stored table format, and tables from a digital PDF's text layer
# =============================================================================


def edge_starts(values: list[float]) -> list[float]:
    """Merge nearly equal positions into one list of column (or row) starts."""
    starts: list[float] = []
    for value in sorted(values):
        if not starts or value - starts[-1] > EDGE_TOLERANCE_PT:
            starts.append(value)
    return starts


def spanned(starts: list[float], low: float, high: float) -> list[int]:
    """Indexes of the columns (or rows) whose start lies inside low..high."""
    return [
        index
        for index, start in enumerate(starts)
        if low - EDGE_TOLERANCE_PT <= start < high - EDGE_TOLERANCE_PT
    ]


def build_table(cells: list[TableCell], source: str) -> dict[str, Any] | None:
    """Arrange cells into rows and columns: the one format every table is stored in.

    A cell that spans several columns or rows (a merged cell) keeps its text in
    its top-left slot; the slots it covers stay empty, the same as PyMuPDF does.
    Returns None when the cells don't make at least a 2 x 2 grid.
    """
    column_starts = edge_starts([cell.bbox[0] for cell in cells])
    row_starts = edge_starts([cell.bbox[1] for cell in cells])
    if len(row_starts) < MIN_TABLE_ROWS or len(column_starts) < MIN_TABLE_COLUMNS:
        return None

    rows = [["" for _ in column_starts] for _ in row_starts]
    header_rows = 1
    for cell in cells:
        columns = spanned(column_starts, cell.bbox[0], cell.bbox[2])
        cell_rows = spanned(row_starts, cell.bbox[1], cell.bbox[3])
        if not columns or not cell_rows:
            continue
        rows[cell_rows[0]][columns[0]] = cell.text
        # Header size: a first-row cell that reaches down covers the header
        # rows below it ("Test" over two header rows). A first-row cell spread
        # over several columns ("Typical Data") has sub-headings underneath.
        if cell_rows[0] == 0:
            header_rows = max(header_rows, len(cell_rows), 2 if len(columns) > 1 else 1)

    return {
        "bbox": [
            round(min(cell.bbox[0] for cell in cells), 1),
            round(min(cell.bbox[1] for cell in cells), 1),
            round(max(cell.bbox[2] for cell in cells), 1),
            round(max(cell.bbox[3] for cell in cells), 1),
        ],
        "rows": rows,
        # Always leave at least one data row below the header.
        "header_rows": min(header_rows, len(rows) - 1),
        "source": source,
    }


def find_digital_tables(page: pymupdf.Page) -> list[dict[str, Any]]:
    """Tables drawn with ruled lines in a PDF's text layer, found by PyMuPDF."""
    tables = []
    for found in page.find_tables().tables:
        texts = found.extract()  # one list per row; None where a merged cell covers the slot
        cells = [
            TableCell(tuple(box), " ".join((texts[row][column] or "").split()))
            for row, table_row in enumerate(found.rows)
            for column, box in enumerate(table_row.cells)
            if box is not None
        ]
        table = build_table(cells, source="native")
        if table is not None:
            tables.append(table)
    return tables


def outside_tables(blocks: list[dict[str, Any]], tables: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The text blocks that aren't part of a table (their centre lies outside every table).

    Table text is stored once, in the table's rows, so chunking never reads it twice.
    """

    def inside(block: dict[str, Any], table: dict[str, Any]) -> bool:
        x0, y0, x1, y1 = block["bbox"]
        left, top, right, bottom = table["bbox"]
        return left <= (x0 + x1) / 2 <= right and top <= (y0 + y1) / 2 <= bottom

    return [block for block in blocks if not any(inside(block, table) for table in tables)]


# =============================================================================
# Unit 2: grid lines and cells in a scanned page image
# =============================================================================


def grid_lines(binary: np.ndarray) -> np.ndarray:
    """An image holding only the ruled lines of the page (white lines on black)."""
    width = binary.shape[1]
    ink = cv2.bitwise_not(binary)  # make ink white, which is what OpenCV's shape tools look at

    # "Opening" with a long flat shape keeps only ink that is at least that long
    # in a straight line: ruled lines survive, letters disappear.
    horizontal_shape = cv2.getStructuringElement(
        cv2.MORPH_RECT, (int(width * HORIZONTAL_LINE_MIN_WIDTH_SHARE), 1)
    )
    horizontal = cv2.morphologyEx(ink, cv2.MORPH_OPEN, horizontal_shape)
    vertical_strokes = cv2.morphologyEx(
        ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, VERTICAL_STROKE_MIN_PX))
    )

    # Keep a vertical stroke only if both its ends touch a horizontal line.
    # Column lines run from rule to rule; tall letters ("l", "I") don't.
    reach = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 2 * LINE_END_REACH_PX + 1))
    near_horizontal = cv2.dilate(horizontal, reach)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(vertical_strokes)
    columns = np.zeros_like(vertical_strokes)
    for label in range(1, count):  # label 0 is the background
        x, y, stroke_width, stroke_height, _ = stats[label]
        top_touches = near_horizontal[y, x : x + stroke_width].any()
        bottom_touches = near_horizontal[y + stroke_height - 1, x : x + stroke_width].any()
        if top_touches and bottom_touches:
            columns[labels == label] = WHITE

    # Thicken by one pixel so lines that almost meet do meet.
    return cv2.dilate(cv2.bitwise_or(horizontal, columns), np.ones((3, 3), np.uint8))


def find_grid_cells(rules: np.ndarray) -> list[list[tuple[int, int, int, int]]]:
    """For each ruled grid on the page, the boxes (in pixels) of its cells.

    `rules` is the output of grid_lines: the page's ruled lines and nothing else.
    """
    page_width = rules.shape[1]
    grids = []
    outlines, _ = cv2.findContours(rules, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for outline in outlines:
        left, top, width, height = cv2.boundingRect(outline)
        if width < page_width * TABLE_MIN_WIDTH_SHARE or height < TABLE_MIN_HEIGHT_PX:
            continue

        # The cells are the empty areas fenced in by the lines. Each separate
        # empty area gets its own label; connectivity=4 means areas touching
        # only at a corner stay separate.
        empty = cv2.bitwise_not(rules[top : top + height, left : left + width])
        count, _, stats, _ = cv2.connectedComponentsWithStats(empty, connectivity=4)
        cells = []
        for label in range(1, count):
            x, y, cell_width, cell_height, area = stats[label]
            # An area touching the edge is the page outside the grid, not a cell.
            touches_edge = x == 0 or y == 0 or x + cell_width >= width or y + cell_height >= height
            too_small = cell_width < CELL_MIN_SIDE_PX or cell_height < CELL_MIN_SIDE_PX
            not_a_rectangle = area < cell_width * cell_height * CELL_MIN_FILL_SHARE
            if touches_edge or too_small or not_a_rectangle:
                continue
            cells.append((left + x, top + y, left + x + cell_width, top + y + cell_height))
        if cells:
            grids.append(cells)
    return grids


def erase_lines(binary: np.ndarray, rules: np.ndarray) -> np.ndarray:
    """A copy of the page with ruled lines painted white, for OCR to read.

    With the lines left in, Tesseract reads cell borders as "|" or "[" and
    misreads digits that touch them ("0.0" -> "oo").
    """
    erased = binary.copy()
    erased[rules > 0] = WHITE
    return erased


# =============================================================================
# Unit 3: OCR words into cells
# =============================================================================


def words_in(box: tuple[int, int, int, int], words: list[OcrWord]) -> list[OcrWord]:
    """The words whose centre falls inside `box` (all in pixels)."""
    x0, y0, x1, y1 = box
    return [
        word
        for word in words
        if x0 <= (word.bbox[0] + word.bbox[2]) / 2 <= x1 and y0 <= (word.bbox[1] + word.bbox[3]) / 2 <= y1
    ]


def text_lines(words: list[OcrWord]) -> list[list[OcrWord]]:
    """Group a cell's words into printed lines, top to bottom, each left to right."""
    lines: list[list[OcrWord]] = []
    for word in sorted(words, key=lambda word: (word.bbox[1] + word.bbox[3]) / 2):
        middle = (word.bbox[1] + word.bbox[3]) / 2
        # Same line as the previous word if its middle is above that line's bottom.
        if lines and middle < max(other.bbox[3] for other in lines[-1]):
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda word: word.bbox[0]) for line in lines]


def split_unruled_rows(
    cells: list[tuple[tuple[int, int, int, int], list[list[OcrWord]]]],
) -> list[tuple[tuple[int, int, int, int], list[list[OcrWord]]]]:
    """Split rows that hold several table rows because no line was printed between them.

    Some tables rule only the columns: the body becomes one tall cell per
    column, each holding N lines. If every filled cell in such a band has the
    same number of lines, line k of each cell is table row k. Cells whose line
    counts differ (one long wrapped description next to short values) are a
    single row of wrapped text, and stay whole.
    """
    bands: list[list[int]] = []  # indexes of cells sharing the same top and bottom
    for index, (box, _) in enumerate(cells):
        for band in bands:
            other = cells[band[0]][0]
            if abs(box[1] - other[1]) <= SAME_ROW_TOLERANCE_PX and abs(box[3] - other[3]) <= SAME_ROW_TOLERANCE_PX:
                band.append(index)
                break
        else:  # no existing band matched: start a new one
            bands.append([index])

    result = []
    for band in bands:
        line_counts = {len(cells[index][1]) for index in band if cells[index][1]}
        if len(line_counts) != 1 or line_counts == {1}:
            result.extend(cells[index] for index in band)  # nothing to split
            continue
        for index in band:
            (x0, _, x1, _), lines = cells[index]
            if not lines:
                result.append(cells[index])
                continue
            # One new cell per line, as tall as that line's words.
            for line in lines:
                top = min(word.bbox[1] for word in line)
                bottom = max(word.bbox[3] for word in line)
                result.append(((x0, top, x1, bottom), [line]))
    return result


def has_overlapping_cells(grid: list[tuple[int, int, int, int]]) -> bool:
    """True when two cell boxes overlap: boxes drawn inside boxes (a diagram), not a table grid."""
    return any(
        a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
        for index, a in enumerate(grid)
        for b in grid[index + 1 :]
    )


def find_scanned_tables(
    grids: list[list[tuple[int, int, int, int]]], ocr: OcrResult, pixels_per_point: float
) -> list[dict[str, Any]]:
    """Fill each ruled grid with the words OCR read inside its cells."""
    words = [word for line in ocr.lines for word in line.words]
    tables = []
    for grid in grids:
        if has_overlapping_cells(grid):
            continue
        cells = split_unruled_rows([(box, text_lines(words_in(box, words))) for box in grid])
        filled = sum(1 for _, lines in cells if lines)
        if filled < len(cells) * MIN_FILLED_CELL_SHARE:
            continue  # chart axes or a framed picture, not a table

        table_cells = [
            TableCell(
                tuple(value / pixels_per_point for value in box),  # pixels -> page points
                " ".join(word.text for line in lines for word in line),
            )
            for box, lines in cells
        ]
        table = build_table(table_cells, source=ocr.engine)
        if table is not None:
            tables.append(table)
    return tables

