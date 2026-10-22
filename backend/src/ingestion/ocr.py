from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import boto3
import cv2
import numpy as np

from src.config.settings import get_settings

# --- Image cleanup settings ---
# Scans are rarely tilted more than a few degrees; larger turns (90°) are fixed
# by Tesseract's orientation detection instead.
MAX_SKEW_DEGREES = 5.0
SKEW_STEP_DEGREES = 0.25
# Skew is estimated on a shrunken copy: much faster, and accurate enough.
SKEW_ESTIMATE_MAX_SIDE_PX = 1000
# Adaptive binarization compares each pixel with its neighbourhood (31 px wide)
# instead of one global cut-off, so shadows and faded corners survive.
BINARIZE_BLOCK_SIZE_PX = 31
BINARIZE_OFFSET = 15
WHITE = 255

@dataclass(frozen=True)
class OcrLine:
    text: str
    # Box around the line, in pixels of the image that was read: (x0, y0, x1, y1).
    bbox: tuple[float, float, float, float]
    confidence: float  # 0..1
    handwriting: bool = False


@dataclass(frozen=True)
class OcrResult:
    engine: str
    lines: list[OcrLine]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def confidence(self) -> float:
        """Average line confidence, weighted by line length.

        Weighting means one misread 2-letter fragment doesn't drag down a page of
        well-read paragraphs. A page with no text at all scores 0.
        """
        total_chars = sum(len(line.text) for line in self.lines)
        if total_chars == 0:
            return 0.0
        return sum(line.confidence * len(line.text) for line in self.lines) / total_chars


class OcrEngine(Protocol):
    """What every OCR engine must offer.

    A Protocol is a description of required methods: any class with a `name`
    and a matching `read` counts as an OcrEngine, without inheriting from it.
    """

    name: str

    def read(self, image: np.ndarray) -> OcrResult: ...


# Image cleanup: deskew + binarization (Feature 2 acceptance criterion)

