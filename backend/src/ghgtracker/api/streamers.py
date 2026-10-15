import shutil

from fastapi import APIRouter, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, func
from sqlmodel import col, select

from ghgtracker.api.deps import DbSession, StreamerDep, Trackers
from ghgtracker.capture.frame_source import check_live
from ghgtracker.config import get_settings
from ghgtracker.models import (
    F3Event,
    Snapshot,
    Streamer,
    StreamerCreate,
    StreamerRead,
    StreamerUpdate,
    TrackingSession,
    TrackingSessionRead,
)

router = APIRouter(prefix="/streamers", tags=["streamers"])


def _with_stats(db: DbSession, streamers: list[Streamer]) -> list[StreamerRead]:
    ids = [s.id for s in streamers]
    stats = {
        row[0]: (row[1], row[2])
        for row in db.exec(
            select(Snapshot.streamer_id, func.count(), func.max(Snapshot.captured_at))
            .where(col(Snapshot.streamer_id).in_(ids))
            .group_by(Snapshot.streamer_id)
        ).all()
    }
    result = []
    for streamer in streamers:
        count, last = stats.get(streamer.id, (0, None))
        result.append(
            StreamerRead.model_validate(
                {**streamer.model_dump(), "snapshot_count": count, "last_snapshot_at": last}
            )
        )
    return result


@router.get("", response_model=list[StreamerRead])
def list_streamers(db: DbSession):
    streamers = list(db.exec(select(Streamer).order_by(Streamer.login)).all())
    return _with_stats(db, streamers)


@router.post("", response_model=StreamerRead, status_code=status.HTTP_201_CREATED)
def create_streamer(payload: StreamerCreate, db: DbSession):
    if db.exec(select(Streamer).where(Streamer.login == payload.login)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, f"streamer {payload.login} already exists")
    streamer = Streamer.model_validate(payload)
    db.add(streamer)
    db.commit()
    db.refresh(streamer)
    return _with_stats(db, [streamer])[0]


@router.get("/{streamer_id}", response_model=StreamerRead)
def get_streamer(streamer: StreamerDep, db: DbSession):
    return _with_stats(db, [streamer])[0]


@router.patch("/{streamer_id}", response_model=StreamerRead)
def update_streamer(payload: StreamerUpdate, streamer: StreamerDep, db: DbSession):
    streamer.sqlmodel_update(payload.model_dump(exclude_unset=True))
    db.add(streamer)
    db.commit()
    db.refresh(streamer)
    return _with_stats(db, [streamer])[0]


@router.delete("/{streamer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_streamer(streamer: StreamerDep, db: DbSession, trackers: Trackers):
    await run_in_threadpool(trackers.forget, streamer.id)
    for model in (Snapshot, F3Event, TrackingSession):
        db.exec(delete(model).where(model.streamer_id == streamer.id))
    db.delete(streamer)
    db.commit()
    shutil.rmtree(get_settings().snapshot_dir / streamer.login, ignore_errors=True)


@router.get("/{streamer_id}/live")
async def streamer_live(streamer: StreamerDep):
    """Ask streamlink whether the channel currently has a playable stream (takes ~1-3 s)."""
    return {"login": streamer.login, "live": await run_in_threadpool(check_live, streamer.login)}


@router.get("/{streamer_id}/sessions", response_model=list[TrackingSessionRead])
def list_sessions(streamer: StreamerDep, db: DbSession, limit: int = 50):
    return db.exec(
        select(TrackingSession)
        .where(TrackingSession.streamer_id == streamer.id)
        .order_by(col(TrackingSession.started_at).desc())
        .limit(limit)
    ).all()
