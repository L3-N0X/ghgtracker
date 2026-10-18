from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from ghgtracker.vision.f3_detector import F3Detector, draw_overlay

from .synthetic import (
    CHAT_LINES,
    downscale,
    draw_chat,
    f3_frame,
    game_background,
    jpeg_roundtrip,
)

detector = F3Detector()

DATASET = Path(__file__).resolve().parents[1] / "dataset"
POSITIVES = sorted((DATASET / "f3_open").glob("*")) if DATASET.is_dir() else []
NEGATIVES = sorted((DATASET / "no_f3").glob("*")) if DATASET.is_dir() else []
# Images where the F3 text is too small to resolve at all (smaller than any stream quality).
KNOWN_MISSES = {"shader.jpg"}


def load(path: Path) -> np.ndarray:
    return cv2.cvtColor(np.asarray(Image.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)


def dataset_param(path: Path):
    marks = []
    if path.name in KNOWN_MISSES:
        marks.append(pytest.mark.xfail(reason="text below a resolvable size"))
    return pytest.param(path, id=path.name, marks=marks)


# ---------------------------------------------------------------- synthetic frames


@pytest.mark.parametrize("gui_scale", [2, 3, 4])
@pytest.mark.parametrize("background", ["grass", "sky", "snow"])
def test_detects_f3_screen(gui_scale: int, background: str) -> None:
    frame = jpeg_roundtrip(f3_frame(gui_scale=gui_scale, background=background))
    result = detector.detect(frame)
    assert result.detected, result.to_dict()
    assert result.confidence >= 0.6
    assert result.left.starts_at_top and result.right.starts_at_top
    assert result.gui_scale == pytest.approx(gui_scale, rel=0.02)


@pytest.mark.parametrize(
    ("width", "height", "gui_scale"), [(1280, 720, 2), (2560, 1440, 4), (3840, 2160, 4)]
)
def test_detects_at_other_resolutions(width: int, height: int, gui_scale: int) -> None:
    frame = jpeg_roundtrip(f3_frame(width=width, height=height, gui_scale=gui_scale))
    assert detector.detect(frame).detected


@pytest.mark.parametrize("height", [720, 480])
def test_detects_in_lower_stream_quality(height: int) -> None:
    frame = jpeg_roundtrip(downscale(f3_frame(gui_scale=2), height), quality=70)
    assert detector.detect(frame).detected


def test_detects_one_column_when_the_other_is_covered() -> None:
    left_only = detector.detect(jpeg_roundtrip(f3_frame(right=False)))
    assert left_only.detected, left_only.to_dict()
    assert left_only.right.line_count == 0

    covered = f3_frame()
    covered[:400, :700] = (60, 70, 90)  # facecam over the left column
    result = detector.detect(jpeg_roundtrip(covered))
    assert result.left.line_count == 0
    assert result.right.line_count > 0


@pytest.mark.parametrize("background", ["grass", "sky", "snow"])
def test_plain_gameplay_is_not_f3(background: str) -> None:
    frame = jpeg_roundtrip(game_background(1920, 1080, background, seed=3))
    result = detector.detect(frame)
    assert not result.detected
    assert result.confidence < 0.5


@pytest.mark.parametrize(("size", "spacing"), [(14, 1.15), (16, 1.2), (22, 1.15), (28, 1.3)])
@pytest.mark.parametrize("top", [4, 500])
def test_chat_overlay_is_not_f3(size: int, spacing: float, top: int) -> None:
    # Anti-aliased chat text on dark line boxes, flush left: at the very top, or further down.
    frame = draw_chat(game_background(1920, 1080, "grass", 5), CHAT_LINES, size, y=top)
    result = detector.detect(jpeg_roundtrip(frame))
    assert not result.detected, result.to_dict()


def test_icon_column_is_not_f3() -> None:
    # Player heads of a stream overlay: a regular column of small squares along the edge.
    frame = game_background(1920, 1080, "sky", 2)
    for i in range(12):
        y = 30 + i * 45
        frame[y : y + 32, 12:44] = (40, 120, 220)
        frame[y + 8 : y + 14, 18:26] = (250, 250, 250)
        frame[y + 8 : y + 14, 30:38] = (250, 250, 250)
    frame[:, -60:] = frame[:, 59::-1]  # same on the right
    assert not detector.detect(jpeg_roundtrip(frame)).detected


def test_overlay_marks_lines() -> None:
    frame = f3_frame()
    result = detector.detect(frame)
    out = draw_overlay(frame, result)
    assert out.shape == frame.shape
    assert cv2.absdiff(out, frame).sum() > 0
    # Boxes are in source coordinates: the first left line starts at the top-left corner.
    x1, y1, _, _ = result.left.boxes[0]
    assert x1 < 10 and y1 < 10


# ---------------------------------------------------------------- real screenshots


@pytest.mark.skipif(not POSITIVES, reason="dataset/f3_open not available")
@pytest.mark.parametrize("path", [dataset_param(p) for p in POSITIVES])
def test_dataset_f3_open(path: Path) -> None:
    frame = load(path)
    result = detector.detect(frame)
    assert result.detected, result.to_dict()
    if frame.shape[0] > 720:
        # The same frame in a 720p stream.
        assert detector.detect(jpeg_roundtrip(downscale(frame, 720), 70)).detected


@pytest.mark.skipif(not NEGATIVES, reason="dataset/no_f3 not available")
@pytest.mark.parametrize("path", [dataset_param(p) for p in NEGATIVES])
def test_dataset_no_f3(path: Path) -> None:
    frame = load(path)
    result = detector.detect(frame)
    assert not result.detected, result.to_dict()
    assert not detector.detect(jpeg_roundtrip(frame, 40)).detected
