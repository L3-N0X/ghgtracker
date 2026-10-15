from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlmodel import Session

from ghgtracker.db import get_session
from ghgtracker.models import Streamer
from ghgtracker.tracker.manager import TrackerManager

DbSession = Annotated[Session, Depends(get_session)]


def get_tracker_manager(request: Request) -> TrackerManager:
    return request.app.state.tracker_manager


Trackers = Annotated[TrackerManager, Depends(get_tracker_manager)]


def get_streamer_or_404(streamer_id: int, db: DbSession) -> Streamer:
    streamer = db.get(Streamer, streamer_id)
    if streamer is None:
        raise HTTPException(status_code=404, detail="streamer not found")
    return streamer


StreamerDep = Annotated[Streamer, Depends(get_streamer_or_404)]
