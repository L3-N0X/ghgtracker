import os
import tempfile
from pathlib import Path

import pytest

# Must happen before the app (and its cached settings / engine) is imported.
_DATA_DIR = Path(tempfile.mkdtemp(prefix="ghgtracker-test-"))
os.environ["GHG_DATA_DIR"] = str(_DATA_DIR)
os.environ["GHG_CAPTURE_WIDTH"] = "1280"
os.environ["GHG_CAPTURE_HEIGHT"] = "720"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return _DATA_DIR


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from ghgtracker.main import app

    with TestClient(app) as test_client:
        yield test_client
