"""Database tables and API schemas.

Hierarchy: Streamer -> TrackingSession -> (F3Event, Snapshot).
A Snapshot is one stored frame taken while the F3 debug screen was open. Coordinate / biome
fields stay empty until the OCR stage (not implemented yet) fills them in.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, field_validator
from sqlmodel import Field, SQLModel


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_utc(value: datetime) -> datetime:
    # SQLite drops tzinfo; everything we store is UTC.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


UTCDatetime = Annotated[datetime, AfterValidator(_as_utc)]


class SessionStatus(StrEnum):
    running = "running"
    stopped = "stopped"
    error = "error"


class OcrStatus(StrEnum):
    pending = "pending"  # waiting for the (future) OCR stage
    done = "done"
    failed = "failed"
    manual = "manual"  # values entered / corrected by hand


class Dimension(StrEnum):
    overworld = "overworld"
    nether = "nether"
    end = "end"


# --------------------------------------------------------------------------- streamers


class StreamerBase(SQLModel):
    display_name: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=2000)


class Streamer(StreamerBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    login: str = Field(index=True, unique=True, max_length=32)
    created_at: datetime = Field(default_factory=utcnow)


class StreamerCreate(StreamerBase):
    login: str = Field(min_length=3, max_length=64)

    @field_validator("login")
    @classmethod
    def normalize_login(cls, value: str) -> str:
        login = value.strip().lower()
        # Accept pasted channel URLs like https://www.twitch.tv/somebody
        if "twitch.tv/" in login:
            login = login.split("twitch.tv/", 1)[1].split("/")[0].split("?")[0]
        login = login.lstrip("@")
        if not login.replace("_", "").isalnum() or not 3 <= len(login) <= 25:
            raise ValueError("not a valid Twitch login")
        return login


class StreamerUpdate(StreamerBase):
    pass


class StreamerRead(StreamerBase):
    id: int
    login: str
    created_at: UTCDatetime
    snapshot_count: int = 0
    last_snapshot_at: UTCDatetime | None = None


# --------------------------------------------------------------------------- sessions


class TrackingSession(SQLModel, table=True):
    __tablename__ = "tracking_session"

    id: int | None = Field(default=None, primary_key=True)
    streamer_id: int = Field(foreign_key="streamer.id", index=True)
    started_at: datetime = Field(default_factory=utcnow)
    ended_at: datetime | None = None
    status: SessionStatus = SessionStatus.running
    source: str
    capture_fps: float
    save_interval_seconds: float
    frames_processed: int = 0
    f3_frames: int = 0
    f3_events: int = 0
    snapshots_saved: int = 0
    error: str | None = None


class TrackingSessionRead(SQLModel):
    id: int
    streamer_id: int
    started_at: UTCDatetime
    ended_at: UTCDatetime | None
    status: SessionStatus
    source: str
    capture_fps: float
    save_interval_seconds: float
    frames_processed: int
    f3_frames: int
    f3_events: int
    snapshots_saved: int
    error: str | None


# --------------------------------------------------------------------------- F3 events


class F3Event(SQLModel, table=True):
    """One continuous period in which the F3 screen was visible (however short)."""

    __tablename__ = "f3_event"

    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="tracking_session.id", index=True)
    streamer_id: int = Field(foreign_key="streamer.id", index=True)
    opened_at: datetime
    closed_at: datetime | None = None
    frame_count: int = 0
    peak_confidence: float = 0.0


class F3EventRead(SQLModel):
    id: int
    session_id: int
    streamer_id: int
    opened_at: UTCDatetime
    closed_at: UTCDatetime | None
    frame_count: int
    peak_confidence: float
    duration_seconds: float | None = None


# --------------------------------------------------------------------------- snapshots


class SnapshotData(SQLModel):
    """Values read from the F3 screen. All optional until OCR exists."""

    x: float | None = None
    y: float | None = None
    z: float | None = None
    biome: str | None = Field(default=None, max_length=128)
    dimension: Dimension | None = None
    facing: str | None = Field(default=None, max_length=32)


class Snapshot(SnapshotData, table=True):
    id: int | None = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="tracking_session.id", index=True)
    streamer_id: int = Field(foreign_key="streamer.id", index=True)
    f3_event_id: int | None = Field(default=None, foreign_key="f3_event.id", index=True)
    captured_at: datetime = Field(default_factory=utcnow, index=True)
    # Seconds since the tracking session started, handy for lining up with VODs.
    stream_offset_seconds: float = 0.0
    confidence: float = 0.0
    image_path: str | None = None
    ocr_status: OcrStatus = OcrStatus.pending
    raw_text: str | None = None


class SnapshotUpdate(SnapshotData):
    pass


class SnapshotRead(SnapshotData):
    id: int
    session_id: int
    streamer_id: int
    f3_event_id: int | None
    captured_at: UTCDatetime
    stream_offset_seconds: float
    confidence: float
    image_url: str | None = None
    ocr_status: OcrStatus
    raw_text: str | None


class Page[T](BaseModel):
    items: list[T]
    total: int
    limit: int
    offset: int
