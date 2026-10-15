import cv2
import pytest

from ghgtracker.vision.f3_detector import F3Detector

from .synthetic import draw_debug_lines, f3_frame, game_background, jpeg_roundtrip

detector = F3Detector()


@pytest.mark.parametrize("gui_scale", [2, 3, 4])
@pytest.mark.parametrize("background", ["grass", "sky", "snow"])
def test_detects_f3_screen(gui_scale: int, background: str) -> None:
    frame = jpeg_roundtrip(f3_frame(gui_scale=gui_scale, background=background))
    result = detector.detect(frame)
    assert result.detected, result.to_dict()
    assert result.confidence >= 0.6
    assert result.left.starts_at_top


@pytest.mark.parametrize("size", [(1280, 720), (2560, 1440)])
def test_detects_at_other_resolutions(size: tuple[int, int]) -> None:
    w, h = size
    frame = jpeg_roundtrip(f3_frame(width=w, height=h, gui_scale=h // 360))
    assert detector.detect(frame).detected


def test_detects_left_column_only_when_right_is_covered() -> None:
    frame = jpeg_roundtrip(f3_frame(right=False))
    assert detector.detect(frame).detected


@pytest.mark.parametrize("background", ["grass", "sky", "snow"])
def test_plain_gameplay_is_not_f3(background: str) -> None:
    frame = jpeg_roundtrip(game_background(1920, 1080, background, seed=3))
    result = detector.detect(frame)
    assert not result.detected
    assert result.confidence < 0.5


def test_chat_overlay_is_not_f3() -> None:
    # A chat-like block of white lines in the lower-left area, not starting at the top.
    frame = game_background(1920, 1080, "grass", seed=5)
    chat = frame[500:1000, :900]
    draw_debug_lines(chat, ["viewer123: this is a chat message"] * 14, 2, "left")
    result = detector.detect(jpeg_roundtrip(frame))
    assert not result.detected


def test_overlay_marks_lines() -> None:
    from ghgtracker.vision.f3_detector import draw_overlay

    frame = f3_frame()
    result = detector.detect(frame)
    out = draw_overlay(frame, result)
    assert out.shape == frame.shape
    assert cv2.absdiff(out, frame).sum() > 0
