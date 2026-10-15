"""In-process pub/sub that fans tracker events out to WebSocket clients.

Tracker workers run in threads, so `publish` is thread-safe and hops onto the event loop.
"""

import asyncio
import contextlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


class EventBus:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=500)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event_type: str, **payload: Any) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        message = {"type": event_type, **payload}
        try:
            self._loop.call_soon_threadsafe(self._dispatch, message)
        except RuntimeError:  # loop shutting down
            pass

    def _dispatch(self, message: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            if queue.full():
                # Slow client: drop its oldest event rather than blocking everyone.
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(message)


event_bus = EventBus()
