"""Heuristic detector for the Minecraft F3 debug screen.

The debug overlay has a very distinct layout that survives Twitch compression well:

* light-gray text (#E0E0E0), unsaturated, on top of semi-transparent dark-gray line backgrounds
* a column of lines flush against the LEFT screen edge, starting at the very top
  (version, FPS, XYZ, Block, Chunk, Facing, Biome, ...)
* a second column flush against the RIGHT screen edge (Java version, memory, CPU, targeted block)
* all lines share the same height and sit on a fixed vertical pitch (9 GUI px * GUI scale),
  with occasional blank lines that skip exactly one pitch

The detector downsamples the frame to a fixed working height, builds a mask of "F3 text colored"
pixels, groups mask rows into horizontal text bands and then checks how many bands form an
aligned, evenly spaced column on each side. That structure is what distinguishes F3 from snow,
sky, white UI elements or a chat overlay.

No OCR happens here: this runs on (almost) every captured frame and must stay cheap (~ms).
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

WORK_HEIGHT = 720


@dataclass(frozen=True)
class F3DetectorConfig:
    # Text pixel color: bright and unsaturated (F3 text is #E0E0E0, compression lowers it a bit).
    text_min_brightness: int = 160
    text_max_saturation: int = 45
    # Text must be this much brighter than the darkened line background (#505050 at ~56% alpha)
    # on both sides of a stroke, within `stroke_window` pixels at working resolution.
    min_text_contrast: int = 40
    stroke_window: int = 4
    # Largest horizontal gap inside one line (fraction of frame width), e.g. between words.
    max_word_gap: float = 0.02
    # Region (fraction of the frame) searched for each column.
    roi_width: float = 0.5
    roi_height: float = 0.9
    # How close to the screen edge a column has to start (fraction of width).
    edge_tolerance: float = 0.03
    # A column must start this close to the top of the screen (fraction of height).
    top_tolerance: float = 0.08
    min_row_pixels: int = 2
    min_band_height: int = 3
    max_band_height: int = 48
    # Glyphs only cover part of their bounding box. Solid bright areas (sky, snow) are denser.
    min_band_density: float = 0.06
    max_band_density: float = 0.75
    # Allowed relative deviation of a line gap from a multiple of the base line pitch.
    pitch_tolerance: float = 0.22
    # Decision thresholds. The "primary" column is whichever side has more aligned lines.
    min_primary_lines: int = 6
    min_secondary_lines: int = 3
    # With this many lines in one column the other one is not required (facecam may cover it).
    strong_primary_lines: int = 10


@dataclass
class TextBand:
    top: int
    bottom: int
    left: int
    right: int
    pixels: int

    @property
    def height(self) -> int:
        return self.bottom - self.top + 1

    @property
    def width(self) -> int:
        return self.right - self.left + 1

    @property
    def density(self) -> float:
        return self.pixels / max(1, self.height * self.width)


@dataclass
class ColumnAnalysis:
    line_count: int = 0
    starts_at_top: bool = False
    pitch: float | None = None
    candidate_bands: int = 0
    # Bands in working-resolution coordinates of the full frame: (x1, y1, x2, y2)
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)


@dataclass
class F3Detection:
    detected: bool
    confidence: float
    left: ColumnAnalysis
    right: ColumnAnalysis
    work_scale: float  # working resolution / source resolution
    elapsed_ms: float

    def to_dict(self) -> dict:
        data = asdict(self)
        data["left"].pop("boxes")
        data["right"].pop("boxes")
        return data


class F3Detector:
    def __init__(self, config: F3DetectorConfig | None = None) -> None:
        self.config = config or F3DetectorConfig()

    def detect(self, frame_bgr: np.ndarray) -> F3Detection:
        started = time.perf_counter()
        cfg = self.config
        src_h, src_w = frame_bgr.shape[:2]
        scale = WORK_HEIGHT / src_h
        if src_h != WORK_HEIGHT:
            # Nearest neighbour keeps the thin text strokes at their original color.
            frame = cv2.resize(
                frame_bgr,
                (max(1, round(src_w * scale)), WORK_HEIGHT),
                interpolation=cv2.INTER_NEAREST,
            )
        else:
            frame = frame_bgr
        h, w = frame.shape[:2]
        roi_h = int(h * cfg.roi_height)
        roi_w = int(w * cfg.roi_width)

        left_mask = self._text_mask(frame[:roi_h, :roi_w])
        # Mirror the right half so the same "flush-left" analysis applies to right-aligned text.
        right_mask = self._text_mask(frame[:roi_h, w - roi_w :])[:, ::-1]

        left = self._analyze_column(left_mask, w, h)
        right = self._analyze_column(right_mask, w, h)
        right.boxes = [(w - 1 - x2, y1, w - 1 - x1, y2) for (x1, y1, x2, y2) in right.boxes]

        # Since 1.21.9 the F3 layout is customizable, so either side may hold most of the lines.
        primary, secondary = sorted((left, right), key=lambda c: c.line_count, reverse=True)
        detected = primary.starts_at_top and (
            (
                primary.line_count >= cfg.min_primary_lines
                and secondary.line_count >= cfg.min_secondary_lines
            )
            or primary.line_count >= cfg.strong_primary_lines
        )
        confidence = self._confidence(primary, secondary)
        if not detected:
            confidence = min(confidence, 0.49)

        return F3Detection(
            detected=detected,
            confidence=round(confidence, 3),
            left=left,
            right=right,
            work_scale=scale,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # ------------------------------------------------------------------ internals

    def _text_mask(self, roi: np.ndarray) -> np.ndarray:
        cfg = self.config
        b, g, r = cv2.split(roi)
        mx = cv2.max(cv2.max(b, g), r)
        mn = cv2.min(cv2.min(b, g), r)
        bright = (mn >= cfg.text_min_brightness) & (cv2.subtract(mx, mn) <= cfg.text_max_saturation)
        # F3 glyphs are thin strokes on a darkened line background: a text pixel is noticeably
        # brighter than its surroundings on BOTH sides, horizontally or vertically. Large bright
        # surfaces (sky, snow, quartz) and the outer edges of the line backgrounds fail this.
        k = cfg.stroke_window
        h_kernel = np.ones((1, k), np.uint8)
        v_kernel = np.ones((k, 1), np.uint8)

        def darker(kernel: np.ndarray, anchor: tuple[int, int]) -> np.ndarray:
            local_min = cv2.erode(mx, kernel, anchor=anchor, borderType=cv2.BORDER_REPLICATE)
            return cv2.subtract(mn, local_min) >= cfg.min_text_contrast

        horizontal = darker(h_kernel, (k - 1, 0)) & darker(h_kernel, (0, 0))
        vertical = darker(v_kernel, (0, k - 1)) & darker(v_kernel, (0, 0))
        return bright & (horizontal | vertical)

    def _find_bands(self, mask: np.ndarray, edge_px: int) -> list[TextBand]:
        """Group rows into text bands, only counting the run of text that starts at the edge."""
        cfg = self.config
        h, w = mask.shape
        gap = max(6, int(w / self.config.roi_width * cfg.max_word_gap))
        # Close word gaps so a whole line becomes one run, then keep the run touching the edge.
        closed = cv2.morphologyEx(
            mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((1, gap), np.uint8)
        ).astype(bool)
        starts_at_edge = mask[:, :edge_px].any(axis=1)
        closed[starts_at_edge, :edge_px] = True
        # Length of the leading run of each row (index of its first gap, or full width).
        run_end = np.where(closed.all(axis=1), w, np.argmin(closed, axis=1))
        run_end[~starts_at_edge] = 0
        run_mask = mask & (np.arange(w)[None, :] < run_end[:, None])

        row_counts = run_mask.sum(axis=1)
        is_text_row = row_counts >= cfg.min_row_pixels
        bands: list[TextBand] = []
        y = 0
        while y < h:
            if not is_text_row[y]:
                y += 1
                continue
            top = y
            # Lines are separated by 1-2 empty GUI pixel rows, so any empty row ends a line.
            while y + 1 < h and is_text_row[y + 1]:
                y += 1
            bottom = y
            band_mask = run_mask[top : bottom + 1]
            cols = np.flatnonzero(band_mask.any(axis=0))
            bands.append(
                TextBand(
                    top=top,
                    bottom=bottom,
                    left=int(cols[0]),
                    right=int(cols[-1]),
                    pixels=int(band_mask.sum()),
                )
            )
            y += 1
        return bands

    def _analyze_column(self, mask: np.ndarray, frame_w: int, frame_h: int) -> ColumnAnalysis:
        cfg = self.config
        edge_px = max(3, int(frame_w * cfg.edge_tolerance))
        bands = [
            b
            for b in self._find_bands(mask, edge_px)
            if cfg.min_band_height <= b.height <= cfg.max_band_height
            and cfg.min_band_density <= b.density <= cfg.max_band_density
            and b.width >= b.height  # a line of text is wider than tall
        ]
        result = ColumnAnalysis(candidate_bands=len(bands))
        if len(bands) < 2:
            return result

        # All F3 lines start at the same x: keep the bands that share the dominant left edge.
        anchor = int(np.median([b.left for b in bands]))
        align_tol = max(2, int(frame_w * 0.004))
        bands = [b for b in bands if abs(b.left - anchor) <= align_tol]
        if len(bands) < 2:
            return result

        # ...and the same glyph height.
        median_height = float(np.median([b.height for b in bands]))
        bands = [
            b for b in bands if abs(b.height - median_height) <= max(2.0, 0.45 * median_height)
        ]
        if len(bands) < 2:
            return result

        pitch = self._estimate_pitch(bands)
        if pitch is None:
            return result

        chain = self._longest_regular_chain(bands, pitch)
        result.line_count = len(chain)
        result.pitch = round(pitch, 2)
        result.starts_at_top = bool(chain) and chain[0].top <= frame_h * cfg.top_tolerance
        result.boxes = [(b.left, b.top, b.right, b.bottom) for b in chain]
        return result

    def _estimate_pitch(self, bands: list[TextBand]) -> float | None:
        """Find the line pitch that best explains the gaps between bands.

        Each gap votes for candidate pitches it is (close to) a 1x/2x/3x multiple of, weighted
        1/k, so a stray half-line fragment cannot pull the pitch down to a fraction of the real one.
        """
        tol = self.config.pitch_tolerance
        gaps = np.diff([b.top for b in bands]).astype(float)
        gaps = gaps[gaps > 0]
        if len(gaps) == 0:
            return None
        best_pitch, best_score = None, 0.0
        for candidate in np.unique(gaps):
            ratios = gaps / candidate
            steps = np.round(ratios)
            fits = (steps >= 1) & (steps <= 3) & (np.abs(ratios - steps) <= tol * steps)
            score = float((1.0 / steps[fits]).sum())
            if score > best_score:
                best_pitch, best_score = candidate, score
        if best_pitch is None:
            return None
        # Refine with the gaps that are direct neighbours at that pitch.
        direct = gaps[np.abs(gaps / best_pitch - 1) <= tol]
        return float(np.median(direct)) if len(direct) else float(best_pitch)

    def _longest_regular_chain(self, bands: list[TextBand], pitch: float) -> list[TextBand]:
        tol = self.config.pitch_tolerance
        best: list[TextBand] = []
        current: list[TextBand] = [bands[0]]
        for prev, band in zip(bands, bands[1:], strict=False):
            ratio = (band.top - prev.top) / pitch
            steps = round(ratio)
            # 1 = next line, 2-3 = blank separator line(s) in between
            if 1 <= steps <= 3 and abs(ratio - steps) <= tol * steps:
                current.append(band)
            else:
                if len(current) > len(best):
                    best = current
                current = [band]
        return current if len(current) > len(best) else best

    def _confidence(self, primary: ColumnAnalysis, secondary: ColumnAnalysis) -> float:
        cfg = self.config
        primary_score = min(primary.line_count / cfg.strong_primary_lines, 1.0)
        secondary_score = min(secondary.line_count / (cfg.min_secondary_lines * 2), 1.0)
        score = 0.65 * primary_score + 0.35 * secondary_score
        if primary.line_count >= cfg.strong_primary_lines:
            score = max(score, 0.8)
        if not primary.starts_at_top:
            score *= 0.5
        return score


def draw_overlay(frame_bgr: np.ndarray, detection: F3Detection) -> np.ndarray:
    """Return a copy of the frame with the detected F3 line boxes drawn on it (debug preview)."""
    out = frame_bgr.copy()
    inv = 1.0 / detection.work_scale
    color = (80, 220, 80) if detection.detected else (60, 160, 255)
    thickness = max(1, round(2 * inv / 1.5))
    for column in (detection.left, detection.right):
        for x1, y1, x2, y2 in column.boxes:
            cv2.rectangle(
                out,
                (int(x1 * inv) - 2, int(y1 * inv) - 2),
                (int(x2 * inv) + 2, int(y2 * inv) + 2),
                color,
                thickness,
            )
    label = (
        f"F3 {'OPEN' if detection.detected else 'closed'}  conf={detection.confidence:.2f}  "
        f"L={detection.left.line_count} R={detection.right.line_count}"
    )
    h = out.shape[0]
    font_scale = h / 1080
    cv2.putText(
        out,
        label,
        (int(20 * font_scale), h - int(24 * font_scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1 * font_scale,
        (0, 0, 0),
        int(6 * font_scale) + 1,
        cv2.LINE_AA,
    )
    cv2.putText(
        out,
        label,
        (int(20 * font_scale), h - int(24 * font_scale)),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.1 * font_scale,
        color,
        int(2 * font_scale) + 1,
        cv2.LINE_AA,
    )
    return out
