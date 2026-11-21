import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from austral_headlines.config import load_settings  # noqa: E402


@pytest.fixture(scope="session")
def settings():
    return load_settings()
