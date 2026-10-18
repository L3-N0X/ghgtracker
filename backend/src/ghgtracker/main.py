import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from ghgtracker.api import detection, ocr, snapshots, streamers, tracker, ws
from ghgtracker.config import get_settings
from ghgtracker.db import init_db
from ghgtracker.events import event_bus
from ghgtracker.tracker.manager import TrackerManager
from ghgtracker.tracker.ocr_worker import OcrWorker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.snapshot_dir.mkdir(parents=True, exist_ok=True)
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

    settings.snapshot_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media/snapshots", StaticFiles(directory=settings.snapshot_dir), name="snapshots")
    return app


app = create_app()
