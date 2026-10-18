"""Compare OCR engines on reading the XYZ line of the F3 screen.

    uv run --with rapidocr --with onnxruntime --with "onnxtr[cpu]" --with pytesseract \
        taskset -c 0,2 python scripts/ocr_bench.py ppocr5-mobile tesseract ...

Ground truth comes from the file names in dataset/f3_open (``x_y_z_rot<yaw>_...``); files named
``no_coordinates*`` show an F3 screen whose XYZ line is hidden, so any reading there is a
hallucination. OCR only runs where the detector sees an F3 screen (like the tracker would), on
crops of the detected columns. Each frame is also tested as a 720p stream frame.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import os
import re
import resource
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from evaluate_detector import DATASET, load, stream  # noqa: E402

from ghgtracker.vision.f3_detector import F3Detection, F3Detector, F3DetectorConfig  # noqa: E402
from ghgtracker.vision.f3_text import LABEL, parse_f3_text  # noqa: E402
from ghgtracker.vision.ocr import _column_x, _scale, column_crops, stack  # noqa: E402

THREADS = 2
# Accuracy does not depend on the thread count: VLM runs may use more to finish in time.
VLM_THREADS = int(os.environ.get("BENCH_VLM_THREADS", THREADS))

# ------------------------------------------------------------------ ground truth / parsing


def truth(path: Path) -> tuple[float, float, float] | None:
    m = re.match(r"(-?[\d.]+)_(-?[\d.]+)_(-?[\d.]+)_rot", path.name)
    return tuple(float(v) for v in m.groups()) if m else None  # type: ignore[return-value]


# ------------------------------------------------------------------ crops


def line_crops(frame: np.ndarray, det: F3Detection, target_gui: float) -> list[np.ndarray]:
    """One crop per detected line (for recognizer-only engines), as wide as its column."""
    h, w = frame.shape[:2]
    gui = det.gui_scale or 2.0
    pad = int(math.ceil(2 * gui))
    limit = int(w * F3DetectorConfig().strip_width)
    crops = []
    for col, right in ((det.left, False), (det.right, True)):
        if not col.boxes:
            continue
        # Line boxes end at the first wide gap (BetterF3 separates values by double spaces),
        # so every line gets the width of the whole column.
        x1, x2 = _column_x(col, right, w, pad, limit)
        for _, y1, _, y2 in col.boxes:
            y1, y2 = max(0, y1 - pad), min(h, y2 + pad)
            crops.append(_scale(frame[y1:y2, x1:x2], target_gui / gui))
    return crops


# ------------------------------------------------------------------ engines


class Engine:
    target_gui = 3.0
    mode = "columns"  # or "lines" (recognizer only on detector line boxes) or "full"

    def read(self, images: list[np.ndarray]) -> str:
        raise NotImplementedError


class Tesseract(Engine):
    target_gui = 4.0

    def __init__(self) -> None:
        import pytesseract

        self.tess = pytesseract
        os.environ["OMP_THREAD_LIMIT"] = str(THREADS)

    def read(self, images):
        out = []
        for img in images:
            gray = 255 - cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            out.append(self.tess.image_to_string(gray, config="--psm 6"))
        return "\n".join(out)


class RapidOCREngine(Engine):
    def __init__(self, version: str, det: str, rec: str, lang: str, mode="columns",
                 target_gui: float = 3.0, early_exit: bool = False) -> None:
        from rapidocr import LangDet, LangRec, ModelType, OCRVersion, RapidOCR

        self.mode, self.target_gui, self.early_exit = mode, target_gui, early_exit
        params = {
            "Global.use_cls": False,
            "Global.log_level": "error",
            "EngineConfig.onnxruntime.intra_op_num_threads": THREADS,
            "EngineConfig.onnxruntime.inter_op_num_threads": 1,
            "Det.ocr_version": OCRVersion(version),
            "Det.model_type": ModelType(det),
            "Rec.ocr_version": OCRVersion(version),
            "Rec.model_type": ModelType(rec),
            "Rec.lang_type": LangRec(lang),
        }
        if version == "PP-OCRv6":
            params["Det.lang_type"] = LangDet("en")
        self.ocr = RapidOCR(params=params)

    def read(self, images):
        if self.mode == "lines":
            texts = []
            for img in images:
                res = self.ocr(img, use_det=False, use_cls=False, use_rec=True)
                texts += list(res.txts or [])
                # Stop one line after XYZ: the Block line below it confirms the reading.
                if self.early_exit and len(texts) > 1 and LABEL.search(texts[-2]):
                    break
            return "\n".join(texts)
        out = []
        for img in images:
            res = self.ocr(img)
            out.append("\n".join(merge_rows(res.boxes, res.txts)))
        return "\n".join(out)


def merge_rows(boxes, txts) -> list[str]:
    """Detection models may split a line into words: join boxes on the same row."""
    if boxes is None or txts is None:
        return []
    items = sorted(
        ((float(np.mean(b[:, 1])), float(np.min(b[:, 0])), float(np.ptp(b[:, 1])), t)
         for b, t in zip(boxes, txts, strict=True)),
    )
    rows: list[list] = []
    for cy, x, hgt, t in items:
        if rows and abs(rows[-1][0] - cy) < 0.5 * hgt:
            rows[-1][1].append((x, t))
        else:
            rows.append([cy, [(x, t)]])
    return [" ".join(t for _, t in sorted(parts)) for _, parts in rows]


class OnnxTREngine(Engine):
    def __init__(self, det: str, reco: str) -> None:
        import onnxruntime as ort
        from onnxtr.io import DocumentFile  # noqa: F401
        from onnxtr.models import EngineConfig, ocr_predictor

        so = ort.SessionOptions()
        so.intra_op_num_threads = THREADS
        so.inter_op_num_threads = 1
        cfg = EngineConfig(session_options=so, providers=["CPUExecutionProvider"])
        self.model = ocr_predictor(
            det_arch=det, reco_arch=reco, det_engine_cfg=cfg, reco_engine_cfg=cfg,
            reco_bs=64, assume_straight_pages=True, detect_orientation=False,
        )

    def read(self, images):
        rgb = [cv2.cvtColor(i, cv2.COLOR_BGR2RGB) for i in images]
        doc = self.model(rgb)
        lines = []
        for page in doc.pages:
            for block in page.blocks:
                for line in block.lines:
                    lines.append(" ".join(w.value for w in line.words))
        return "\n".join(lines)


class OllamaEngine(Engine):
    target_gui = 2.0
    url = "http://127.0.0.1:11434/api/generate"

    def __init__(self, model: str, prompt: str, num_predict: int = 96) -> None:
        self.model, self.prompt, self.num_predict = model, prompt, num_predict

    def read(self, images):
        ok, buf = cv2.imencode(".png", stack(images))
        body = {
            "model": self.model,
            "prompt": self.prompt,
            "images": [base64.b64encode(buf).decode()],
            "stream": False,
            "think": False,
            "keep_alive": "30m",
            "options": {"temperature": 0, "num_thread": VLM_THREADS, "num_gpu": 0,
                        "num_predict": self.num_predict, "num_ctx": 4096},
        }
        req = urllib.request.Request(self.url, json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            return json.loads(r.read())["response"]

    def runner_rss_mb(self) -> float | None:
        try:
            pids = subprocess.check_output(["pgrep", "-f", "ollama runner"], text=True).split()
            return max(int(re.search(r"VmHWM:\s+(\d+)", Path(f"/proc/{p}/status").read_text())
                           .group(1)) for p in pids) / 1024
        except Exception:
            return None


ASK_XYZ = (
    "This image shows the Minecraft F3 debug screen text. Copy the line that starts with "
    '"XYZ:" exactly as written. If there is no line starting with "XYZ:", answer NONE.'
)

ENGINES = {
    "tesseract": lambda: Tesseract(),
    "ppocr4-mobile": lambda: RapidOCREngine("PP-OCRv4", "mobile", "mobile", "en"),
    "ppocr5-mobile": lambda: RapidOCREngine("PP-OCRv5", "mobile", "mobile", "en"),
    "ppocr5-server": lambda: RapidOCREngine("PP-OCRv5", "server", "server", "ch"),
    "ppocr6-tiny": lambda: RapidOCREngine("PP-OCRv6", "tiny", "tiny", "en"),
    "ppocr6-small": lambda: RapidOCREngine("PP-OCRv6", "small", "small", "en"),
    "ppocr5-mobile-lines": lambda: RapidOCREngine("PP-OCRv5", "mobile", "mobile", "en", "lines"),
    "ppocr6-tiny-lines": lambda: RapidOCREngine("PP-OCRv6", "tiny", "tiny", "en", "lines"),
    "ppocr6-small-lines": lambda: RapidOCREngine("PP-OCRv6", "small", "small", "en", "lines"),
    "ppocr5-mobile-gui2": lambda: RapidOCREngine("PP-OCRv5", "mobile", "mobile", "en",
                                                 target_gui=2.0),
    "ppocr6-small-gui2": lambda: RapidOCREngine("PP-OCRv6", "small", "small", "en", target_gui=2.0),
    "ppocr6-tiny-gui2": lambda: RapidOCREngine("PP-OCRv6", "tiny", "tiny", "en", target_gui=2.0),
    "ppocr5-mobile-lines-exit": lambda: RapidOCREngine("PP-OCRv5", "mobile", "mobile", "en",
                                                       "lines", early_exit=True),
    "ppocr6-small-lines-exit": lambda: RapidOCREngine("PP-OCRv6", "small", "small", "en", "lines",
                                                      early_exit=True),
    "onnxtr-mobile": lambda: OnnxTREngine("db_mobilenet_v3_large", "crnn_mobilenet_v3_small"),
    "onnxtr-fast-parseq": lambda: OnnxTREngine("fast_base", "parseq"),
    "qwen3-vl-2b": lambda: OllamaEngine("qwen3-vl:2b-instruct", ASK_XYZ),
    "glm-ocr": lambda: OllamaEngine("glm-ocr", "Text Recognition:", num_predict=1200),
    "granite-vision-2b": lambda: OllamaEngine("granite3.2-vision:2b", ASK_XYZ),
}

VARIANTS = {"orig": lambda f: f, "720p": lambda f: stream(f, 720)}

# ------------------------------------------------------------------ run


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("engines", nargs="+", choices=sorted(ENGINES))
    parser.add_argument("--variants", default="orig,720p")
    parser.add_argument("--max-nocoord", type=int, help="only use this many no_coordinates*")
    parser.add_argument("--json", type=Path, help="append per-engine summaries here (jsonl)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    detector = F3Detector()
    frames = []
    paths = sorted((DATASET / "f3_open").glob("*"))
    if args.max_nocoord is not None:
        hidden = [p for p in paths if truth(p) is None]
        paths = [p for p in paths if truth(p) is not None] + hidden[: args.max_nocoord]
    for path in paths:
        frame = load(path)
        for name in args.variants.split(","):
            variant = VARIANTS[name](frame)
            if variant is not None:
                frames.append((path, name, variant, detector.detect(variant)))

    for engine_name in args.engines:
        engine = ENGINES[engine_name]()
        stats = {"engine": engine_name, "labeled": 0, "exact": 0, "block": 0, "numbers": 0,
                 "nocoord": 0, "hallucinated": 0, "confirmed": 0, "confirmed_wrong": 0,
                 "times": []}
        warm = True
        for path, variant, frame, det in frames:
            expected = truth(path)
            got, confirmed, text, elapsed = None, False, "", 0.0
            if det.detected:
                if engine.mode == "lines":
                    images = line_crops(frame, det, engine.target_gui)
                else:
                    images = column_crops(frame, det, engine.target_gui)
                if warm:  # first call loads models / allocates, keep it out of the timing
                    engine.read(images[:1])
                    warm = False
                started = time.perf_counter()
                text = engine.read(images)
                elapsed = time.perf_counter() - started
                stats["times"].append(elapsed)
                parsed = parse_f3_text(text)
                got = (parsed.x, parsed.y, parsed.z) if parsed.has_position else None
                confirmed = parsed.confirmed
            if expected is None:
                stats["nocoord"] += 1
                stats["hallucinated"] += got is not None
                ok = "ok " if got is None else "HAL"
            else:
                stats["labeled"] += 1
                hits = [got is not None and abs(g - e) < 5e-4
                        for g, e in zip(got or (0, 0, 0), expected, strict=True)]
                stats["numbers"] += sum(hits)
                stats["exact"] += all(hits)
                block = got is not None and all(
                    math.floor(a) == math.floor(b) for a, b in zip(got, expected, strict=True))
                stats["block"] += block
                stats["confirmed"] += confirmed
                stats["confirmed_wrong"] += confirmed and not all(hits)
                ok = "ok " if all(hits) else ("blk" if block else "ERR")
            if args.verbose or ok not in ("ok ",):
                mark = " (block ok)" if confirmed else ""
                print(f"  {engine_name:20s} {ok} {variant:4s} {elapsed:6.2f}s "
                      f"{path.name[:34]:34s} -> {got}{mark}", flush=True)
            if args.verbose and ok == "ERR":
                print("    " + "\n    ".join(text.splitlines()[:60]))
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
        if isinstance(engine, OllamaEngine):
            rss = engine.runner_rss_mb() or rss
        times = sorted(stats.pop("times"))
        summary = {
            **stats,
            "median_s": round(times[len(times) // 2], 3),
            "p90_s": round(times[int(len(times) * 0.9)], 3),
            "peak_rss_mb": round(rss),
        }
        n = summary["labeled"]
        print(f"{engine_name:20s} exact {summary['exact']}/{n}  block {summary['block']}/{n}  "
              f"numbers {summary['numbers']}/{3 * n}  hallucinated "
              f"{summary['hallucinated']}/{summary['nocoord']}  confirmed {summary['confirmed']} "
              f"(wrong {summary['confirmed_wrong']})  median {summary['median_s']}s  "
              f"p90 {summary['p90_s']}s  rss {summary['peak_rss_mb']} MB", flush=True)
        if args.json:
            with args.json.open("a") as f:
                f.write(json.dumps(summary) + "\n")


if __name__ == "__main__":
    main()
