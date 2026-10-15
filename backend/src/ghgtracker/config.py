from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration. Every field can be overridden via `GHG_<FIELD>` env vars or `.env`."""

    model_config = SettingsConfigDict(env_prefix="GHG_", env_file=".env", extra="ignore")

    data_dir: Path = BACKEND_ROOT / "data"
    database_url: str | None = None
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

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

    @property
    def snapshot_dir(self) -> Path:
        return self.data_dir / "snapshots"

    @property
    def resolved_database_url(self) -> str:
        return self.database_url or f"sqlite:///{self.data_dir / 'ghgtracker.db'}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
