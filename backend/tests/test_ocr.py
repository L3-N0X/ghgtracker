import re
import time
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image
from sqlmodel import Session

from ghgtracker.config import BACKEND_ROOT, get_settings
from ghgtracker.db import get_engine
from ghgtracker.events import EventBus
from ghgtracker.models import OcrStatus, Snapshot, TrackingSession
from ghgtracker.tracker.ocr_worker import OcrWorker
from ghgtracker.vision.extractor import ExtractionResult
from ghgtracker.vision.f3_detector import F3Detector

from .synthetic import f3_frame

DATASET = BACKEND_ROOT / "dataset" / "f3_open"
detector = F3Detector()


class FakeExtractor:
    def __init__(self, result: ExtractionResult | None) -> None:
        self.result = result
        self.calls = 0

    def extract(self, frame_bgr, detection):
        self.calls += 1
        return self.result


def make_snapshot(client, status: OcrStatus = OcrStatus.pending) -> int:
    streamer = client.post("/api/streamers", json={"login": f"ocr_{time.time_ns() % 10**9}"})
    with Session(get_engine()) as db:
        session = TrackingSession(
            streamer_id=streamer.json()["id"], source="test", capture_fps=1, save_interval_seconds=1
        )
        db.add(session)
        db.commit()
        snapshot = Snapshot(
            session_id=session.id, streamer_id=session.streamer_id, ocr_status=status
        )
        db.add(snapshot)
        db.commit()
        assert snapshot.id is not None
        return snapshot.id


def run_worker(monkeypatch, extractor: FakeExtractor) -> OcrWorker:
    worker = OcrWorker(get_settings(), EventBus())
    monkeypatch.setattr(worker, "_load", lambda: extractor)
    worker.start()
    return worker


def wait_for(snapshot_id: int, until=lambda s: s.ocr_status != OcrStatus.pending) -> Snapshot:
    deadline = time.time() + 5
    while time.time() < deadline:
        with Session(get_engine()) as db:
            snapshot = db.get(Snapshot, snapshot_id)
            assert snapshot is not None
            if until(snapshot):
                return snapshot
        time.sleep(0.02)
    raise AssertionError("OCR worker did not process the snapshot")


@pytest.mark.parametrize(
    ("result", "status"),
    [
        (ExtractionResult(x=1.5, y=64.0, z=-3.25, confirmed=True, dimension="nether"), "done"),
        (ExtractionResult(x=1.5, y=64.0, z=-3.25, confirmed=False), "unverified"),
        (ExtractionResult(raw_text="Facing: south"), "failed"),
    ],
)
def test_worker_stores_results(client, monkeypatch, result, status) -> None:
    snapshot_id = make_snapshot(client)
    worker = run_worker(monkeypatch, FakeExtractor(result))
    try:
        frame = f3_frame()
        assert worker.submit_frame(snapshot_id, frame, detector.detect(frame))
        snapshot = wait_for(snapshot_id)
    finally:
        worker.stop()
    assert snapshot.ocr_status == status
    assert (snapshot.x, snapshot.y, snapshot.z) == (result.x, result.y, result.z)
    if result.dimension:
        assert snapshot.dimension == "nether"


def test_worker_keeps_manual_values(client, monkeypatch) -> None:
    snapshot_id = make_snapshot(client, OcrStatus.manual)
    extractor = FakeExtractor(ExtractionResult(x=1.0, y=2.0, z=3.0, confirmed=True))
    worker = run_worker(monkeypatch, extractor)
    try:
        frame = f3_frame()
        worker.submit_frame(snapshot_id, frame, detector.detect(frame))
        deadline = time.time() + 5
        while extractor.calls == 0 and time.time() < deadline:
            time.sleep(0.02)
        time.sleep(0.1)
    finally:
        worker.stop()
    snapshot = wait_for(snapshot_id, until=lambda s: True)
    assert snapshot.ocr_status == OcrStatus.manual and snapshot.x is None


def test_ocr_off(client) -> None:
    assert client.get("/api/ocr").json()["state"] == "off"
    snapshot_id = make_snapshot(client)
    assert client.post(f"/api/snapshots/{snapshot_id}/ocr").status_code == 409
    assert client.post("/api/snapshots/ocr").status_code == 409


# ---------------------------------------------------------------- real OCR on the dataset


def truth(path: Path) -> tuple[float, float, float] | None:
    m = re.match(r"(-?[\d.]+)_(-?[\d.]+)_(-?[\d.]+)_rot", path.name)
    return (float(m[1]), float(m[2]), float(m[3])) if m else None


@pytest.fixture(scope="module")
def ocr_extractor():
    pytest.importorskip("rapidocr")
    from ghgtracker.vision.ocr import OcrExtractor, create_engine

    engine = create_engine("ppocr6-tiny", threads=2, model_dir=BACKEND_ROOT / "data" / "models")
    assert engine is not None
    return OcrExtractor(engine)


@pytest.mark.skipif(not DATASET.is_dir(), reason="dataset not available")
def test_reads_dataset(ocr_extractor) -> None:
    paths = sorted(DATASET.glob("*"))
    labeled = [p for p in paths if truth(p)]
    hidden = [p for p in paths if not truth(p)][:6]
    exact = 0
    for path in labeled + hidden:
        frame = cv2.cvtColor(np.asarray(Image.open(path).convert("RGB")), cv2.COLOR_RGB2BGR)
        result = ocr_extractor.extract(frame, detector.detect(frame))
        assert result is not None, path.name
        got, expected = (result.x, result.y, result.z), truth(path)
        if expected is None:
            assert result.x is None, f"hallucinated {got} on {path.name}"
            continue
        correct = result.x is not None and all(
            abs(a - b) < 5e-4 for a, b in zip(got, expected, strict=True)
        )
        exact += correct
        # A reading confirmed by the Block line must be right.
        assert correct or not result.confirmed, f"{path.name}: confirmed {got}"
    assert exact >= len(labeled) - 2, f"only {exact}/{len(labeled)} exact"
