from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import col, select

from ghgtracker.api.deps import DbSession
from ghgtracker.api.serializers import f3_event_to_read, snapshot_to_read
from ghgtracker.config import get_settings
from ghgtracker.models import (
    F3Event,
    F3EventRead,
    OcrStatus,
    Page,
    Snapshot,
    SnapshotRead,
    SnapshotUpdate,
)

router = APIRouter(tags=["snapshots"])


@router.get("/snapshots", response_model=Page[SnapshotRead])
def list_snapshots(
    db: DbSession,
    streamer_id: int | None = None,
    session_id: int | None = None,
    ocr_status: OcrStatus | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    filters = []
    if streamer_id is not None:
        filters.append(Snapshot.streamer_id == streamer_id)
    if session_id is not None:
        filters.append(Snapshot.session_id == session_id)
    if ocr_status is not None:
        filters.append(Snapshot.ocr_status == ocr_status)
    if since is not None:
        filters.append(Snapshot.captured_at >= since)
    if until is not None:
        filters.append(Snapshot.captured_at <= until)

    total = db.exec(select(func.count()).select_from(Snapshot).where(*filters)).one()
    order_by = col(Snapshot.captured_at)
    rows = db.exec(
        select(Snapshot)
        .where(*filters)
        .order_by(order_by.desc() if order == "desc" else order_by.asc())
        .offset(offset)
        .limit(limit)
    ).all()
    return Page[SnapshotRead](
        items=[snapshot_to_read(s) for s in rows], total=total, limit=limit, offset=offset
    )


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotRead)
def get_snapshot(snapshot_id: int, db: DbSession):
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "snapshot not found")
    return snapshot_to_read(snapshot)


@router.patch("/snapshots/{snapshot_id}", response_model=SnapshotRead)
def update_snapshot(snapshot_id: int, payload: SnapshotUpdate, db: DbSession):
    """Manually set / correct the values read from the F3 screen."""
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "snapshot not found")
    snapshot.sqlmodel_update(payload.model_dump(exclude_unset=True))
    snapshot.ocr_status = OcrStatus.manual
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot_to_read(snapshot)


@router.delete("/snapshots/{snapshot_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_snapshot(snapshot_id: int, db: DbSession):
    snapshot = db.get(Snapshot, snapshot_id)
    if snapshot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "snapshot not found")
    if snapshot.image_path:
        (get_settings().snapshot_dir / snapshot.image_path).unlink(missing_ok=True)
    db.delete(snapshot)
    db.commit()


@router.get("/f3-events", response_model=Page[F3EventRead])
def list_f3_events(
    db: DbSession,
    streamer_id: int | None = None,
    session_id: int | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    filters = []
    if streamer_id is not None:
        filters.append(F3Event.streamer_id == streamer_id)
    if session_id is not None:
        filters.append(F3Event.session_id == session_id)
    total = db.exec(select(func.count()).select_from(F3Event).where(*filters)).one()
    rows = db.exec(
        select(F3Event)
        .where(*filters)
        .order_by(col(F3Event.opened_at).desc())
        .offset(offset)
        .limit(limit)
    ).all()
    return Page[F3EventRead](
        items=[f3_event_to_read(e) for e in rows], total=total, limit=limit, offset=offset
    )
