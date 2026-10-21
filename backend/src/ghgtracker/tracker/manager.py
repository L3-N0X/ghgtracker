"""Tracker workers: one background thread per streamer that is currently being tracked.

Per frame:  detect F3  ->  maintain the open/closed F3 event  ->  maybe store a snapshot.

Detection runs on every captured frame so even very short F3 openings are caught, while
snapshots are rate limited by `save_interval_seconds` (OCR + storage is the expensive part).
Snapshots are stored right away and read by the shared OCR worker in the background.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path

import cv2
import numpy as np
from pydantic import BaseModel
from sqlmodel import Session, select

from ghgtracker.capture.frame_source import (
    CaptureOptions,
    FrameSource,
    FrameSourceError,
    is_local_file,
    twitch_channel_url,
)
from ghgtracker.config import Settings
from ghgtracker.db import get_engine
from ghgtracker.events import EventBus
from ghgtracker.models import (
    F3Event,
    OcrStatus,
    SessionStatus,
    Snapshot,
    Streamer,
    TrackingSession,
    UTCDatetime,
    utcnow,
)
from ghgtracker.storage import get_store
from ghgtracker.tracker.ocr_worker import OcrWorker
from ghgtracker.vision.f3_detector import F3Detection, F3Detector, draw_overlay

logger = logging.getLogger(__name__)

STATS_INTERVAL_S = 0.5
DB_FLUSH_INTERVAL_S = 5.0


class TrackerState(StrEnum):
    idle = "idle"
    starting = "starting"
    running = "running"
    stopping = "stopping"
    stopped = "stopped"
    error = "error"


class TrackerStartRequest(BaseModel):
    source: str | None = None  # default: the streamer's live channel
    capture_fps: float | None = None
    save_interval_seconds: float | None = None
    save_images: bool | None = None


class TrackerStatus(BaseModel):
    streamer_id: int
    state: TrackerState = TrackerState.idle
    session_id: int | None = None
    started_at: UTCDatetime | None = None
    source: str | None = None
    capture_fps: float | None = None
    save_interval_seconds: float | None = None
    frames_processed: int = 0
    measured_fps: float = 0.0
    f3_frames: int = 0
    f3_events: int = 0
    snapshots_saved: int = 0
    f3_open: bool = False
    last_confidence: float = 0.0
    detect_ms: float = 0.0
    last_f3_at: UTCDatetime | None = None
    last_snapshot_at: UTCDatetime | None = None
    error: str | None = None


@dataclass
class _OpenEvent:
    id: int
    frame_count: int = 0
    peak_confidence: float = 0.0
    last_seen_at: datetime | None = None


class Tracker:
    def __init__(
        self,
        streamer: Streamer,
        request: TrackerStartRequest,
        settings: Settings,
        bus: EventBus,
        ocr: OcrWorker | None = None,
    ) -> None:
        assert streamer.id is not None
        self.streamer_id = streamer.id
        self.login = streamer.login
        self.settings = settings
        self.bus = bus
        self.detector = F3Detector()
        self.ocr = ocr

        self.source_url = (request.source or "").strip() or twitch_channel_url(streamer.login)
        self.capture_fps = request.capture_fps or settings.capture_fps
        self.save_interval = (
            request.save_interval_seconds
            if request.save_interval_seconds is not None
            else settings.save_interval_seconds
        )
        self.save_images = (
            request.save_images if request.save_images is not None else settings.save_images
        )

        self.status = TrackerStatus(
            streamer_id=self.streamer_id,
            state=TrackerState.starting,
            source=self.source_url,
            capture_fps=self.capture_fps,
            save_interval_seconds=self.save_interval,
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._source: FrameSource | None = None
        self._frame_lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._latest_detection: F3Detection | None = None

        self._event: _OpenEvent | None = None
        self._miss_streak = 0
        self._last_saved_mono: float | None = None
        self._started_mono = 0.0

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        with Session(get_engine()) as db:
            session = TrackingSession(
                streamer_id=self.streamer_id,
                source=self.source_url,
                capture_fps=self.capture_fps,
                save_interval_seconds=self.save_interval,
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            self.status.session_id = session.id
            self.status.started_at = session.started_at
        self._publish_status()
        self._thread = threading.Thread(target=self._run, name=f"tracker-{self.login}", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        if self.status.state in (TrackerState.starting, TrackerState.running):
            self.status.state = TrackerState.stopping
            self._publish_status()
        self._stop.set()
        if self._source is not None:
            self._source.close()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout)

    @property
    def active(self) -> bool:
        return self.status.state in (
            TrackerState.starting,
            TrackerState.running,
            TrackerState.stopping,
        )

    def preview_jpeg(self, overlay: bool = True, max_width: int = 960) -> bytes | None:
        with self._frame_lock:
            frame, detection = self._latest_frame, self._latest_detection
        if frame is None:
            return None
        if overlay and detection is not None:
            frame = draw_overlay(frame, detection)
        h, w = frame.shape[:2]
        if w > max_width:
            frame = cv2.resize(frame, (max_width, round(h * max_width / w)), cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None

    def _is_live_source(self) -> bool:
        if is_local_file(self.source_url):
            return False
        return not any(part in self.source_url for part in ("/videos/", "/clip/", "clips."))

    # ------------------------------------------------------------------ worker

    def _run(self) -> None:
        final_state, error = TrackerState.stopped, None
        try:
            self._source = FrameSource(
                self.source_url,
                CaptureOptions(
                    fps=self.capture_fps,
                    width=self.settings.capture_width,
                    height=self.settings.capture_height,
                    quality=self.settings.stream_quality,
                    ffmpeg_path=self.settings.ffmpeg_path,
                ),
            )
            if self._stop.is_set():
                return
            self._source.open()
            self._started_mono = time.monotonic()
            last_stats = last_flush = 0.0
            fps_window_start, fps_window_frames = time.monotonic(), 0
            for frame in self._source.frames():
                if self._stop.is_set():
                    break
                if self.status.state == TrackerState.starting:
                    self.status.state = TrackerState.running
                    self._publish_status()
                self._process(frame)

                now = time.monotonic()
                fps_window_frames += 1
                if now - fps_window_start >= 2.0:
                    self.status.measured_fps = round(
                        fps_window_frames / (now - fps_window_start), 1
                    )
                    fps_window_start, fps_window_frames = now, 0
                if now - last_stats >= STATS_INTERVAL_S:
                    last_stats = now
                    self._publish_status()
                if now - last_flush >= DB_FLUSH_INTERVAL_S:
                    last_flush = now
                    self._flush_session()
            else:
                # Source ran out by itself: fine for files / VODs, an error for live channels.
                if not self._stop.is_set() and self._is_live_source():
                    final_state, error = TrackerState.error, "stream ended"
        except FrameSourceError as exc:
            if not self._stop.is_set():
                final_state, error = TrackerState.error, str(exc)
        except Exception as exc:  # noqa: BLE001 - surface anything to the UI
            logger.exception("tracker for %s crashed", self.login)
            final_state, error = TrackerState.error, f"internal error: {exc}"
        finally:
            if self._source is not None:
                self._source.close()
            self._close_event()
            self.status.state = final_state
            self.status.error = error
            self.status.f3_open = False
            self._flush_session(final=True)
            self._publish_status()
            logger.info("tracker for %s finished: %s %s", self.login, final_state, error or "")

    def _process(self, frame: np.ndarray) -> None:
        detection = self.detector.detect(frame)
        with self._frame_lock:
            self._latest_frame, self._latest_detection = frame, detection

        st = self.status
        st.frames_processed += 1
        st.last_confidence = detection.confidence
        st.detect_ms = detection.elapsed_ms

        if detection.detected:
            now = utcnow()
            st.f3_frames += 1
            st.last_f3_at = now
            self._miss_streak = 0
            if self._event is None:
                self._open_event(now)
            assert self._event is not None
            self._event.frame_count += 1
            self._event.peak_confidence = max(self._event.peak_confidence, detection.confidence)
            self._event.last_seen_at = now

            mono = time.monotonic()
            if self._last_saved_mono is None or mono - self._last_saved_mono >= self.save_interval:
                self._last_saved_mono = mono
                self._save_snapshot(frame, detection, now)
        elif self._event is not None:
            self._miss_streak += 1
            if self._miss_streak >= self.settings.f3_close_grace_frames:
                self._close_event()

    # ------------------------------------------------------------------ persistence

    def _open_event(self, now: datetime) -> None:
        with Session(get_engine()) as db:
            event = F3Event(
                session_id=self.status.session_id,
                streamer_id=self.streamer_id,
                opened_at=now,
            )
            db.add(event)
            db.commit()
            db.refresh(event)
        assert event.id is not None
        self._event = _OpenEvent(id=event.id)
        self.status.f3_events += 1
        self.status.f3_open = True
        self.bus.publish(
            "f3.opened", streamer_id=self.streamer_id, event_id=event.id, at=now.isoformat()
        )
        self._publish_status()

    def _close_event(self) -> None:
        open_event, self._event = self._event, None
        self._miss_streak = 0
        if open_event is None:
            return
        closed_at = open_event.last_seen_at or utcnow()
        with Session(get_engine()) as db:
            event = db.get(F3Event, open_event.id)
            if event is not None:
                event.closed_at = closed_at
                event.frame_count = open_event.frame_count
                event.peak_confidence = open_event.peak_confidence
                db.add(event)
                db.commit()
        self.status.f3_open = False
        self.bus.publish(
            "f3.closed",
            streamer_id=self.streamer_id,
            event_id=open_event.id,
            frame_count=open_event.frame_count,
            at=closed_at.isoformat(),
        )
        self._publish_status()

    def _save_snapshot(self, frame: np.ndarray, detection: F3Detection, now: datetime) -> None:
        image_rel: str | None = None
        if self.save_images:
            rel = Path(self.login) / str(self.status.session_id) / f"{uuid.uuid4().hex}.jpg"
            quality = [cv2.IMWRITE_JPEG_QUALITY, self.settings.snapshot_jpeg_quality]
            ok, encoded = cv2.imencode(".jpg", frame, quality)
            if ok:
                try:
                    get_store().put(rel.as_posix(), encoded.tobytes())
                    image_rel = rel.as_posix()
                except Exception:
                    logger.exception("could not store snapshot image %s", rel)

        snapshot = Snapshot(
            session_id=self.status.session_id,
            streamer_id=self.streamer_id,
            f3_event_id=self._event.id if self._event else None,
            captured_at=now,
            stream_offset_seconds=round(time.monotonic() - self._started_mono, 2),
            confidence=detection.confidence,
            image_path=image_rel,
            ocr_status=OcrStatus.pending,
        )
        with Session(get_engine()) as db:
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
        self.status.snapshots_saved += 1
        self.status.last_snapshot_at = now

        from ghgtracker.api.serializers import snapshot_to_read  # avoid import cycle

        self.bus.publish(
            "snapshot.created",
            streamer_id=self.streamer_id,
            snapshot=snapshot_to_read(snapshot).model_dump(mode="json"),
        )
        if self.ocr is not None:
            assert snapshot.id is not None
            self.ocr.submit_frame(snapshot.id, frame, detection)

    def _flush_session(self, final: bool = False) -> None:
        if self.status.session_id is None:
            return
        with Session(get_engine()) as db:
            session = db.get(TrackingSession, self.status.session_id)
            if session is None:
                return
            session.frames_processed = self.status.frames_processed
            session.f3_frames = self.status.f3_frames
            session.f3_events = self.status.f3_events
            session.snapshots_saved = self.status.snapshots_saved
            if final:
                session.ended_at = utcnow()
                session.status = (
                    SessionStatus.error
                    if self.status.state == TrackerState.error
                    else SessionStatus.stopped
                )
                session.error = self.status.error
            db.add(session)
            db.commit()

    def _publish_status(self) -> None:
        self.bus.publish("tracker.status", status=self.status.model_dump(mode="json"))


class TrackerAlreadyRunning(RuntimeError):
    pass


class TrackerManager:
    def __init__(self, settings: Settings, bus: EventBus, ocr: OcrWorker | None = None) -> None:
        self.settings = settings
        self.bus = bus
        self.ocr = ocr
        self._trackers: dict[int, Tracker] = {}
        self._lock = threading.Lock()

    def start(self, streamer: Streamer, request: TrackerStartRequest) -> TrackerStatus:
        assert streamer.id is not None
        with self._lock:
            current = self._trackers.get(streamer.id)
            if current is not None and current.active:
                raise TrackerAlreadyRunning(f"tracker for {streamer.login} is already running")
            tracker = Tracker(streamer, request, self.settings, self.bus, self.ocr)
            self._trackers[streamer.id] = tracker
        tracker.start()
        return tracker.status

    def stop(self, streamer_id: int) -> TrackerStatus:
        tracker = self._trackers.get(streamer_id)
        if tracker is None:
            return TrackerStatus(streamer_id=streamer_id)
        tracker.stop()
        return tracker.status

    def get(self, streamer_id: int) -> Tracker | None:
        return self._trackers.get(streamer_id)

    def status(self, streamer_id: int) -> TrackerStatus:
        tracker = self._trackers.get(streamer_id)
        return tracker.status if tracker else TrackerStatus(streamer_id=streamer_id)

    def all_statuses(self) -> list[TrackerStatus]:
        return [t.status for t in self._trackers.values()]

    def forget(self, streamer_id: int) -> None:
        tracker = self._trackers.pop(streamer_id, None)
        if tracker is not None:
            tracker.stop()

    def shutdown(self) -> None:
        for tracker in list(self._trackers.values()):
            tracker.stop(timeout=5)

    @staticmethod
    def recover_interrupted_sessions() -> None:
        """Sessions still marked running belong to a previous server process that died."""
        with Session(get_engine()) as db:
            stale = db.exec(
                select(TrackingSession).where(TrackingSession.status == SessionStatus.running)
            ).all()
            for session in stale:
                session.status = SessionStatus.error
                session.ended_at = session.ended_at or utcnow()
                session.error = "interrupted (server restarted)"
                db.add(session)
            db.commit()
