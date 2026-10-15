from fastapi import APIRouter, HTTPException, Response, status
from fastapi.concurrency import run_in_threadpool

from ghgtracker.api.deps import StreamerDep, Trackers
from ghgtracker.tracker.manager import TrackerAlreadyRunning, TrackerStartRequest, TrackerStatus

router = APIRouter(tags=["tracker"])


@router.get("/trackers", response_model=list[TrackerStatus])
def list_trackers(trackers: Trackers):
    return trackers.all_statuses()


@router.get("/streamers/{streamer_id}/tracker", response_model=TrackerStatus)
def tracker_status(streamer: StreamerDep, trackers: Trackers):
    return trackers.status(streamer.id)


@router.post("/streamers/{streamer_id}/tracker/start", response_model=TrackerStatus)
async def start_tracker(
    streamer: StreamerDep, trackers: Trackers, payload: TrackerStartRequest | None = None
):
    request = payload or TrackerStartRequest()
    if request.capture_fps is not None and not 0.5 <= request.capture_fps <= 60:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "capture_fps must be 0.5-60")
    if request.save_interval_seconds is not None and request.save_interval_seconds < 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "save interval must be >= 0")
    try:
        return await run_in_threadpool(trackers.start, streamer, request)
    except TrackerAlreadyRunning as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/streamers/{streamer_id}/tracker/stop", response_model=TrackerStatus)
async def stop_tracker(streamer: StreamerDep, trackers: Trackers):
    return await run_in_threadpool(trackers.stop, streamer.id)


@router.get(
    "/streamers/{streamer_id}/tracker/frame.jpg",
    responses={200: {"content": {"image/jpeg": {}}}, 204: {"description": "no frame yet"}},
)
async def tracker_frame(streamer: StreamerDep, trackers: Trackers, overlay: bool = True):
    """Latest captured frame, optionally with the F3 detector's line boxes drawn on top."""
    tracker = trackers.get(streamer.id)
    jpeg = await run_in_threadpool(tracker.preview_jpeg, overlay) if tracker else None
    if jpeg is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})
