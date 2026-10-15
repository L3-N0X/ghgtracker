"""Turns a Twitch channel / VOD URL / local video file into a stream of BGR frames.

    streamlink (HLS, ad handling) ──bytes──▶ ffmpeg (decode, fps + scale filter) ──rawvideo──▶ numpy

ffmpeg resamples to a fixed fps and resolution, so every frame we read has a known byte size.
"""

from __future__ import annotations

import logging
import subprocess
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class FrameSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class CaptureOptions:
    fps: float
    width: int
    height: int
    quality: str = "best"
    ffmpeg_path: str = "ffmpeg"


def twitch_channel_url(login: str) -> str:
    return f"https://www.twitch.tv/{login}"


def is_local_file(source: str) -> bool:
    return "://" not in source and Path(source).expanduser().is_file()


def resolve_stream(source: str, quality: str = "best"):
    """Return a streamlink Stream for `source`. Raises FrameSourceError if offline / unsupported."""
    from streamlink import Streamlink
    from streamlink.exceptions import NoPluginError, PluginError

    session = Streamlink()
    session.set_option("hls-live-edge", 2)  # stay close to live
    try:
        streams = session.streams(source)
    except NoPluginError as exc:
        raise FrameSourceError(f"unsupported source: {source}") from exc
    except PluginError as exc:
        raise FrameSourceError(f"could not open {source}: {exc}") from exc
    if not streams:
        raise FrameSourceError("stream is offline or has no playable streams")
    for name in [q.strip() for q in quality.split(",")] + ["best"]:
        if name in streams:
            return streams[name]
    raise FrameSourceError(f"no stream matching quality {quality!r}")


def check_live(login: str) -> bool:
    try:
        resolve_stream(twitch_channel_url(login))
    except FrameSourceError:
        return False
    return True


class FrameSource:
    """Iterate decoded frames from a source until `close()` is called or the stream ends."""

    def __init__(self, source: str, options: CaptureOptions) -> None:
        self.source = source
        self.options = options
        self._proc: subprocess.Popen[bytes] | None = None
        self._stream_fd = None
        self._pump: threading.Thread | None = None
        self._closed = threading.Event()
        self._stderr_tail: list[str] = []

    @property
    def frame_shape(self) -> tuple[int, int, int]:
        return (self.options.height, self.options.width, 3)

    def open(self) -> None:
        opts = self.options
        vf = (
            f"fps={opts.fps},"
            f"scale={opts.width}:{opts.height}:force_original_aspect_ratio=decrease,"
            f"pad={opts.width}:{opts.height}:(ow-iw)/2:(oh-ih)/2"
        )
        local = is_local_file(self.source)
        input_args = (
            ["-re", "-i", str(Path(self.source).expanduser())] if local else ["-i", "pipe:0"]
        )
        cmd = [
            opts.ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            *input_args,
            "-an",
            "-vf",
            vf,
            "-pix_fmt",
            "bgr24",
            "-f",
            "rawvideo",
            "pipe:1",
        ]
        if not local:
            stream = resolve_stream(self.source, opts.quality)
            self._stream_fd = stream.open()
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL if local else subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except FileNotFoundError as exc:
            self.close()
            raise FrameSourceError(f"ffmpeg not found at {opts.ffmpeg_path!r}") from exc

        threading.Thread(target=self._drain_stderr, daemon=True).start()
        if not local:
            self._pump = threading.Thread(target=self._pump_stream, daemon=True)
            self._pump.start()

    def frames(self) -> Iterator[np.ndarray]:
        if self._proc is None:
            self.open()
        assert self._proc is not None and self._proc.stdout is not None
        frame_bytes = self.options.width * self.options.height * 3
        stdout = self._proc.stdout
        while not self._closed.is_set():
            buf = bytearray(frame_bytes)
            view = memoryview(buf)
            read = 0
            while read < frame_bytes:
                n = stdout.readinto(view[read:])
                if not n:
                    if self._closed.is_set():
                        return
                    # Clean end of input (file / VOD finished) on a frame boundary.
                    if read == 0 and self._proc.wait() == 0:
                        return
                    raise FrameSourceError(self._exit_message())
                read += n
            yield np.frombuffer(buf, np.uint8).reshape(self.frame_shape)

    def close(self) -> None:
        self._closed.set()
        if self._stream_fd is not None:
            try:
                self._stream_fd.close()
            except Exception:  # noqa: BLE001 - best effort shutdown
                logger.debug("error closing stream", exc_info=True)
        if self._proc is not None and self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    # ------------------------------------------------------------------ internals

    def _pump_stream(self) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        try:
            while not self._closed.is_set():
                chunk = self._stream_fd.read(64 * 1024)
                if not chunk:
                    break
                self._proc.stdin.write(chunk)
        except (OSError, ValueError):
            if not self._closed.is_set():
                logger.warning("stream pump stopped", exc_info=True)
        finally:
            try:
                self._proc.stdin.close()
            except OSError:
                pass

    def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        for raw in self._proc.stderr:
            line = raw.decode(errors="replace").strip()
            if line:
                self._stderr_tail = [*self._stderr_tail[-9:], line]

    def _exit_message(self) -> str:
        detail = self._stderr_tail[-1] if self._stderr_tail else "no output"
        return f"video stream ended ({detail})"

    def __enter__(self) -> FrameSource:
        self.open()
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
