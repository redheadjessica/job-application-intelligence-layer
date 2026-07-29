"""Make the prep modules importable without installing them, and expose the
fixtures dir. Tests read saved fixtures from disk — they never hit the network."""
import json
import sys
from pathlib import Path

import pytest

PREP_DIR = Path(__file__).resolve().parent.parent  # ENGINE__PUBLIC_GIT_TRACKED/02-PREP
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(PREP_DIR) not in sys.path:
    sys.path.insert(0, str(PREP_DIR))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def load():
    return load_fixture
