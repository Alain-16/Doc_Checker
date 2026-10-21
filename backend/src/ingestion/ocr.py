from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import boto3
import cv2
import numpy as np

from src.config.settings import get_settings

# --- Image cleanup settings ---
# Scans are rarely tilted more than a few degrees; larger turns (90°) are fixed
# by PaddleOCR's own page-orientation model instead.
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


# Engine 1: PaddleOCR, self-hosted, for printed text

class PaddleOcrEngine:
    name = "paddleocr"

    def __init__(self) -> None:
        self._ocr = None

    def _model(self):
        """Load PaddleOCR the first time it's needed, then keep it.

        Loading takes seconds and hundreds of MB, so it happens once per worker
        process, and never in processes that don't OCR (like the API). The import
        is inside the function for the same reason.
        """
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                lang="en",
                # Detects pages scanned sideways or upside down and turns them upright.
                use_doc_orientation_classify=True,
                use_doc_unwarping=False,
                use_textline_orientation=True,
            )
        return self._ocr

    def read(self, image: np.ndarray) -> OcrResult:
        # PaddleOCR expects a 3-channel colour image; our cleaned scans are 1-channel.
        color = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR) if image.ndim == 2 else image
        result = self._model().predict(color)[0]
        lines = [
            OcrLine(text=text.strip(), bbox=tuple(float(v) for v in box), confidence=float(score))
            for text, score, box in zip(result["rec_texts"], result["rec_scores"], result["rec_boxes"])
            if text.strip()
        ]
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


# One PaddleOCR per worker process. Cheap to create: the model loads on first read.
paddle_engine = PaddleOcrEngine()


@lru_cache
def get_textract_engine() -> TextractOcrEngine | None:
    """Textract when a region is configured (staging/production), else None."""
    region = get_settings().textract_region
    return TextractOcrEngine(region) if region else None


def ocr_image(gray: np.ndarray) -> OcrResult:
    """Clean a scan and read it: PaddleOCR first, Textract when Paddle struggles.

    PaddleOCR is free and good on print; it scores low on handwriting. So a low
    Paddle score is our handwriting detector: we then ask Textract (paid, built
    for handwriting) and keep whichever engine was more confident.
    """
    cleaned = clean_scan(gray)
    result = paddle_engine.read(cleaned)

    textract = get_textract_engine()
    if textract is not None and result.confidence < get_settings().ocr_confidence_threshold:
        second_opinion = textract.read(cleaned)
        if second_opinion.confidence > result.confidence:
            result = second_opinion
    return result