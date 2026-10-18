"""Detector lab: run the F3 detector (and OCR) on an uploaded screenshot, for testing / tuning."""

import base64
from dataclasses import asdict
from typing import Annotated

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from ghgtracker.api.deps import Ocr
from ghgtracker.vision.extractor import CoordinateExtractor
from ghgtracker.vision.f3_detector import F3Detector, draw_overlay

router = APIRouter(prefix="/detect", tags=["detection"])
_detector = F3Detector()
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


def _run(data: bytes, extractor: CoordinateExtractor | None) -> dict:
    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "could not decode image")
    detection = _detector.detect(frame)
    reading = None
    if detection.detected and extractor is not None:
        result = extractor.extract(frame, detection)
        reading = asdict(result) if result else None
    overlay = draw_overlay(frame, detection)
    h, w = overlay.shape[:2]
    if w > 1280:
        overlay = cv2.resize(overlay, (1280, round(h * 1280 / w)), interpolation=cv2.INTER_AREA)
    _, buf = cv2.imencode(".jpg", overlay, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return {
        **detection.to_dict(),
        "width": w,
        "height": h,
        "ocr": reading,
        "overlay_jpeg": "data:image/jpeg;base64," + base64.b64encode(buf.tobytes()).decode(),
    }


@router.post("")
async def detect_image(file: Annotated[UploadFile, File()], ocr: Ocr, read: bool = True):
    """Detect the F3 screen; with `read` (default) also run OCR on it if OCR is enabled."""
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "image too large")

    def run() -> dict:
        return _run(data, ocr.extractor() if read else None)

    return await run_in_threadpool(run)
