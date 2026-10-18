"""Synthetic Minecraft-like frames for exercising the F3 detector without a live stream.

F3 text is drawn the way the game draws it: a pixel font on the GUI pixel grid (glyph bodies in
rows 0-6, descenders in row 7 of a 9 GUI px line), light gray #E0E0E0 on per-line boxes of
#505050 at ~56% opacity, flush against the screen edge.
"""

from functools import cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

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

CHAT_LINES = [
    "viewer123: das ist ja krass",
    "Moderator: !discord for more",
    "pandalily: Ich hab mir CoffeeB gekauft.",
    "florence: einfach kapsel giveaway machen",
    "xXgamerXx: LUL",
    "nightbot: Follow on Twitter",
    "someone: was ist das fuer ein mod?",
    "chatter_42: GG",
] * 3


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


@cache
def _glyph_rows(text: str) -> np.ndarray:
    """Render `text` as a 1 bit pixel font with the game's metrics: (8 rows, width) bool."""
    font = ImageFont.load_default(size=9)  # bundled with Pillow: 6 px caps, 2 px descenders
    image = Image.new("L", (len(text) * 8 + 8, 16))
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"  # no anti-aliasing
    draw.text((0, 0), text, font=font, fill=255)
    ink = np.asarray(image) > 0
    top = font.getbbox("H")[1]
    # 6 cap rows -> 7 body rows (repeat the middle one), 2 descender rows -> 1.
    rows = [ink[top + r] for r in (0, 1, 2, 2, 3, 4, 5)]
    rows.append(ink[top + 6] | ink[top + 7])
    bitmap = np.array(rows)
    cols = np.flatnonzero(bitmap.any(axis=0))
    return bitmap[:, : cols[-1] + 1] if len(cols) else bitmap[:, :1]


def draw_debug_lines(
    frame: np.ndarray, lines: list[str], gui_scale: int, align: str = "left", top: int = 0
) -> np.ndarray:
    h, w = frame.shape[:2]
    s = gui_scale
    for i, text in enumerate(lines):
        if not text:
            continue  # blank lines have no box
        glyphs = np.kron(_glyph_rows(text), np.ones((s, s), bool))
        text_h, text_w = glyphs.shape
        y = top + (2 + 9 * i) * s
        x = 2 * s if align == "left" else w - 2 * s - text_w
        if y + 8 * s > h:
            break
        # Line box: one GUI px around the text, 0x90505050.
        y1, y2 = y - s, y + 8 * s
        x1, x2 = max(0, x - s), min(w, x + text_w + s)
        region = frame[y1:y2, x1:x2].astype(np.float32)
        frame[y1:y2, x1:x2] = (region * 0.44 + 80 * 0.56).astype(np.uint8)
        frame[y : y + text_h, x : x + text_w][glyphs] = (224, 224, 224)
    return frame


def draw_chat(
    frame: np.ndarray, lines: list[str], size: int = 16, x: int = 4, y: int = 4, spacing=1.2
) -> np.ndarray:
    """Anti-aliased chat-like text with per-line boxes, like a stream overlay."""
    image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert("RGBA")
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = ImageFont.load_default(size=size)
    pitch = round(size * spacing)
    for i, text in enumerate(lines):
        top = y + i * pitch
        width = draw.textlength(text, font=font)
        draw.rectangle([x - 4, top - 2, x + width + 4, top + pitch - 3], fill=(40, 40, 40, 140))
        draw.text((x, top), text, font=font, fill=(235, 235, 235, 255))
    image = Image.alpha_composite(image, overlay).convert("RGB")
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


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


def downscale(frame: np.ndarray, height: int) -> np.ndarray:
    """Simulate a lower stream quality, e.g. 1080p gameplay watched at 720p."""
    h, w = frame.shape[:2]
    return cv2.resize(frame, (round(w * height / h), height), interpolation=cv2.INTER_AREA)
