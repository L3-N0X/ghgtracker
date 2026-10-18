"""OCR of the F3 screen: crop the detected text columns, read them, parse the values.

The engine is picked with ``GHG_OCR_ENGINE`` (see `ENGINES`). The PaddleOCR presets run on
onnxruntime on the CPU; ``ollama`` sends the crops to a vision LLM served by Ollama, which can
use a GPU. On 2 CPU threads (benchmark in scripts/ocr_bench.py, 22 real readings):

    ppocr6-tiny    19/22 exact, ~0.8 s per snapshot   (default, fits a small VPS)
    ppocr6-small   21/22 exact, ~3.6 s
    ppocr5-mobile  20/22 exact, ~3.1 s
    ollama         qwen3-vl:2b-instruct 17/22 on CPU (~145 s), use it with a GPU only
"""

from __future__ import annotations

import base64
import json
import logging
import math
import threading
import time
import urllib.request
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from ghgtracker.vision.extractor import ExtractionResult
from ghgtracker.vision.f3_detector import ColumnAnalysis, F3Detection, F3DetectorConfig
from ghgtracker.vision.f3_text import parse_f3_text

logger = logging.getLogger(__name__)

# PaddleOCR presets: (version, detection model, its language, recognition model, its language).
PADDLE_PRESETS = {
    "ppocr6-tiny": ("PP-OCRv6", "tiny", "en", "tiny", "en"),
    "ppocr6-small": ("PP-OCRv6", "small", "en", "small", "en"),
    "ppocr5-mobile": ("PP-OCRv5", "mobile", "ch", "mobile", "en"),
}
ENGINES = ("none", *PADDLE_PRESETS, "ollama")


class OcrEngine(Protocol):
    name: str
    # Crops are scaled so one GUI pixel is this many image pixels.
    target_gui: float

    def read(self, crops: list[np.ndarray]) -> str:
        """Return the text of the crops, one line of the F3 screen per text line."""
        ...


# ------------------------------------------------------------------ crops


def column_crops(
    frame: np.ndarray,
    detection: F3Detection,
    target_gui: float,
    config: F3DetectorConfig | None = None,
) -> list[np.ndarray]:
    """One crop per detected F3 column, scaled so the GUI scale is about `target_gui`."""
    h, w = frame.shape[:2]
    gui = detection.gui_scale or 2.0
    pad = math.ceil(3 * gui)
    limit = int(w * (config or F3DetectorConfig()).strip_width)
    crops = []
    for column, right in ((detection.left, False), (detection.right, True)):
        if not column.boxes:
            continue
        y1 = max(0, min(b[1] for b in column.boxes) - pad)
        y2 = min(h, max(b[3] for b in column.boxes) + pad)
        x1, x2 = _column_x(column, right, w, pad, limit)
        crops.append(_scale(frame[y1:y2, x1:x2], target_gui / gui))
    return crops


