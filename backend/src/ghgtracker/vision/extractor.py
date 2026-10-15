"""Reading coordinates / biome from an F3 frame (OCR) — interface only for now.

The tracker calls an extractor for every stored snapshot. Until a real implementation exists,
`NullExtractor` leaves the values empty and the snapshot stays in `ocr_status="pending"`, so it
can be (re)processed later from the stored image.
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
    biome: str | None = None
    dimension: str | None = None
    facing: str | None = None
    raw_text: str | None = None


class CoordinateExtractor(Protocol):
    def extract(self, frame_bgr: np.ndarray, detection: F3Detection) -> ExtractionResult | None:
        """Return the parsed values, or None if this extractor cannot read the frame."""
        ...


class NullExtractor:
    def extract(self, frame_bgr: np.ndarray, detection: F3Detection) -> ExtractionResult | None:
        return None
