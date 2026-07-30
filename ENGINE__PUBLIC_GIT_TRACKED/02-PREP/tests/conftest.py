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


@pytest.fixture(autouse=True)
def _isolated_capture_registry(tmp_path, monkeypatch):
    """No test may ever read or write the user's REAL capture-history registry
    (it lives under the gitignored PRIVATE root). Every test gets its own."""
    import prep_common
    monkeypatch.setattr(prep_common, "DEFAULT_REGISTRY_PATH",
                        tmp_path / "_registry" / "capture-history-registry.json")


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def load():
    return load_fixture
