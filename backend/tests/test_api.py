import shutil
import time
from pathlib import Path

import cv2
import pytest

from .synthetic import f3_frame, game_background

FPS = 30


def make_video(path: Path) -> None:
    """6 s clip: F3 open from 1.0-3.0 s and a very short 0.3 s flash at 4.5 s."""
    w, h = 1280, 720
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), FPS, (w, h))
    plain = game_background(w, h, "grass", seed=1)
    debug = f3_frame(width=w, height=h, gui_scale=2, background="grass", seed=1)
    for i in range(6 * FPS):
        t = i / FPS
        writer.write(debug if 1.0 <= t < 3.0 or 4.5 <= t < 4.8 else plain)
    writer.release()


def test_health(client) -> None:
    assert client.get("/api/health").json() == {"status": "ok"}


def test_streamer_crud(client) -> None:
    res = client.post("/api/streamers", json={"login": "https://www.twitch.tv/Some_Streamer"})
    assert res.status_code == 201, res.text
    streamer = res.json()
    assert streamer["login"] == "some_streamer"
    assert client.post("/api/streamers", json={"login": "some_streamer"}).status_code == 409
    assert client.post("/api/streamers", json={"login": "no spaces!"}).status_code == 422

    res = client.patch(f"/api/streamers/{streamer['id']}", json={"display_name": "Some Streamer"})
    assert res.json()["display_name"] == "Some Streamer"
    assert any(s["id"] == streamer["id"] for s in client.get("/api/streamers").json())

    assert client.delete(f"/api/streamers/{streamer['id']}").status_code == 204
    assert client.get(f"/api/streamers/{streamer['id']}").status_code == 404


def test_detect_endpoint(client) -> None:
    ok, buf = cv2.imencode(".png", f3_frame())
    res = client.post("/api/detect", files={"file": ("f3.png", buf.tobytes(), "image/png")})
    assert res.status_code == 200
    body = res.json()
    assert body["detected"] is True
    assert body["overlay_jpeg"].startswith("data:image/jpeg;base64,")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_tracker_on_video_file(client, tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    make_video(video)
    streamer = client.post("/api/streamers", json={"login": "video_test"}).json()
    sid = streamer["id"]

    res = client.post(
        f"/api/streamers/{sid}/tracker/start",
        json={"source": str(video), "capture_fps": 15, "save_interval_seconds": 1.0},
    )
    assert res.status_code == 200, res.text
    assert client.post(f"/api/streamers/{sid}/tracker/start", json={}).status_code == 409

    deadline = time.time() + 20
    status = res.json()
    while time.time() < deadline:
        status = client.get(f"/api/streamers/{sid}/tracker").json()
        if status["state"] in ("stopped", "error"):
            break
        time.sleep(0.25)
    assert status["state"] == "stopped", status
    assert status["frames_processed"] >= 80

    events = client.get("/api/f3-events", params={"streamer_id": sid}).json()
    # Both the 2 s opening and the 0.3 s flash are caught as separate F3 events.
    assert events["total"] == 2, events
    durations = sorted(e["duration_seconds"] for e in events["items"])
    assert durations[0] < 0.6 and durations[1] > 1.5

    snaps = client.get("/api/snapshots", params={"streamer_id": sid, "order": "asc"}).json()
    # 2 s opening at 1 s interval -> 2 snapshots, plus one for the short flash.
    assert snaps["total"] == 3, snaps
    first = snaps["items"][0]
    assert first["ocr_status"] == "pending" and first["x"] is None
    assert client.get(first["image_url"]).status_code == 200

    res = client.patch(
        f"/api/snapshots/{first['id']}",
        json={"x": -1234.5, "y": 72, "z": 845.2, "biome": "minecraft:plains"},
    )
    assert res.json()["ocr_status"] == "manual"

    sessions = client.get(f"/api/streamers/{sid}/sessions").json()
    assert sessions[0]["snapshots_saved"] == 3
    assert sessions[0]["status"] == "stopped"
