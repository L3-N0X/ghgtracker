import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ghgtracker.api import detection, ocr, snapshots, streamers, tracker, ws
from ghgtracker.config import get_settings
from ghgtracker.db import init_db
from ghgtracker.events import event_bus
from ghgtracker.storage import get_store
from ghgtracker.tracker.manager import TrackerManager
from ghgtracker.tracker.ocr_worker import OcrWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await run_in_threadpool(get_store().prepare)
    init_db()
    TrackerManager.recover_interrupted_sessions()
    event_bus.bind(asyncio.get_running_loop())
    app.state.ocr = OcrWorker(settings, event_bus)
    app.state.ocr.start()
    app.state.tracker_manager = TrackerManager(settings, event_bus, app.state.ocr)
    yield
    await run_in_threadpool(app.state.tracker_manager.shutdown)
    await run_in_threadpool(app.state.ocr.stop)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="GHG Tracker", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api")

    @api.get("/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    for module in (streamers, tracker, snapshots, ocr, detection, ws):
        api.include_router(module.router)
    app.include_router(api)

    @app.get("/media/snapshots/{key:path}", include_in_schema=False)
    def snapshot_image(key: str):
        """Snapshot JPEGs, read from whichever storage backend is configured."""
        try:
            data = get_store().get(key)
        except ValueError:
            data = None
        if data is None:
            raise HTTPException(404, "image not found")
        # File names are random uuids and never rewritten, so browsers may cache them for good.
        return Response(
            data,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )

    # Last, so it only answers what the API does not. The UI uses hash routes, so serving
    # index.html for "/" is all it needs.
    if settings.frontend_dir is not None and settings.frontend_dir.is_dir():
        app.mount("/", StaticFiles(directory=settings.frontend_dir, html=True), name="frontend")
    return app


app = create_app()
