"""OCR status and (re-)running OCR on stored snapshots."""

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlmodel import col, select

from ghgtracker.api.deps import DbSession, Ocr
from ghgtracker.api.serializers import snapshot_to_read
from ghgtracker.models import OcrStatus, Snapshot, SnapshotRead
from ghgtracker.tracker.ocr_worker import OcrInfo, OcrState

router = APIRouter(tags=["ocr"])


class QueuedResponse(BaseModel):
    queued: int


def _require_ocr(ocr) -> None:
    if ocr.info.state in (OcrState.off, OcrState.error):
        detail = "OCR is switched off (GHG_OCR_ENGINE=none)"
        if ocr.info.state == OcrState.error:
            detail = f"OCR engine failed to load: {ocr.info.error}"
        raise HTTPException(status.HTTP_409_CONFLICT, detail)


@router.get("/ocr", response_model=OcrInfo)
def ocr_info(ocr: Ocr):
    return ocr.info


@router.post("/snapshots/ocr", response_model=QueuedResponse)
def queue_snapshots(
    db: DbSession,
    ocr: Ocr,
    streamer_id: int | None = None,
    session_id: int | None = None,
    ocr_status: list[OcrStatus] = Query([OcrStatus.pending, OcrStatus.failed]),
):
    """Queue stored snapshots (by default the unread ones) for OCR in the background."""
    _require_ocr(ocr)
    filters = [col(Snapshot.ocr_status).in_(ocr_status), col(Snapshot.image_path).is_not(None)]
    if streamer_id is not None:
        filters.append(Snapshot.streamer_id == streamer_id)
    if session_id is not None:
        filters.append(Snapshot.session_id == session_id)
    ids = db.exec(select(Snapshot.id).where(*filters).order_by(col(Snapshot.captured_at))).all()
    return QueuedResponse(queued=ocr.submit_stored([i for i in ids if i is not None]))


@router.post("/snapshots/{snapshot_id}/ocr", response_model=SnapshotRead)
async def run_snapshot_ocr(snapshot_id: int, db: DbSession, ocr: Ocr):
    """Read a stored snapshot again right now (overwrites values, also manual ones)."""
    _require_ocr(ocr)
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "snapshot not found")
    if snapshot.image_path is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "no image stored for this snapshot")
    if snapshot.ocr_status == OcrStatus.manual:
        # An explicit re-run replaces hand-entered values.
        snapshot.ocr_status = OcrStatus.pending
        db.add(snapshot)
        db.commit()
    updated = await run_in_threadpool(ocr.process_now, snapshot_id)
    if updated is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "OCR could not read the stored image")
    return snapshot_to_read(updated)
