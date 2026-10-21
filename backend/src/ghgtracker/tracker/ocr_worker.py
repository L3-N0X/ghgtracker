"""OCR worker: one background thread that reads the values of stored snapshots.

OCR takes around a second per snapshot on a small CPU, far longer than the capture loop may
block, so trackers only store the snapshot ("pending") and hand the frame over. All trackers
share this one worker, which keeps the OCR load at `ocr_threads` cores no matter how many
streamers are tracked. Live frames go first; stored snapshots (re-runs, snapshots taken while
OCR was off) are read from their image files when nothing live is waiting.
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
from dataclasses import dataclass, field
from enum import StrEnum

import cv2
import numpy as np
from pydantic import BaseModel
from sqlmodel import Session

from ghgtracker.config import Settings
from ghgtracker.db import get_engine
from ghgtracker.events import EventBus
from ghgtracker.models import Dimension, OcrStatus, Snapshot
from ghgtracker.storage import get_store
from ghgtracker.vision.extractor import CoordinateExtractor, ExtractionResult
from ghgtracker.vision.f3_detector import F3Detection, F3Detector

logger = logging.getLogger(__name__)

LIVE, STORED = 0, 1  # job priorities


class OcrState(StrEnum):
    off = "off"
    loading = "loading"
    ready = "ready"
    error = "error"


class OcrInfo(BaseModel):
    engine: str
    state: OcrState
    queued: int = 0
    processed: int = 0
    skipped: int = 0  # live snapshots dropped because the worker was behind
    last_ms: float | None = None
    error: str | None = None


@dataclass(order=True)
class _Job:
    priority: int
    seq: int
    snapshot_id: int = field(compare=False)
    frame: np.ndarray | None = field(default=None, compare=False)
    detection: F3Detection | None = field(default=None, compare=False)


class OcrWorker:
    def __init__(self, settings: Settings, bus: EventBus) -> None:
        self.settings = settings
        self.bus = bus
        self.info = OcrInfo(engine=settings.ocr_engine, state=OcrState.loading)
        self.detector = F3Detector()
        self._extractor: CoordinateExtractor | None = None
        self._ready = threading.Event()
        self._jobs: queue.PriorityQueue[_Job] = queue.PriorityQueue()
        self._seq = itertools.count()
        self._live_waiting = 0
        self._count_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ control

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="ocr-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._jobs.put(_Job(-1, -1, 0))  # wake the thread up
        if self._thread is not None:
            self._thread.join(timeout)

    def extractor(self, timeout: float = 120.0) -> CoordinateExtractor | None:
        """The loaded extractor (waits while the models load), None if OCR is unavailable."""
        self._ready.wait(timeout)
        return self._extractor

    # ------------------------------------------------------------------ jobs

    def submit_frame(self, snapshot_id: int, frame: np.ndarray, detection: F3Detection) -> bool:
        """Queue a freshly captured snapshot. False if the worker is too far behind."""
        if self.info.state in (OcrState.off, OcrState.error):
            return False
        with self._count_lock:
            if self._live_waiting >= self.settings.ocr_queue_size:
                self.info.skipped += 1
                return False
            self._live_waiting += 1
        self._jobs.put(_Job(LIVE, next(self._seq), snapshot_id, frame, detection))
        self.info.queued = self._jobs.qsize()
        return True

    def submit_stored(self, snapshot_ids: list[int]) -> int:
        """Queue stored snapshots; their images are read from disk when it is their turn."""
        if self.info.state in (OcrState.off, OcrState.error):
            return 0
        for snapshot_id in snapshot_ids:
            self._jobs.put(_Job(STORED, next(self._seq), snapshot_id))
        self.info.queued = self._jobs.qsize()
        return len(snapshot_ids)

    def process_now(self, snapshot_id: int) -> Snapshot | None:
        """Run OCR on a stored snapshot right away, in the calling thread."""
        return self._process(_Job(STORED, -1, snapshot_id))

    # ------------------------------------------------------------------ worker

    def _run(self) -> None:
        try:
            self._extractor = self._load()
            self.info.state = OcrState.ready if self._extractor else OcrState.off
        except Exception as exc:  # noqa: BLE001 - tracking works without OCR
            logger.exception("could not load OCR engine %s", self.settings.ocr_engine)
            self.info.state, self.info.error = OcrState.error, str(exc)
        finally:
            self._ready.set()
        if self._extractor is None:
            return
        logger.info("OCR engine %s ready", self.settings.ocr_engine)

        while not self._stop.is_set():
            job = self._jobs.get()
            if self._stop.is_set():
                break
            if job.priority == LIVE:
                with self._count_lock:
                    self._live_waiting -= 1
            try:
                self._process(job)
            except Exception:  # noqa: BLE001 - one bad snapshot must not stop the worker
                logger.exception("OCR of snapshot %s failed", job.snapshot_id)
            self.info.queued = self._jobs.qsize()

    def _load(self) -> CoordinateExtractor | None:
        from ghgtracker.vision.ocr import OcrExtractor, create_engine

        engine = create_engine(
            self.settings.ocr_engine,
            threads=self.settings.ocr_threads,
            model_dir=self.settings.model_dir,
            ollama_url=self.settings.ocr_ollama_url,
            ollama_model=self.settings.ocr_ollama_model,
        )
        if engine is None:
            return None
        extractor = OcrExtractor(engine)
        # Warm up (first run allocates buffers) so the first real snapshot is not slow.
        blank = np.zeros((64, 256, 3), np.uint8)
        engine.read([blank])
        return extractor

    def _process(self, job: _Job) -> Snapshot | None:
        extractor = self.extractor()
        if extractor is None:
            return None
        frame, detection = job.frame, job.detection
        if frame is None:
            with Session(get_engine()) as db:
                snapshot = db.get(Snapshot, job.snapshot_id)
                image_path = snapshot.image_path if snapshot else None
            if image_path is None:
                return None
            try:
                data = get_store().get(image_path)
            except Exception:
                logger.exception("could not load snapshot image %s", image_path)
                return None
            if data is None:
                return None
            frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if frame is None:
                return None
        if detection is None:
            detection = self.detector.detect(frame)

        result = extractor.extract(frame, detection) if detection.detected else None
        if result is not None:
            self.info.processed += 1
            self.info.last_ms = result.elapsed_ms
        return self._store(job.snapshot_id, result)

    def _store(self, snapshot_id: int, result: ExtractionResult | None) -> Snapshot | None:
        with Session(get_engine()) as db:
            snapshot = db.get(Snapshot, snapshot_id)
            # Deleted meanwhile, or corrected by hand: never overwrite manual values.
            if snapshot is None or snapshot.ocr_status == OcrStatus.manual:
                return snapshot
            apply_result(snapshot, result)
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)

        from ghgtracker.api.serializers import snapshot_to_read  # avoid import cycle

        self.bus.publish(
            "snapshot.updated",
            streamer_id=snapshot.streamer_id,
            snapshot=snapshot_to_read(snapshot).model_dump(mode="json"),
        )
        return snapshot


def apply_result(snapshot: Snapshot, result: ExtractionResult | None) -> None:
    """Copy an OCR result onto a snapshot and set its status."""
    if result is None or result.x is None:
        snapshot.ocr_status = OcrStatus.failed
    elif result.confirmed:
        snapshot.ocr_status = OcrStatus.done
    else:
        snapshot.ocr_status = OcrStatus.unverified
    if result is None:
        snapshot.raw_text = None
        return
    snapshot.x, snapshot.y, snapshot.z = result.x, result.y, result.z
    snapshot.biome = result.biome
    snapshot.dimension = Dimension(result.dimension) if result.dimension else None
    snapshot.facing = result.facing
    snapshot.raw_text = result.raw_text
