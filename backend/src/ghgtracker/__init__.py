"""Twitch Minecraft coordinate tracker backend."""


def main() -> None:
    import uvicorn

    uvicorn.run("ghgtracker.main:app", host="127.0.0.1", port=8000)
