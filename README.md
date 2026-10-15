# GHG Tracker

Foundation for a Twitch stream → Minecraft coordinate tracker. It watches a streamer's live
stream, detects whenever the F3 debug screen is open (even briefly), and stores snapshots that a
later OCR stage turns into coordinates and biomes. A map comes after that.

```
backend/    Python 3.13 · uv · FastAPI · SQLModel (SQLite) · OpenCV · streamlink + ffmpeg
frontend/   Svelte 5 · Vite · TypeScript · Tailwind CSS v4 · shadcn-svelte
```

## Requirements

- `uv`, Node 22+ with `pnpm`
- `ffmpeg` on `PATH` (decodes the stream). `streamlink` is installed as a Python dependency.

## Run

```bash
# backend → http://127.0.0.1:8000  (API docs at /docs)
cd backend
uv sync
uv run uvicorn ghgtracker.main:app --reload

# frontend → http://localhost:5173  (proxies /api and /media to the backend)
cd frontend
pnpm install
pnpm dev
```

Open the frontend, add a streamer (Twitch login or channel URL), then start the tracker. For
testing without a live stream, put a Twitch VOD URL or a local video path into the tracker's
**Source** field. The **Detector lab** page runs the detector on an uploaded screenshot.

## How it works

```
streamlink ─▶ ffmpeg (fps + scale) ─▶ F3 detector (every frame, ~10 ms) ─▶ F3 event open/close
                                                     │
                                                     └─▶ snapshot (rate limited) ─▶ JPEG + DB row
                                                                                     └─▶ OCR (todo)
```

- **F3 detection** (`backend/src/ghgtracker/vision/f3_detector.py`): finds light-gray, thin-stroke
  text on darkened line backgrounds, groups it into text lines, and checks for a column of lines
  flush against the left or right screen edge, starting at the top, on a fixed line pitch. Either
  side can be the main column, since the layout is customizable from 1.21.9 on. No OCR runs in
  this step.
- **F3 events**: each continuous period F3 is visible. After `GHG_F3_CLOSE_GRACE_FRAMES` frames
  in a row without F3, the event counts as closed, so single dropped frames don't split one opening
  in two.
- **Snapshots**: while F3 is open, at most one snapshot per `save_interval_seconds` (set per run in
  the UI, default 5 s). The frame is stored under `backend/data/snapshots/`. `x/y/z`, `biome`,
  `dimension` and `facing` stay empty (`ocr_status = pending`) until an OCR extractor is
  plugged into `vision/extractor.py`. You can also enter or correct values by hand.
- **Live updates**: the frontend listens on the WebSocket `/api/ws` for `tracker.status`,
  `f3.opened`, `f3.closed` and `snapshot.created` events.

## Data model

`Streamer` → `TrackingSession` (one per tracker start) → `F3Event` and `Snapshot`
(`captured_at`, `stream_offset_seconds`, `confidence`, `image_path`, `x/y/z`, `biome`,
`dimension`, `facing`, `ocr_status`, `raw_text`).

SQLite lives at `backend/data/ghgtracker.db`. Tables are created on startup, and there are no
migrations yet.

## Configuration

Set these as environment variables (or in `backend/.env`):

| Variable | Default | |
|---|---|---|
| `GHG_DATA_DIR` | `backend/data` | DB + snapshot images |
| `GHG_DATABASE_URL` | SQLite in data dir | any SQLAlchemy URL |
| `GHG_CAPTURE_FPS` | `15` | default analysis frame rate |
| `GHG_CAPTURE_WIDTH` / `_HEIGHT` | `1920` / `1080` | decode resolution |
| `GHG_STREAM_QUALITY` | `best` | streamlink quality, comma separated fallbacks |
| `GHG_SAVE_INTERVAL_SECONDS` | `5` | default snapshot interval |
| `GHG_F3_CLOSE_GRACE_FRAMES` | `3` | negative frames before an F3 event closes |
| `GHG_FFMPEG_PATH` | `ffmpeg` | |

## Tests

```bash
cd backend && uv run pytest     # detector (synthetic frames) + API + tracker end-to-end on a video
cd frontend && pnpm check
```