def _column_x(column: ColumnAnalysis, right: bool, w: int, pad: int, limit: int) -> tuple[int, int]:
    # The detector only searches the outer `strip_width` of the frame: lines reaching that limit
    # continue beyond it, then the crop extends to the middle of the frame.
    if right:
        x1 = min(b[0] for b in column.boxes)
        return (w // 2 if x1 <= w - limit + pad else max(0, x1 - pad)), w
    x2 = max(b[2] for b in column.boxes)
    return 0, (w // 2 if x2 >= limit - pad else min(w, x2 + pad))


def _scale(image: np.ndarray, factor: float) -> np.ndarray:
    factor = min(max(factor, 0.5), 4.0)
    if abs(factor - 1) < 0.05:
        return image
    interpolation = cv2.INTER_CUBIC if factor > 1 else cv2.INTER_AREA
    return cv2.resize(image, None, fx=factor, fy=factor, interpolation=interpolation)


def stack(crops: list[np.ndarray]) -> np.ndarray:
    """Crops on top of each other (one image for engines that take a single picture)."""
    width = max(c.shape[1] for c in crops)
    gap = np.zeros((16, width, 3), np.uint8)
    parts: list[np.ndarray] = []
    for crop in crops:
        padded = cv2.copyMakeBorder(crop, 0, 0, 0, width - crop.shape[1], cv2.BORDER_CONSTANT)
        parts += [padded, gap]
    return np.vstack(parts[:-1])


# ------------------------------------------------------------------ engines


class PaddleEngine:
    """PaddleOCR models via RapidOCR / onnxruntime (CPU)."""

    target_gui = 2.0

    def __init__(self, preset: str, threads: int, model_dir: Path | None = None) -> None:
        from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR

        version, det, det_lang, rec, rec_lang = PADDLE_PRESETS[preset]
        params: dict = {
            "Global.use_cls": False,
            "Global.log_level": "warning",
            "EngineConfig.onnxruntime.intra_op_num_threads": threads if threads > 0 else -1,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Det.ocr_version": OCRVersion(version),
            "Det.model_type": ModelType(det),
            "Det.lang_type": LangDet(det_lang),
            "Rec.ocr_version": OCRVersion(version),
            "Rec.model_type": ModelType(rec),
            "Rec.lang_type": LangRec(rec_lang),
        }
        if model_dir is not None:
            model_dir.mkdir(parents=True, exist_ok=True)
            params["Global.model_root_dir"] = str(model_dir)
        self.name = preset
        self._ocr = RapidOCR(params=params)

    def read(self, crops: list[np.ndarray]) -> str:
        lines: list[str] = []
        for crop in crops:
            result = self._ocr(crop)
            lines += _rows(result.boxes, result.txts)
        return "\n".join(lines)


def _rows(boxes, texts) -> list[str]:
    """The detection model may split one line into several boxes: join boxes on the same row."""
    if boxes is None or texts is None:
        return []
    items = sorted(
        (float(np.mean(b[:, 1])), float(np.min(b[:, 0])), float(np.ptp(b[:, 1])), t)
        for b, t in zip(boxes, texts, strict=True)
    )
    rows: list[tuple[float, list[tuple[float, str]]]] = []
    for center, x, height, text in items:
        if rows and abs(rows[-1][0] - center) < 0.5 * height:
            rows[-1][1].append((x, text))
        else:
            rows.append((center, [(x, text)]))
    return [" ".join(t for _, t in sorted(parts)) for _, parts in rows]


OLLAMA_PROMPT = (
    "This image shows the text of the Minecraft F3 debug screen. Copy these lines exactly as "
    'written, one per line, and skip any that are not there: the line starting with "XYZ:", '
    'the line starting with "Block:", the line starting with "Facing:", the line starting with '
    '"Biome:" and the line containing the dimension (like "minecraft:overworld"). '
    "Answer NONE if there is no XYZ line."
)


class OllamaEngine:
    """A vision LLM served by Ollama (uses the GPU if Ollama has one)."""

    target_gui = 2.0

    def __init__(self, url: str, model: str, threads: int, timeout: float = 300.0) -> None:
        self.name = f"ollama:{model}"
        self.url = url.rstrip("/") + "/api/generate"
        self.model, self.threads, self.timeout = model, threads, timeout

    def read(self, crops: list[np.ndarray]) -> str:
        ok, buf = cv2.imencode(".png", stack(crops))
        options: dict = {"temperature": 0, "num_predict": 160}
        if self.threads > 0:
            options["num_thread"] = self.threads
        body = {
            "model": self.model,
            "prompt": OLLAMA_PROMPT,
            "images": [base64.b64encode(buf.tobytes()).decode()],
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": options,
        }
        request = urllib.request.Request(
            self.url, json.dumps(body).encode(), {"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.loads(response.read())["response"]


# ------------------------------------------------------------------ extractor


class OcrExtractor:
    """`CoordinateExtractor` that reads the F3 columns with an OCR engine."""

    def __init__(self, engine: OcrEngine, detector_config: F3DetectorConfig | None = None) -> None:
        self.engine = engine
        self.detector_config = detector_config
        # Engines are not guaranteed to be thread safe, and parallel runs only fight for the CPU.
        self._lock = threading.Lock()

    def extract(self, frame_bgr: np.ndarray, detection: F3Detection) -> ExtractionResult | None:
        crops = column_crops(frame_bgr, detection, self.engine.target_gui, self.detector_config)
        if not crops:
            return None
        started = time.perf_counter()
        with self._lock:
            text = self.engine.read(crops)
        parsed = parse_f3_text(text)
        return ExtractionResult(
            x=parsed.x,
            y=parsed.y,
            z=parsed.z,
            confirmed=parsed.confirmed,
            biome=parsed.biome,
            dimension=parsed.dimension,
            facing=parsed.facing,
            raw_text=text,
            engine=self.engine.name,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
        )


def create_engine(
    name: str,
    *,
    threads: int = 2,
    model_dir: Path | None = None,
    ollama_url: str = "http://127.0.0.1:11434",
    ollama_model: str = "qwen3-vl:2b-instruct",
) -> OcrEngine | None:
    if name == "none":
        return None
    if name in PADDLE_PRESETS:
        return PaddleEngine(name, threads, model_dir)
    if name == "ollama":
        return OllamaEngine(ollama_url, ollama_model, threads)
    raise ValueError(f"unknown OCR engine {name!r}, expected one of {', '.join(ENGINES)}")
