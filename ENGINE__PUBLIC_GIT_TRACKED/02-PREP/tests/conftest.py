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
    (it lives under the gitignored PRIVATE root). Every test gets its own.

    Also stubs the employer-name lookup's network step to a recording no-op: it runs
    inside `process_urls`, so without this a synthetic fixture whose URL looks like an
    employer domain makes a LIVE request from the test suite (it did — the run jumped
    to 66s once the enrichment moved onto the shared path). Tests that exercise the
    lookup inject their own fetcher; tests that care about WHEN it fires request this
    fixture by name to read the recorded calls."""
    import prep_common
    monkeypatch.setattr(prep_common, "DEFAULT_REGISTRY_PATH",
                        tmp_path / "_registry" / "capture-history-registry.json")
    calls: list = []

    def _no_network(url, **_kw):
        calls.append(url)
        return None
    monkeypatch.setattr(prep_common, "EMPLOYER_NAME_FETCHER", _no_network)
    return calls


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def load():
    return load_fixture
