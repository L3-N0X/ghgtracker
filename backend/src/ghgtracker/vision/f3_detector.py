"""Detector for the Minecraft F3 debug screen.

The detector models how the game draws the debug overlay instead of looking for "bright text"
in general. In GUI pixels (one GUI pixel = ``s`` screen pixels, ``s`` being the GUI scale):

* every line sits on its own semi-transparent dark box, flush against the screen edge
  (left column left-aligned at x = 2, right column right-aligned at x = width - 2)
* the first line starts at y = 2, lines follow on a fixed pitch of exactly 9 GUI pixels
* inside one pitch, rows 0-6 carry the glyph bodies, row 7 only descenders and row 8 is
  always empty, so a column of F3 lines is a lattice of filled bands with thin empty gaps
* blank lines skip one pitch and have no box; left and right columns share the same lattice

Detection steps:

1. Normalize the resolution (native up to ~1200 px height, larger frames are area-downscaled,
   tiny ones upscaled) and cut out a strip along the left and the right edge. The right strip
   is mirrored, so both columns are "left-aligned" from here on.
2. Build a stroke mask: pixels that are a thin bright ridge, i.e. darker pixels on both sides
   horizontally or vertically within a few pixels. This keeps glyph strokes of any color
   (vanilla is #E0E0E0, BetterF3 and similar mods use colored text) and rejects large bright
   areas like sky, snow or quartz.
3. Estimate the line pitch from the autocorrelation of the per-row stroke counts, then fit the
   lattice (pitch + top offset) jointly to both strips. A lattice line counts when its body rows
   are filled, its empty row is (nearly) empty and its strokes reach far enough from the edge to
   be text (icon columns of stream overlays don't).
4. Verify each column: its lines start at one shared anchor close to the screen edge, and the
   column has the vertical signature of the debug font (text fills 7 of 9 rows of a pitch).
5. Decide from the number of lines found in each column, counted from the top. A single column
   (the other one may be hidden behind a facecam) additionally has to be drawn in a pixel font:
   its glyph edges must sit on the GUI pixel grid, which anti-aliased chat text does not.

No OCR happens here: this runs on every captured frame and stays at a few milliseconds.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

# Line layout in GUI pixels.
LINE_PITCH = 9
BODY_ROWS = (2, 3, 4, 5, 6)  # rows every line has strokes in (row 0-1 only for tall glyphs)
EMPTY_ROW = 8
TEXT_ROWS = 8  # rows 0..7 hold glyphs


@dataclass(frozen=True)
class F3DetectorConfig:
    # Working resolution: frames taller than max_height are downscaled to target_height,
    # frames shorter than min_height are upscaled to it.
    max_height: int = 1200
    target_height: int = 1080
    min_height: int = 720
    # Part of the frame searched for each column (fractions of width / height).
    strip_width: float = 0.3
    strip_height: float = 0.78
    # Stroke mask: minimum brightness (max RGB channel) of a text pixel and how much darker the
    # surrounding background has to be within `stroke_window` px on both sides.
    min_brightness: int = 140
    min_contrast: int = 36
    stroke_window: int = 6
    # Plausible GUI scales in working pixels (a 720p stream of GUI scale 2 at 1080p is ~0.67*2).
    min_gui_scale: float = 0.75
    max_gui_scale: float = 6.0
    # A lattice line: at least this many of the BODY_ROWS hold strokes, and its empty row holds
    # at most `max_empty_ratio` of the strokes of an average body row.
    min_filled_body_rows: int = 4
    max_empty_ratio: float = 0.22
    # Lines start at the column anchor; allowed deviation in GUI pixels.
    anchor_tolerance: float = 2.2
    # The anchor has to be close to the screen edge: GUI pixels + fraction of the width.
    max_anchor_gui: float = 6.0
    max_anchor_width: float = 0.012
    # A column ends after this many lattice lines without text (F3 has single blank lines).
    max_gap_lines: int = 2
    # Vertical signature of a column: averaged over its lines, at least `min_text_rows` of the 9
    # rows of a pitch hold strokes (>= 20% of the line's busiest row) and one row is (nearly)
    # empty. Text with looser line spacing, like most chat overlays, fills far fewer rows.
    min_text_rows: int = 6
    max_gap_row: float = 0.12
    # Decision: lines found in the stronger / weaker column.
    min_lines_both: int = 3
    min_lines_total: int = 8
    min_lines_single: int = 12
    # ...and only if its glyph edges sit on the GUI pixel grid like the game's pixel font does
    # (0 = random sub-pixel positions as with anti-aliased chat fonts, 1 = perfectly on grid).
    min_single_grid: float = 0.15


@dataclass
class ColumnAnalysis:
    line_count: int = 0
    starts_at_top: bool = False
    pitch: float | None = None  # in source pixels
    anchor: float | None = None  # x distance of the text from the screen edge, source pixels
    grid: float = 0.0  # how well glyph edges align with the GUI pixel grid, 0..1
    # Detected lines in source pixel coordinates: (x1, y1, x2, y2)
    boxes: list[tuple[int, int, int, int]] = field(default_factory=list)


@dataclass
class F3Detection:
    detected: bool
    confidence: float
    left: ColumnAnalysis
    right: ColumnAnalysis
    gui_scale: float | None  # estimated GUI scale in source pixels
    work_scale: float  # working resolution / source resolution
    elapsed_ms: float

    def to_dict(self) -> dict:
        data = asdict(self)
        data["left"].pop("boxes")
        data["right"].pop("boxes")
        return data


@dataclass
class _Strip:
    mask: np.ndarray  # bool (h, w), stroke pixels, mirrored for the right side
    counts: np.ndarray  # int32 (h, w + 1), per-row cumulative stroke counts along x
    first_x: np.ndarray  # float (h,), x of the first stroke pixel in each row, inf if none


@dataclass
class _Fit:
    pitch: float
    top: float
    left: np.ndarray  # bool per lattice line: line found in the left column
    right: np.ndarray
    left_anchor: float | None
    right_anchor: float | None
    left_grid: float = 0.0
    right_grid: float = 0.0

    @property
    def score(self) -> int:
        return int(self.left.sum() + self.right.sum())


class F3Detector:
    def __init__(self, config: F3DetectorConfig | None = None) -> None:
        self.config = config or F3DetectorConfig()

    # ------------------------------------------------------------------ public

    def detect(self, frame_bgr: np.ndarray) -> F3Detection:
        started = time.perf_counter()
        cfg = self.config
        src_h, src_w = frame_bgr.shape[:2]

        scale = 1.0
        if src_h > cfg.max_height:
            scale = cfg.target_height / src_h
        elif src_h < cfg.min_height:
            scale = cfg.min_height / src_h
        work_h = round(src_h * scale)
        work_w = round(src_w * scale)

        strip_w = max(8, int(src_w * cfg.strip_width))
        strip_h = max(8, int(src_h * cfg.strip_height))
        left = self._prepare(frame_bgr[:strip_h, :strip_w], scale)
        right = self._prepare(cv2.flip(frame_bgr[:strip_h, src_w - strip_w :], 1), scale)

        fit = self._fit(left, right, work_w)
        left_col = self._column(fit, left, scale, src_w, mirrored=False)
        right_col = self._column(fit, right, scale, src_w, mirrored=True)

        n_left, n_right = left_col.line_count, right_col.line_count
        strong, weak = max(n_left, n_right), min(n_left, n_right)
        strong_col = left_col if n_left >= n_right else right_col
        detected = (weak >= cfg.min_lines_both and strong + weak >= cfg.min_lines_total) or (
            # One column alone (a facecam may cover the other one) needs stronger evidence.
            strong >= cfg.min_lines_single and strong_col.grid >= cfg.min_single_grid
        )
        confidence = self._confidence(strong, weak, detected)

        return F3Detection(
            detected=detected,
            confidence=round(confidence, 3),
            left=left_col,
            right=right_col,
            gui_scale=round(fit.pitch / LINE_PITCH / scale, 2) if fit and fit.score else None,
            work_scale=round(work_h / src_h, 4) if src_h else 1.0,
            elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    # ------------------------------------------------------------------ stroke mask

    def _prepare(self, region_bgr: np.ndarray, scale: float) -> _Strip:
        region = region_bgr
        if scale != 1.0:
            size = (max(1, round(region.shape[1] * scale)), max(1, round(region.shape[0] * scale)))
            interpolation = cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR
            region = cv2.resize(region, size, interpolation=interpolation)
        if region.ndim == 2:
            value = region
        else:
            # Brightest channel, so colored text (BetterF3 etc.) counts like white text.
            b, g, r = cv2.split(region)[:3]
            value = cv2.max(cv2.max(b, g), r)
        mask = self._stroke_mask(value)
        # Per-row cumulative stroke counts along x, (h, w + 1); much faster than np.cumsum.
        integral = cv2.integral(mask.view(np.uint8))
        counts = integral[1:] - integral[:-1]
        has = counts[:, -1] > 0
        first_x = np.where(has, np.argmax(mask, axis=1), np.inf).astype(np.float64)
        return _Strip(mask=mask, counts=counts, first_x=first_x)

    def _stroke_mask(self, value: np.ndarray) -> np.ndarray:
        cfg = self.config
        k = cfg.stroke_window
        h_kernel = np.ones((1, k), np.uint8)
        v_kernel = np.ones((k, 1), np.uint8)
        threshold = cv2.subtract(value, cfg.min_contrast)  # saturates at 0

        def darker(kernel: np.ndarray, anchor: tuple[int, int]) -> np.ndarray:
            # Minimum over the k pixels ending (or starting) at each pixel.
            local_min = cv2.erode(value, kernel, anchor=anchor, borderType=cv2.BORDER_REPLICATE)
            return local_min <= threshold

        horizontal = darker(h_kernel, (k - 1, 0)) & darker(h_kernel, (0, 0))
        vertical = darker(v_kernel, (0, k - 1)) & darker(v_kernel, (0, 0))
        return (value >= cfg.min_brightness) & (horizontal | vertical)

    # ------------------------------------------------------------------ lattice fit

    def _pitch_candidates(self, left: _Strip, right: _Strip, work_w: int) -> list[float]:
        cfg = self.config
        lo = LINE_PITCH * cfg.min_gui_scale
        hi = LINE_PITCH * cfg.max_gui_scale
        window = max(8, int(work_w * 0.12))
        acf_sum = None
        for strip in (left, right):
            profile = strip.counts[:, min(window, strip.counts.shape[1] - 1)].astype(np.float64)
            profile -= profile.mean()
            energy = float(profile @ profile)
            if energy <= 0:
                continue
            n = len(profile)
            spectrum = np.fft.rfft(profile, 2 * n)
            acf = np.fft.irfft(spectrum * np.conj(spectrum))[:n] / energy
            acf_sum = acf if acf_sum is None else acf_sum + acf
        if acf_sum is None:
            return []
        lags = np.arange(len(acf_sum))
        valid = (lags >= lo) & (lags <= min(hi, len(acf_sum) - 2))
        peaks = [
            int(i)
            for i in np.flatnonzero(valid)
            if acf_sum[i] > 0 and acf_sum[i] >= acf_sum[i - 1] and acf_sum[i] >= acf_sum[i + 1]
        ]
        peaks.sort(key=lambda i: acf_sum[i], reverse=True)
        candidates: list[float] = []
        for peak in peaks[:4]:
            # Sub-pixel peak position from a parabola through the three samples.
            a, b, c = acf_sum[peak - 1], acf_sum[peak], acf_sum[peak + 1]
            denom = a - 2 * b + c
            offset = 0.5 * (a - c) / denom if denom else 0.0
            for lag in (peak + offset, (peak + offset) / 2):
                if lo <= lag <= hi and all(abs(lag / p - 1) > 0.01 for p in candidates):
                    candidates.append(float(lag))
        return candidates

    def _fit(self, left: _Strip, right: _Strip, work_w: int) -> _Fit | None:
        candidates = self._pitch_candidates(left, right, work_w)
        if not candidates:
            return None
        # Coarse: +-1.2% around every autocorrelation peak, scored on the first lines only so
        # a small pitch error cannot accumulate over a long column.
        pitches = (np.array(candidates)[:, None] * (1 + 0.004 * np.arange(-3, 4))).ravel()
        offsets = np.linspace(0.0, 0.8, 17)[None, :] * pitches[:, None]
        pitch, top = self._best_lattice(left, right, pitches, offsets, max_lines=16)
        if pitch is None:
            return None
        # Fine: +-0.4% and +-5% of a pitch around the winner, over the whole column.
        pitches = pitch * (1 + 0.0005 * np.arange(-8, 9))
        offsets = top + np.linspace(-0.05, 0.05, 5)[None, :] * pitches[:, None]
        pitch, top = self._best_lattice(left, right, pitches, offsets, max_lines=None)
        if pitch is None:
            return None
        left_lines = self._lattice_lines(left, np.array([pitch]), np.array([[top]]))[0, 0]
        right_lines = self._lattice_lines(right, np.array([pitch]), np.array([[top]]))[0, 0]
        # Every column has to start its lines at one anchor close to the screen edge.
        left_ok, left_anchor = self._check_anchor(left, pitch, top, left_lines, work_w)
        right_ok, right_anchor = self._check_anchor(right, pitch, top, right_lines, work_w)
        if not self._has_line_signature(left, pitch, top, self._run_mask(left_ok)):
            left_ok, left_anchor = np.zeros_like(left_ok), None
        if not self._has_line_signature(right, pitch, top, self._run_mask(right_ok)):
            right_ok, right_anchor = np.zeros_like(right_ok), None
        left_ok, right_ok = self._run_mask(left_ok), self._run_mask(right_ok)
        return _Fit(
            pitch=pitch,
            top=top,
            left=left_ok,
            right=right_ok,
            left_anchor=left_anchor,
            right_anchor=right_anchor,
            left_grid=self._grid_coherence(left, pitch, top, left_ok, left_anchor),
            right_grid=self._grid_coherence(right, pitch, top, right_ok, right_anchor),
        )

    def _best_lattice(
        self,
        left: _Strip,
        right: _Strip,
        pitches: np.ndarray,
        offsets: np.ndarray,
        max_lines: int | None,
    ) -> tuple[float | None, float]:
        left_runs = self._run_lengths(self._lattice_lines(left, pitches, offsets, max_lines))
        right_runs = self._run_lengths(self._lattice_lines(right, pitches, offsets, max_lines))
        # Most lines in total; on a tie prefer lattices that both columns agree on.
        score = (left_runs + right_runs) * 1000 + np.minimum(left_runs, right_runs)
        p, t = np.unravel_index(int(np.argmax(score)), score.shape)
        if left_runs[p, t] + right_runs[p, t] == 0:
            return None, 0.0
        return float(pitches[p]), float(offsets[p, t])

    def _lattice_lines(
        self,
        strip: _Strip,
        pitches: np.ndarray,
        offsets: np.ndarray,
        max_lines: int | None = None,
    ) -> np.ndarray:
        """Classify lattice lines: (pitch, top offset, line) -> looks like a line of F3 text."""
        cfg = self.config
        h = strip.mask.shape[0]
        gui = pitches / LINE_PITCH
        n_lines = int(h // pitches.min())
        if max_lines is not None:
            n_lines = min(n_lines, max_lines)
        # Count strokes in a window starting at the screen edge, roughly 44 GUI px wide: every F3
        # line is longer than that, and it keeps unrelated structures further in out of the count.
        windows = np.clip(np.rint(44 * gui), 4, strip.counts.shape[1] - 1).astype(np.intp)
        profiles = strip.counts[:, windows].T.ravel()  # (pitch, row) flattened
        # Strokes between 24 and 34 GUI px from the edge: text lines are wide (even "Misc: 0" is
        # ~34 GUI px), unlike columns of icons such as the player heads of stream overlays.
        far_lo = np.clip(np.rint(24 * gui), 1, strip.counts.shape[1] - 1).astype(np.intp)
        far_hi = np.clip(np.rint(34 * gui), 1, strip.counts.shape[1] - 1).astype(np.intp)
        far = (strip.counts[:, far_hi] - strip.counts[:, far_lo]).T.ravel()
        base = (np.arange(len(pitches)) * h)[:, None, None]
        line_tops = offsets[:, :, None] + np.arange(n_lines)[None, None, :] * pitches[:, None, None]
        inside = line_tops + LINE_PITCH * gui[:, None, None] <= h
        gui4 = gui[:, None, None, None]
        body_rows = np.rint(line_tops[..., None] + (np.array(BODY_ROWS) + 0.5) * gui4)
        body_rows = np.clip(body_rows, 0, h - 1).astype(np.intp)
        empty_rows = np.rint(line_tops + (EMPTY_ROW + 0.5) * gui[:, None, None])
        empty_rows = np.clip(empty_rows, 0, h - 1).astype(np.intp)
        body = profiles[body_rows + base[..., None]]
        wide = (far[body_rows + base[..., None]] > 0).sum(axis=-1) >= 3
        empty = profiles[empty_rows + base]
        min_fill = np.maximum(2.0, 1.5 * gui)[:, None, None]
        filled = (body >= min_fill[..., None]).sum(axis=-1)
        body_mean = body.mean(axis=-1)
        return (
            inside
            & (filled >= cfg.min_filled_body_rows)
            & (empty <= cfg.max_empty_ratio * body_mean + 0.5)
            & (body_mean >= 2 * min_fill)
            & wide
        )

    def _has_line_signature(
        self, strip: _Strip, pitch: float, top: float, lines: np.ndarray
    ) -> bool:
        idx = np.flatnonzero(lines)
        if len(idx) == 0:
            return True
        cfg = self.config
        h = strip.mask.shape[0]
        gui = pitch / LINE_PITCH
        window = min(strip.counts.shape[1] - 1, max(4, round(44 * gui)))
        rows = top + idx[:, None] * pitch + (np.arange(LINE_PITCH) + 0.5)[None, :] * gui
        rows = np.clip(np.rint(rows), 0, h - 1).astype(np.intp)
        values = strip.counts[rows, window].astype(np.float64)
        folded = (values / np.maximum(values.max(axis=1, keepdims=True), 1)).mean(axis=0)
        return bool((folded >= 0.2).sum() >= cfg.min_text_rows and folded.min() <= cfg.max_gap_row)

    def _grid_coherence(
        self, strip: _Strip, pitch: float, top: float, lines: np.ndarray, anchor: float | None
    ) -> float:
        """How well stroke edges line up with the GUI pixel grid that starts at the anchor.

        The game font is drawn in whole GUI pixels, so every left and right stroke edge lies on
        anchor + k * gui_scale. Edges of anti-aliased fonts land on arbitrary sub-pixel positions
        and average out to ~0. Downscaled streams (fractional GUI scale) still score ~0.2-0.4.
        """
        idx = np.flatnonzero(lines)
        if anchor is None or len(idx) == 0:
            return 0.0
        h, w = strip.mask.shape
        gui = pitch / LINE_PITCH
        rows = top + idx[:, None] * pitch + (np.arange(1, 7) + 0.5)[None, :] * gui
        rows = np.clip(np.rint(rows), 0, h - 1).astype(np.intp).ravel()
        x2 = min(w, int(anchor + 44 * gui))
        if x2 < 3:
            return 0.0
        band = strip.mask[rows, :x2].view(np.int8)
        edges = np.flatnonzero(np.diff(band, axis=1).ravel() != 0) % (x2 - 1) + 1
        if len(edges) < 20:
            return 0.0
        phase = 2 * np.pi * (edges - anchor) / gui
        return float(np.hypot(np.cos(phase).mean(), np.sin(phase).mean()))

    def _run_lengths(self, lines: np.ndarray) -> np.ndarray:
        """Number of lines in the column that starts at the top, per top offset."""
        return self._run_mask(lines).sum(axis=-1)

    def _run_mask(self, lines: np.ndarray) -> np.ndarray:
        """Keep the lines of the run that starts within the first lines and ends at a long gap."""
        if lines.shape[-1] == 0:
            return lines
        idx = np.arange(lines.shape[-1])
        last = np.maximum.accumulate(np.where(lines, idx, -1), axis=-1)
        gap = idx - last
        ended = np.maximum.accumulate(gap > self.config.max_gap_lines, axis=-1)
        return lines & ~ended

    def _check_anchor(
        self, strip: _Strip, pitch: float, top: float, lines: np.ndarray, work_w: int
    ) -> tuple[np.ndarray, float | None]:
        cfg = self.config
        h = strip.mask.shape[0]
        gui = pitch / LINE_PITCH
        lines = self._run_mask(lines)
        idx = np.flatnonzero(lines)
        if len(idx) == 0:
            return lines, None
        anchors = np.empty(len(idx))
        for j, i in enumerate(idx):
            y1 = max(0, int(round(top + i * pitch)))
            y2 = min(h, int(round(top + i * pitch + TEXT_ROWS * gui)))
            anchors[j] = strip.first_x[y1:y2].min() if y2 > y1 else np.inf
        finite = anchors[np.isfinite(anchors)]
        if len(finite) == 0:
            return np.zeros_like(lines), None
        # The anchor is the start position shared by most lines.
        tol = max(1.5, cfg.anchor_tolerance * gui)
        support = [(np.abs(finite - a) <= tol).sum() for a in finite]
        anchor = float(np.median(finite[np.abs(finite - finite[int(np.argmax(support))]) <= tol]))
        if anchor > cfg.max_anchor_gui * gui + cfg.max_anchor_width * work_w:
            return np.zeros_like(lines), None
        ok = lines.copy()
        ok[idx] = np.abs(anchors - anchor) <= tol
        return ok, anchor

    # ------------------------------------------------------------------ results

    def _column(
        self,
        fit: _Fit | None,
        strip: _Strip,
        scale: float,
        src_w: int,
        mirrored: bool,
    ) -> ColumnAnalysis:
        result = ColumnAnalysis()
        if fit is None:
            return result
        lines = fit.right if mirrored else fit.left
        if not lines.any():
            return result
        gui = fit.pitch / LINE_PITCH
        idx = np.flatnonzero(lines)
        result.line_count = len(idx)
        result.starts_at_top = bool(idx[0] <= 1)
        result.pitch = round(fit.pitch / scale, 3)
        anchor = fit.right_anchor if mirrored else fit.left_anchor
        result.grid = round(fit.right_grid if mirrored else fit.left_grid, 3)
        result.anchor = round(anchor / scale, 1) if anchor is not None else None
        h, w = strip.mask.shape
        inv = 1.0 / scale
        for i in idx:
            y1 = max(0, int(round(fit.top + i * fit.pitch)))
            y2 = min(h, int(round(fit.top + i * fit.pitch + TEXT_ROWS * gui)))
            cols = np.flatnonzero(strip.mask[y1:y2].any(axis=0))
            if len(cols) == 0:
                continue
            # The line ends where the strokes stop: allow word gaps of up to ~6 GUI px.
            gaps = np.flatnonzero(np.diff(cols) > 6 * gui)
            x1, x2 = int(cols[0]), int(cols[gaps[0]] if len(gaps) else cols[-1])
            box = (x1 * inv, y1 * inv, (x2 + 1) * inv, y2 * inv)
            if mirrored:
                box = (src_w - box[2], box[1], src_w - box[0], box[3])
            result.boxes.append(tuple(int(round(v)) for v in box))  # type: ignore[arg-type]
        return result

    def _confidence(self, strong: int, weak: int, detected: bool) -> float:
        cfg = self.config
        if not detected:
            # How close the frame came to the decision thresholds.
            both = min(weak / cfg.min_lines_both, 1.0) * min(
                (strong + weak) / cfg.min_lines_total, 1.0
            )
            closeness = max(both, strong / cfg.min_lines_single)
            return min(0.49, 0.49 * closeness)
        evidence = strong + weak
        return min(1.0, 0.6 + 0.4 * min(1.0, (evidence - cfg.min_lines_total) / 16))


def draw_overlay(frame_bgr: np.ndarray, detection: F3Detection) -> np.ndarray:
    """Return a copy of the frame with the detected F3 lines boxed (debug preview)."""
    out = frame_bgr.copy()
    h = out.shape[0]
    color = (80, 220, 80) if detection.detected else (60, 160, 255)
    thickness = max(1, round(h / 720))
    pad = max(1, round(h / 1080))
    for column in (detection.left, detection.right):
        for x1, y1, x2, y2 in column.boxes:
            cv2.rectangle(out, (x1 - pad, y1 - pad), (x2 + pad, y2 + pad), color, thickness)
    label = (
        f"F3 {'OPEN' if detection.detected else 'closed'}  conf={detection.confidence:.2f}  "
        f"L={detection.left.line_count} R={detection.right.line_count}"
    )
    font_scale = h / 1080
    origin = (int(20 * font_scale), h - int(24 * font_scale))
    for ink, weight in (((0, 0, 0), int(6 * font_scale) + 1), (color, int(2 * font_scale) + 1)):
        cv2.putText(
            out, label, origin, cv2.FONT_HERSHEY_SIMPLEX, 1.1 * font_scale, ink, weight, cv2.LINE_AA
        )
    return out
