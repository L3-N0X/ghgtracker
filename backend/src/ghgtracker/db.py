from collections.abc import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from ghgtracker.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.resolved_database_url
        is_sqlite = url.startswith("sqlite")
        if is_sqlite:
            settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(
            url,
            # Tracker workers write from their own threads.
            connect_args={"check_same_thread": False} if is_sqlite else {},
        )
        if is_sqlite:
            event.listen(_engine, "connect", _configure_sqlite)
    return _engine


def _configure_sqlite(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    # WAL lets the API read while tracker threads write.
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def init_db() -> None:
    from ghgtracker import models  # noqa: F401  (registers tables)

    SQLModel.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