def rotate(image: np.ndarray, degrees: float, fill: int) -> np.ndarray:
    """Turn an image around its centre, filling the uncovered corners with `fill`."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), degrees, 1.0)
    return cv2.warpAffine(image, matrix, (width, height), borderValue=fill)


def estimate_skew(gray: np.ndarray) -> float:
    """Find the small rotation that makes the text lines horizontal.

    Method ("projection profile"): try every angle in a small range and, for each,
    add up the ink in every pixel row. When lines are level, rows alternate
    between full (text) and empty (gaps), so the row totals vary the most.
    """
    scale = SKEW_ESTIMATE_MAX_SIDE_PX / max(gray.shape)
    small = cv2.resize(gray, None, fx=scale, fy=scale) if scale < 1 else gray
    # Otsu picks the ink/paper cut-off automatically. INV makes ink white (255)
    # so that summing a row counts ink.
    _, ink = cv2.threshold(small, 0, WHITE, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)

    candidate_angles = np.arange(-MAX_SKEW_DEGREES, MAX_SKEW_DEGREES + SKEW_STEP_DEGREES, SKEW_STEP_DEGREES)
    row_variation = [np.var(rotate(ink, angle, fill=0).sum(axis=1)) for angle in candidate_angles]
    return float(candidate_angles[int(np.argmax(row_variation))])


def clean_scan(gray: np.ndarray) -> np.ndarray:
    """Straighten a grayscale scan and turn it into pure black text on white."""
    straightened = rotate(gray, estimate_skew(gray), fill=WHITE)
    return cv2.adaptiveThreshold(
        straightened,
        WHITE,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        BINARIZE_BLOCK_SIZE_PX,
        BINARIZE_OFFSET,
    )


# Engine 1: Tesseract, self-hosted, for printed text

# Tesseract gives up on a single image after this long instead of hanging the worker.
TESSERACT_TIMEOUT_SECONDS = 180
# Tesseract's orientation check (OSD) reports how sure it is; below this we
# leave the image as it is (14 is the cut-off OCRmyPDF uses).
MIN_ORIENTATION_CONFIDENCE = 14.0
# Tesseract scores words 0..100; -1 marks rows that are layout, not words.
NOT_A_WORD = -1


class TesseractOcrEngine:
    name = "tesseract"

    def upright(self, image: np.ndarray) -> np.ndarray:
        """Turn a page scanned sideways or upside down so its text reads normally."""
        import pytesseract

        try:
            osd = pytesseract.image_to_osd(
                image, output_type=pytesseract.Output.DICT, timeout=TESSERACT_TIMEOUT_SECONDS
            )
        except pytesseract.TesseractError:
            # OSD fails on images with too little text (logos, blank pages): keep as is.
            return image
        if osd["orientation_conf"] < MIN_ORIENTATION_CONFIDENCE:
            return image
        # "rotate" is how many degrees clockwise the image must turn to be upright.
        turns = {
            90: cv2.ROTATE_90_CLOCKWISE,
            180: cv2.ROTATE_180,
            270: cv2.ROTATE_90_COUNTERCLOCKWISE,
        }
        return cv2.rotate(image, turns[osd["rotate"]]) if osd["rotate"] in turns else image

    def read(self, image: np.ndarray) -> OcrResult:
        """OCR one image and keep Tesseract's own per-word confidence.

        Tesseract scores every word; a line's confidence is the average of its words.
        """
        import pytesseract

        image = self.upright(image)
        data = pytesseract.image_to_data(
            image, lang="eng", output_type=pytesseract.Output.DICT, timeout=TESSERACT_TIMEOUT_SECONDS
        )

        # One row per word, numbered by block / paragraph / line: group into lines.
        grouped: dict[tuple[int, int, int], list[int]] = {}
        for row, text in enumerate(data["text"]):
            if float(data["conf"][row]) == NOT_A_WORD or not text.strip():
                continue
            key = (data["block_num"][row], data["par_num"][row], data["line_num"][row])
            grouped.setdefault(key, []).append(row)

        lines = []
        for rows in grouped.values():
            text = " ".join(data["text"][row].strip() for row in rows)
            lines.append(
                OcrLine(
                    text=text,
                    bbox=(
                        float(min(data["left"][row] for row in rows)),
                        float(min(data["top"][row] for row in rows)),
                        float(max(data["left"][row] + data["width"][row] for row in rows)),
                        float(max(data["top"][row] + data["height"][row] for row in rows)),
                    ),
                    # Average of the word scores, 0..100 turned into 0..1.
                    confidence=sum(float(data["conf"][row]) for row in rows) / len(rows) / 100,
                )
            )
        # Reading order: top to bottom, then left to right. Rounding y to 10 px
        # keeps words on the same printed line together despite tiny offsets.
        lines.sort(key=lambda line: (round(line.bbox[1] / 10), line.bbox[0]))
        return OcrResult(engine=self.name, lines=lines)


# Engine 2: AWS Textract, for handwriting (Unit 10)



class TextractOcrEngine:
    name = "textract"

    def __init__(self, region: str) -> None:
        self._client = boto3.client("textract", region_name=region)

    def read(self, image: np.ndarray) -> OcrResult:
        encoded_ok, png = cv2.imencode(".png", image)
        if not encoded_ok:
            raise ValueError("Could not encode page image for Textract.")
        response = self._client.detect_document_text(Document={"Bytes": png.tobytes()})
        blocks = response["Blocks"]

        # Textract returns WORD blocks (each tagged PRINTED or HANDWRITING) and
        # LINE blocks that list their words. A line counts as handwriting if any
        # of its words is handwritten.
        handwritten_word_ids = {
            block["Id"]
            for block in blocks
            if block["BlockType"] == "WORD" and block.get("TextType") == "HANDWRITING"
        }
        height, width = image.shape[:2]
        lines = []
        for block in blocks:
            if block["BlockType"] != "LINE":
                continue
            word_ids = {
                word_id
                for relation in block.get("Relationships", [])
                if relation["Type"] == "CHILD"
                for word_id in relation["Ids"]
            }
            # Textract gives positions as fractions of the image size (0..1).
            box = block["Geometry"]["BoundingBox"]
            lines.append(
                OcrLine(
                    text=block["Text"],
                    bbox=(
                        box["Left"] * width,
                        box["Top"] * height,
                        (box["Left"] + box["Width"]) * width,
                        (box["Top"] + box["Height"]) * height,
                    ),
                    confidence=block["Confidence"] / 100,  # Textract uses 0..100
                    handwriting=bool(word_ids & handwritten_word_ids),
                )
            )
        return OcrResult(engine=self.name, lines=lines)



# Choosing the engine for an image


# One per worker process. It holds no state, so sharing it is safe.
tesseract_engine = TesseractOcrEngine()


@lru_cache
def get_textract_engine() -> TextractOcrEngine | None:
    """Textract when a region is configured (staging/production), else None."""
    region = get_settings().textract_region
    return TextractOcrEngine(region) if region else None


def ocr_image(gray: np.ndarray) -> OcrResult:
    """Clean a scan and read it: Tesseract first, Textract when it struggles.

    Tesseract is free and good on print; on handwriting it produces garbage,
    which scores low. So a low score is our handwriting detector: we then ask
    Textract (paid, built for handwriting) and keep whichever engine was more
    confident.
    """
    cleaned = clean_scan(gray)
    result = tesseract_engine.read(cleaned)

    textract = get_textract_engine()
    if textract is not None and result.confidence < get_settings().ocr_confidence_threshold:
        second_opinion = textract.read(cleaned)
        if second_opinion.confidence > result.confidence:
            result = second_opinion
    return result
