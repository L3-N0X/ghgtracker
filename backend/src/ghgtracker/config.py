from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration. Every field can be overridden via `GHG_<FIELD>` env vars or `.env`."""

    model_config = SettingsConfigDict(env_prefix="GHG_", env_file=".env", extra="ignore")

    data_dir: Path = BACKEND_ROOT / "data"
    database_url: str | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Built frontend (Vite `dist`). When this directory exists the backend serves it at `/`,
    # which is how the Docker image runs. Unset in development (Vite serves the UI).
    frontend_dir: Path | None = None
    # Address uvicorn binds to when started via the `ghgtracker` command.
    host: str = "127.0.0.1"
    port: int = 8000

    # Where snapshot images are stored: "local" = <data_dir>/snapshots, "s3" = S3 compatible
    # bucket (RustFS, MinIO, AWS, ...). The backend streams images to the browser itself, so the
    # bucket never has to be public.
    storage_backend: Literal["local", "s3"] = "local"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "ghgtracker"
    s3_region: str = "us-east-1"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_path_style: bool = True

    # Capture pipeline
    ffmpeg_path: str = "ffmpeg"
    stream_quality: str = "best"
    capture_width: int = 1920
    capture_height: int = 1080
    capture_fps: float = 15.0

    # Tracking behaviour
    save_interval_seconds: float = 5.0
    save_images: bool = True
    snapshot_jpeg_quality: int = 90
    # Consecutive negative frames before an open F3 screen counts as closed (debounces flicker).
    f3_close_grace_frames: int = 3

    # OCR of stored snapshots (XYZ, biome, dimension, facing), see vision/ocr.py.
    # none | ppocr6-tiny (fast, small VPS) | ppocr6-small | ppocr5-mobile | ollama (vision LLM)
    ocr_engine: Literal["none", "ppocr6-tiny", "ppocr6-small", "ppocr5-mobile", "ollama"] = (
        "ppocr6-tiny"
    )
    # CPU threads for one OCR run (0 = all cores). Keep it below the VPS core count so frame
    # capture and F3 detection keep up.
    ocr_threads: int = 2
    # Live snapshots waiting for OCR; more are skipped (they stay "pending" and can be re-run).
    ocr_queue_size: int = 8
    ocr_ollama_url: str = "http://127.0.0.1:11434"
    ocr_ollama_model: str = "qwen3-vl:2b-instruct"

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def model_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'ghgtracker.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
