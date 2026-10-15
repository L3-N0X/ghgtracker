from ghgtracker.models import F3Event, F3EventRead, Snapshot, SnapshotRead

MEDIA_PREFIX = "/media/snapshots"


def snapshot_to_read(snapshot: Snapshot) -> SnapshotRead:
    data = snapshot.model_dump()
    data["image_url"] = f"{MEDIA_PREFIX}/{snapshot.image_path}" if snapshot.image_path else None
    return SnapshotRead.model_validate(data)


def f3_event_to_read(event: F3Event) -> F3EventRead:
    read = F3EventRead.model_validate(event.model_dump())
    if read.closed_at is not None:
        read.duration_seconds = round((read.closed_at - read.opened_at).total_seconds(), 3)
    return read
