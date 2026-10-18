"""Run the F3 detector over the dataset and report how it does.

    uv run python scripts/evaluate_detector.py                # dataset/f3_open + dataset/no_f3
    uv run python scripts/evaluate_detector.py --overlays out # also write annotated images
    uv run python scripts/evaluate_detector.py some/dir/*.png # just print results for files

Every image is also tested as it would arrive from a lower stream quality (720p/480p) and with
heavy JPEG compression, since that is what the tracker sees on Twitch.
"""

from __future__ import annotations

import argparse
import statistics
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ghgtracker.vision.f3_detector import F3Detector, draw_overlay

DATASET = Path(__file__).resolve().parents[1] / "dataset"


def load(path: Path) -> np.ndarray:
    return cv2.cvtColor(np.asarray(Image.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)


def jpeg(frame: np.ndarray, quality: int) -> np.ndarray:
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def stream(frame: np.ndarray, height: int) -> np.ndarray | None:
    h, w = frame.shape[:2]
    if h <= height:
        return None
    small = cv2.resize(frame, (round(w * height / h), height), interpolation=cv2.INTER_AREA)
    return jpeg(small, 70)


VARIANTS = {
    "orig": lambda f: f,
    "jpeg40": lambda f: jpeg(f, 40),
    "720p": lambda f: stream(f, 720),
    "480p": lambda f: stream(f, 480),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", type=Path, help="images (default: the dataset)")
    parser.add_argument("--overlays", type=Path, help="write annotated originals here")
    args = parser.parse_args()

    if args.files:
        cases = [(None, p) for p in args.files]
    else:
        cases = [(True, p) for p in sorted((DATASET / "f3_open").glob("*"))]
        cases += [(False, p) for p in sorted((DATASET / "no_f3").glob("*"))]
    if args.overlays:
        args.overlays.mkdir(parents=True, exist_ok=True)

    detector = F3Detector()
    totals: dict[tuple[str, str], list[int]] = {}
    times: list[float] = []
    for expected, path in cases:
        frame = load(path)
        cells = []
        for name, make in VARIANTS.items():
            variant = make(frame)
            if variant is None:
                cells.append(f"{name}:   -   ")
                continue
            result = detector.detect(variant)
            times.append(result.elapsed_ms)
            lines = f"{result.left.line_count:2d}/{result.right.line_count:2d}"
            if expected is None:
                cells.append(f"{name}:{'F3 ' if result.detected else '-- '}{lines}")
                continue
            ok = result.detected == expected
            group = "f3_open" if expected else "no_f3"
            totals.setdefault((group, name), [0, 0])
            totals[(group, name)][0] += ok
            totals[(group, name)][1] += 1
            cells.append(f"{name}:{'ok ' if ok else 'XX '}{lines}")
            if name == "orig" and args.overlays:
                cv2.imwrite(str(args.overlays / f"{path.stem}.jpg"), draw_overlay(frame, result))
        print(f"{path.name[:40]:40} " + "  ".join(cells))

    if totals:
        print("\ncorrect (lines found left/right are shown per image)")
        for (group, name), (ok, n) in sorted(totals.items()):
            print(f"  {group:8} {name:7} {ok}/{n}")
    if times:
        median = statistics.median(times)
        print(f"\ndetection time: median {median:.1f} ms, max {max(times):.1f} ms")


if __name__ == "__main__":
    main()
