import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ghgtracker.events import event_bus

router = APIRouter()


@router.websocket("/ws")
async def events_socket(websocket: WebSocket):
    """Push tracker events: tracker.status, f3.opened, f3.closed, snapshot.created."""
    await websocket.accept()
    queue = event_bus.subscribe()
    trackers = websocket.app.state.tracker_manager
    try:
        for status in trackers.all_statuses():
            await websocket.send_json(
                {"type": "tracker.status", "status": status.model_dump(mode="json")}
            )
        receiver = asyncio.create_task(_drain_client(websocket))
        while not receiver.done():
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, receiver}, return_when=asyncio.FIRST_COMPLETED)
            if getter in done:
                await websocket.send_json(getter.result())
            else:
                getter.cancel()
    except WebSocketDisconnect:
        pass
    finally:
        event_bus.unsubscribe(queue)


async def _drain_client(websocket: WebSocket) -> None:
    """Consume (and ignore) client messages; returns when the client disconnects."""
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        return
