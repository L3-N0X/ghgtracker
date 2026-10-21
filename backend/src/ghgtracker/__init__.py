"""Twitch Minecraft coordinate tracker backend."""


def main() -> None:
    import uvicorn

    from ghgtracker.config import get_settings

    settings = get_settings()
    uvicorn.run("ghgtracker.main:app", host=settings.host, port=settings.port)
