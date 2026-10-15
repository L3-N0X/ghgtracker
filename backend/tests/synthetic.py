"""Synthetic Minecraft-like frames for exercising the F3 detector without a live stream."""

import cv2
import numpy as np

LEFT_LINES = [
    "Minecraft 1.21.4 (1.21.4/vanilla)",
    "143 fps T: 144 vsync fancy fancy-clouds B: 2 GPU: 34%",
    "Integrated server @ 4.1 ms ticks, 12 tx, 2245 rx",
    "C: 497/15000 (s) D: 12, pC: 000, pU: 00, aB: 12",
    "E: 21/129, B: 0, SD: 12",
    "P: 1278. T: 129",
    "Chunks[C] W: 1849 E: 129,82,1043",
    "minecraft:overworld FC: 0",
    "",
    "XYZ: -1234.567 / 72.00000 / 845.210",
    "Block: -1235 72 845 [5 8 13]",
    "Chunk: -78 4 52 [7 -2 in r.-3.1.mca]",
    "Facing: north (Towards negative Z) (-178.3 / 12.4)",
    "Client Light: 15 (15 sky, 4 block)",
    "CH S: 71 M: 71",
    "SH S: 72 O: 63 M: 72 ML: 63",
    "Biome: minecraft:plains",
    "Local Difficulty: 2.25 // 0.75 (Day 3)",
]

RIGHT_LINES = [
    "Java: 21.0.3 64bit",
    "Mem: 41% 1702/4096MB",
    "Allocation rate: 412MB /s",
    "Allocated: 61% 2496MB",
    "",
    "CPU: 16x AMD Ryzen 7 5800X",
    "",
    "Display: 1920x1080 (NVIDIA)",
    "NVIDIA GeForce RTX 3070",
    "4.6.0 NVIDIA 550.54",
    "",
    "Targeted Block: -1236, 71, 845",
    "minecraft:grass_block",
    "snowy: false",
]


def game_background(width: int, height: int, kind: str = "grass", seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    frame = np.zeros((height, width, 3), np.uint8)
    if kind == "sky":
        # Bright, unsaturated-ish sky over the top, blocky terrain below.
        frame[: height * 2 // 3] = (235, 225, 205)
        frame[height * 2 // 3 :] = (60, 140, 80)
    elif kind == "snow":
        frame[:] = (245, 245, 240)
        noise = rng.integers(-12, 12, (height // 16 + 1, width // 16 + 1, 1))
        frame = np.clip(
            frame.astype(int) + np.kron(noise, np.ones((16, 16, 1)))[:height, :width], 0, 255
        )
        frame = frame.astype(np.uint8)
    else:
        # 16px "blocks" of green / brown noise
        blocks = rng.integers(30, 150, (height // 16 + 1, width // 16 + 1, 3)).astype(np.uint8)
        blocks[..., 1] = np.clip(blocks[..., 1].astype(int) + 40, 0, 255)
        frame = np.kron(blocks, np.ones((16, 16, 1), np.uint8))[:height, :width]
    return np.ascontiguousarray(frame)


def draw_debug_lines(
    frame: np.ndarray, lines: list[str], gui_scale: int, align: str = "left"
) -> np.ndarray:
    h, w = frame.shape[:2]
    line_h = 9 * gui_scale
    font = cv2.FONT_HERSHEY_PLAIN
    thickness = max(1, gui_scale - 1)
    # Glyph cells (incl. descenders) are 8 GUI px tall inside a 9 px line.
    (_, h1), b1 = cv2.getTextSize("Ag(|", font, 1.0, thickness)
    font_scale = 8 * gui_scale / (h1 + b1 + thickness)
    for i, text in enumerate(lines):
        if not text:
            continue
        (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
        y = 2 * gui_scale + i * line_h
        x = 2 * gui_scale if align == "left" else w - 2 * gui_scale - tw
        x1, x2 = x - gui_scale, x + tw + gui_scale
        y1, y2 = y - gui_scale, y + 8 * gui_scale
        region = frame[max(0, y1) : y2, max(0, x1) : x2].astype(np.float32)
        frame[max(0, y1) : y2, max(0, x1) : x2] = (region * 0.44 + 80 * 0.56).astype(np.uint8)
        cv2.putText(
            frame,
            text,
            (x, y + th),
            font,
            font_scale,
            (224, 224, 224),
            thickness,
            cv2.LINE_8,
        )
    return frame


def f3_frame(
    width: int = 1920,
    height: int = 1080,
    gui_scale: int = 2,
    background: str = "grass",
    right: bool = True,
    seed: int = 0,
) -> np.ndarray:
    frame = game_background(width, height, background, seed)
    draw_debug_lines(frame, LEFT_LINES, gui_scale, "left")
    if right:
        draw_debug_lines(frame, RIGHT_LINES, gui_scale, "right")
    return frame


def jpeg_roundtrip(frame: np.ndarray, quality: int = 60) -> np.ndarray:
    """Simulate stream compression artifacts."""
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)
