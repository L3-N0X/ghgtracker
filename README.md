# GHG Tracker

Foundation for a Twitch stream → Minecraft coordinate tracker. It watches a streamer's live
stream, detects whenever the F3 debug screen is open (even briefly), and stores snapshots that a
later OCR stage turns into coordinates and biomes, and draws the path on a travel map.

```
backend/    Python 3.13 · uv · FastAPI · SQLModel (SQLite) · OpenCV · streamlink + ffmpeg
frontend/   Svelte 5 · Vite · TypeScript · Tailwind CSS v4 · shadcn-svelte
```

## Requirements

- `uv`, Node 22+ with `pnpm`
- `ffmpeg` on `PATH` (decodes the stream). `streamlink` is installed as a Python dependency.

## Deploy with Docker

The image contains the backend, the built UI and ffmpeg, and the compose file adds
[RustFS](https://rustfs.com) (S3) for the snapshot images:

```bash
curl -O https://raw.githubusercontent.com/L3-N0X/ghgtracker/main/docker-compose.yml
curl -o .env https://raw.githubusercontent.com/L3-N0X/ghgtracker/main/.env.example
# set RUSTFS_ACCESS_KEY and RUSTFS_SECRET_KEY in .env (e.g. `openssl rand -hex 16`)
docker compose up -d       # → http://localhost:8000
```

- `ghcr.io/l3-n0x/ghgtracker` has tags `latest`, `1.2.3` / `1.2` / `1` (releases) and `edge`
  (main branch), for `linux/amd64` and `linux/arm64`. Pin one with `GHG_VERSION` in `.env`.
- The database and the downloaded OCR models live in the `ghgtracker-data` volume, the images in
  `rustfs-data`. The bucket is created on first start. Browse it in the RustFS console at
  `http://127.0.0.1:9001`.
- The UI has no login. Put a reverse proxy with HTTPS and authentication in front of port 8000
  before exposing it.
- To build the image yourself:
  `docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build`.
- Without RustFS, delete the `GHG_STORAGE_BACKEND` / `GHG_S3_*` variables and the `rustfs`
  service. The images then go to the `/data` volume.

CI (`.github/workflows/ci.yml`) runs ruff, pytest, `pnpm check` and a test build of the image on
every push and PR. To publish a release, push a tag:

```bash
git tag v1.0.0 && git push origin v1.0.0   # builds + pushes the image, creates the GitHub release
```

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
**Source** field. The **Detector lab** page runs the detector and OCR on an uploaded screenshot.

## How it works

```
streamlink ─▶ ffmpeg (fps + scale) ─▶ F3 detector (every frame, ~10 ms) ─▶ F3 event open/close
                                                     │
                                                     └─▶ snapshot (rate limited) ─▶ JPEG + DB row
                                                                                     └─▶ OCR worker (background)
```

- **F3 detection** (`backend/src/ghgtracker/vision/f3_detector.py`): models how the game draws
  the debug screen. Lines sit on a strict lattice of 9 GUI px per line, starting 2 GUI px from the
  top, with text in rows 0–6, descenders in row 7 and an always empty row 8. They are flush
  against the left and right screen edge.
  1. A colour-independent stroke mask is built from thin bright ridges, so BetterF3's coloured
     text works too.
  2. The line pitch comes from an autocorrelation of both edge strips.
  3. The lattice (pitch + top offset) is fitted jointly to both columns.
  4. Each column is verified: wide text lines, one shared start position, and the font's vertical
     signature.
  5. A single column alone (e.g. the other one hidden behind a facecam) must also be drawn in a
     pixel font: its glyph edges have to sit on the GUI pixel grid. Anti-aliased chat overlays
     fail that check.

  The detector works at native resolution and takes ~15 ms per 1080p frame. No OCR runs in this
  step.
- **F3 events**: each continuous period F3 is visible. After `GHG_F3_CLOSE_GRACE_FRAMES` frames
  in a row without F3, the event counts as closed, so single dropped frames don't split one opening
  in two.
- **Snapshots**: while F3 is open, at most one snapshot per `save_interval_seconds` (set per run in
  the UI, default 5 s). The frame is stored (see `GHG_STORAGE_BACKEND`) with
  `ocr_status = pending`. You can also enter or correct values by hand.
- **OCR** (`vision/ocr.py`, `vision/f3_text.py`, `tracker/ocr_worker.py`): one background worker,
  shared by all trackers, reads `x/y/z`, `biome`, `dimension` and `facing` from each snapshot.
  This way the capture loop never waits for it. Only the F3 columns found by the detector are
  OCR'd. The parser knows the F3 format: XYZ has decimals, X/Z have 3 and Y has 5, and the
  `Block:` line holds floor(XYZ). That lets it repair typical misreads, like ` / ` read as `7`.
  Resulting status:
  - `done`: XYZ confirmed by the `Block:` line. Confirmed readings were never wrong in testing.
  - `unverified`: XYZ was read, but the `Block:` line could not confirm it.
  - `failed`: no XYZ line readable, e.g. hidden behind a facecam.

  Values you entered by hand are never overwritten by the worker. **Read unread** in the
  coordinate log queues `pending`/`failed` snapshots, e.g. ones taken while OCR was off.
  **Read again** in the snapshot dialog re-reads a single snapshot.
- **Travel map** (`frontend/src/lib/map/travel.ts`, `TravelMap*.svelte`): every reading with X/Z,
  per dimension, joined in time order. The line style shows the time between two readings, not
  the distance: solid blue up to 90 s (really travelled, even when it's an elytra flight), dashed
  amber up to 10 min (pause), dotted magenta beyond that, across a new session, or when the player
  was in another dimension in between. The timeline below the map shortens long gaps so they
  don't squash everything else; drag on it to show only part of the path.
- **Live updates**: the frontend listens on the WebSocket `/api/ws` for `tracker.status`,
  `f3.opened`, `f3.closed`, `snapshot.created` and `snapshot.updated` (OCR finished) events.

## Data model

`Streamer` → `TrackingSession` (one per tracker start) → `F3Event` and `Snapshot`
(`captured_at`, `stream_offset_seconds`, `confidence`, `image_path`, `x/y/z`, `biome`,
`dimension`, `facing`, `ocr_status`, `raw_text`).

SQLite lives at `backend/data/ghgtracker.db`. `image_path` is a storage key
(`<login>/<session id>/<uuid>.jpg`) and the same for both storage backends, so moving from
`local` to `s3` only means copying `data/snapshots/*` into the bucket (e.g. with `rclone` or
`mc mirror`). The backend serves the images itself at `/media/snapshots/<key>`; the bucket does
not have to be reachable from the browser. Tables are created on startup, and there are no
migrations yet.

## Configuration

Set these as environment variables (or in `backend/.env`):

| Variable | Default | |
|---|---|---|
| `GHG_DATA_DIR` | `backend/data` | DB, OCR models and (with `local` storage) snapshot images |
| `GHG_DATABASE_URL` | SQLite in data dir | any SQLAlchemy URL |
| `GHG_STORAGE_BACKEND` | `local` | `local` (`<data dir>/snapshots`) or `s3` |
| `GHG_S3_ENDPOINT_URL` | – | e.g. `http://rustfs:9000`; empty = AWS |
| `GHG_S3_BUCKET` | `ghgtracker` | created on startup if missing |
| `GHG_S3_ACCESS_KEY` / `_SECRET_KEY` | – | |
| `GHG_S3_REGION` | `us-east-1` | |
| `GHG_S3_PATH_STYLE` | `true` | `bucket` in the path, needed for RustFS / MinIO |
| `GHG_HOST` / `GHG_PORT` | `127.0.0.1` / `8000` | bind address of the `ghgtracker` command |
| `GHG_FRONTEND_DIR` | – | built UI (`frontend/dist`) to serve at `/`; set in the Docker image |
| `GHG_CAPTURE_FPS` | `15` | default analysis frame rate |
| `GHG_CAPTURE_WIDTH` / `_HEIGHT` | `1920` / `1080` | decode resolution |
| `GHG_STREAM_QUALITY` | `best` | streamlink quality, comma separated fallbacks |
| `GHG_SAVE_INTERVAL_SECONDS` | `5` | default snapshot interval |
| `GHG_F3_CLOSE_GRACE_FRAMES` | `3` | negative frames before an F3 event closes |
| `GHG_FFMPEG_PATH` | `ffmpeg` | |
| `GHG_OCR_ENGINE` | `ppocr6-tiny` | `ppocr6-tiny`, `ppocr6-small`, `ppocr5-mobile`, `ollama` or `none` (see below) |
| `GHG_OCR_THREADS` | `2` | CPU threads per OCR run, `0` = all cores |
| `GHG_OCR_QUEUE_SIZE` | `8` | live snapshots waiting for OCR; more are skipped and stay `pending` |
| `GHG_OCR_OLLAMA_URL` | `http://127.0.0.1:11434` | for `GHG_OCR_ENGINE=ollama` |
| `GHG_OCR_OLLAMA_MODEL` | `qwen3-vl:2b-instruct` | any Ollama vision model |

### OCR engines

The PaddleOCR presets run on the CPU via onnxruntime. Their models (a few MB each) are downloaded
to `backend/data/models/` on first start. Measured with `scripts/ocr_bench.py` on 2 threads,
using 11 labelled screenshots, each also as a 720p stream frame (22 readings). None of the engines
invented coordinates on screenshots where the XYZ line is hidden.

| Engine | Exact XYZ | Time per snapshot | Use for |
|---|---|---|---|
| `ppocr6-tiny` | 19/22 | ~0.8 s | default, small VPS |
| `ppocr6-small` | 21/22 | ~3.6 s | more accuracy if the CPU has time |
| `ppocr5-mobile` | 20/22 | ~3.1 s | alternative model family |
| `ollama` | 17/22 (`qwen3-vl:2b-instruct`) | ~145 s on CPU | only with a GPU: `ollama pull qwen3-vl:2b-instruct` |
| `none` | – | – | OCR off, snapshots stay `pending` |

## Tests

```bash
cd backend && uv run pytest     # detector + OCR (synthetic + dataset) + API + tracker end-to-end on a video
cd frontend && pnpm check
```

`backend/dataset/f3_open` and `backend/dataset/no_f3` hold real screenshots and stream frames. The
tests run the detector on every image, and also on 720p versions of the F3 images. To check new
screenshots, drop them into the right folder and run:

```bash
cd backend
uv run python scripts/evaluate_detector.py                  # whole dataset, incl. 720p/480p/JPEG variants
uv run python scripts/evaluate_detector.py --overlays /tmp/ov  # also write images with the detected lines boxed
uv run python scripts/evaluate_detector.py path/to/*.png       # any files
```

`scripts/ocr_bench.py` compares OCR engines on `dataset/f3_open`. Name files with known
coordinates `x_y_z_rot<yaw>_<anything>`, and name files whose XYZ line is hidden
`no_coordinates*`. The other engines in it (Tesseract, OnnxTR, VLMs) need extra packages, see
its docstring.
