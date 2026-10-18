"""Reading coordinates / biome from an F3 frame — the interface the tracker talks to.

`OcrExtractor` (vision/ocr.py) is the real implementation; `NullExtractor` is used when OCR is
switched off (``GHG_OCR_ENGINE=none``) and leaves snapshots in ``ocr_status="pending"``, so they
can be processed later from the stored image.
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from ghgtracker.vision.f3_detector import F3Detection


@dataclass
class ExtractionResult:
    x: float | None = None
    y: float | None = None
    z: float | None = None
    # XYZ was cross-checked against the "Block:" line of the F3 screen.
    confirmed: bool = False
    biome: str | None = None
    dimension: str | None = None
    facing: str | None = None
    raw_text: str | None = None
    engine: str | None = None
    elapsed_ms: float = 0.0


class CoordinateExtractor(Protocol):
    def extract(self, frame_bgr: np.ndarray, detection: F3Detection) -> ExtractionResult | None:
        """Return the parsed values, or None if this extractor cannot read the frame."""
        ...


class NullExtractor:
    def extract(self, frame_bgr: np.ndarray, detection: F3Detection) -> ExtractionResult | None:
        return None
