"""Job-folder layout back-compat (the 2026-08-04 `_JAIL Agent Work/` rename).

Agent working artifacts moved off the job folder's top level into `_JAIL Agent Work/`.
Already-submitted archive folders still sit on disk in the OLD shape (`_cl_work/`,
`comparison.json` and `application_coverletter_output - ….md` at the root), so the rule
under test is: readers resolve BOTH shapes preferring the new one, and a writer that asks
for the work directory always gets the new name.

The extraction test drives the real `main()` with `PdfReader` faked, so it exercises the
actual baseline lookup and diff writer rather than a reimplementation of them.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ENGINE__PUBLIC_GIT_TRACKED" / "04-TAILOR" / "learning"))

import extract_submission as es  # noqa: E402

BASELINE = "I have spent six years shipping payments infrastructure.\nI would love the chance to do it here.\n"
SUBMITTED = "I have spent six years shipping payments infrastructure.\nI am excited about this team.\n"


def _new_shape(folder):
    work = folder / "_JAIL Agent Work"
    work.mkdir()
    (work / "final.md").write_text(BASELINE, encoding="utf-8")
    (work / "resume_base_comparison.json").write_text("{}", encoding="utf-8")
    (work / "coverletter_agent_output - Acme - Senior PM.md").write_text("packet", encoding="utf-8")
    return work


def _legacy_shape(folder):
    work = folder / "_cl_work"
    work.mkdir()
    (work / "final.md").write_text(BASELINE, encoding="utf-8")
    (folder / "comparison.json").write_text("{}", encoding="utf-8")
    (folder / "application_coverletter_output - Acme - Senior PM.md").write_text("packet", encoding="utf-8")
    return work


# --- resolvers ---------------------------------------------------------------- #

def test_work_dir_defaults_to_the_new_name_for_writers(tmp_path):
    """An empty folder resolves to the NEW name, so a writer never re-creates `_cl_work/`."""
    assert es.agent_work_dir(tmp_path).name == "_JAIL Agent Work"


def test_resolvers_find_the_new_shape(tmp_path):
    _new_shape(tmp_path)
    assert es.agent_work_dir(tmp_path).name == "_JAIL Agent Work"
    assert es.coverletter_baseline(tmp_path) == tmp_path / "_JAIL Agent Work" / "final.md"
    assert es.resume_base_comparison(tmp_path).name == "resume_base_comparison.json"
    assert es.coverletter_packet(tmp_path).name == "coverletter_agent_output - Acme - Senior PM.md"


def test_resolvers_fall_back_to_the_legacy_shape(tmp_path):
    _legacy_shape(tmp_path)
    assert es.agent_work_dir(tmp_path).name == "_cl_work"
    assert es.coverletter_baseline(tmp_path) == tmp_path / "_cl_work" / "final.md"
    assert es.resume_base_comparison(tmp_path) == tmp_path / "comparison.json"
    assert es.coverletter_packet(tmp_path) == tmp_path / "application_coverletter_output - Acme - Senior PM.md"


def test_new_shape_wins_when_both_are_present(tmp_path):
    _legacy_shape(tmp_path)
    _new_shape(tmp_path)
    assert es.agent_work_dir(tmp_path).name == "_JAIL Agent Work"
    assert es.coverletter_baseline(tmp_path).parent.name == "_JAIL Agent Work"
    assert es.resume_base_comparison(tmp_path).parent.name == "_JAIL Agent Work"
    assert es.coverletter_packet(tmp_path).parent.name == "_JAIL Agent Work"


def test_resolvers_return_none_when_nothing_exists(tmp_path):
    assert es.coverletter_baseline(tmp_path) is None
    assert es.resume_base_comparison(tmp_path) is None
    assert es.coverletter_packet(tmp_path) is None


def test_unversioned_packet_wins_over_later_versions(tmp_path):
    work = _new_shape(tmp_path)
    (work / "coverletter_agent_output - Acme - Senior PM - v2.md").write_text("v2", encoding="utf-8")
    assert es.coverletter_packet(tmp_path).name == "coverletter_agent_output - Acme - Senior PM.md"


# --- the real extraction run, on both shapes ---------------------------------- #

class _FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakeReader:
    """Every PDF in the fixture folder is a one-page cover letter."""
    def __init__(self, path):
        self.pages = [_FakePage(SUBMITTED)]


def _run_extract(tmp_path, monkeypatch, build_shape):
    folder = tmp_path / "Acme - Senior PM"
    folder.mkdir()
    build_shape(folder)
    (folder / "Someone-CoverLetter - Acme - Senior PM.pdf").write_bytes(b"%PDF-fake")
    monkeypatch.setattr(es, "PdfReader", _FakeReader)
    monkeypatch.setattr(sys, "argv", ["extract_submission.py", str(folder)])
    assert es.main() == 0
    return es.extraction_dir_for_read(folder)


@pytest.mark.parametrize("shape,expected_label", [
    (_new_shape, "_JAIL Agent Work/final.md"),
    (_legacy_shape, "_cl_work/final.md"),
])
def test_extraction_diffs_against_the_baseline_in_either_shape(tmp_path, monkeypatch, shape, expected_label):
    out = _run_extract(tmp_path, monkeypatch, shape)
    manifest = (out / "MANIFEST.txt").read_text(encoding="utf-8")
    diff = (out / "coverletter-diff.txt").read_text(encoding="utf-8")

    # The baseline was found (not the "no baseline" branch) and named by its real location.
    assert "no baseline" not in manifest
    assert expected_label in diff
    # The one real edit shows up, and the untouched sentence does not.
    assert "excited about this team" in diff
    assert not any(l.startswith(("+", "-")) and "six years shipping" in l
                   for l in diff.splitlines() if not l.startswith(("+++", "---")))


def test_extraction_reports_no_baseline_when_neither_shape_exists(tmp_path, monkeypatch):
    out = _run_extract(tmp_path, monkeypatch, lambda folder: None)
    assert "COVERLETTER-DIFF: no baseline" in (out / "MANIFEST.txt").read_text(encoding="utf-8")
    assert not (out / "coverletter-diff.txt").exists()


# --- Lanes: extraction moved into "_JAIL Agent Work/Reconcile Agent/" (2026-08-06) -----------

def test_fresh_extraction_lands_in_the_reconcile_lane(tmp_path, monkeypatch):
    out = _run_extract(tmp_path, monkeypatch, _new_shape)
    folder = tmp_path / "Acme - Senior PM"
    assert out == folder / "_JAIL Agent Work" / "Reconcile Agent"
    assert (out / "MANIFEST.txt").is_file()
    # The pre-lane location is not created alongside it.
    assert not (folder / "_extracted").exists()


def test_a_legacy_extracted_folder_still_reads_as_cached_and_is_not_re_extracted(tmp_path, monkeypatch):
    """The expensive failure: ~30 archived folders hold their results in a top-level
    "_extracted/". If the cache check only looked at the new location, every one of them would
    re-extract into a second directory that can then diverge from the first."""
    folder = tmp_path / "Acme - Senior PM"
    (folder / "_extracted").mkdir(parents=True)
    (folder / "_extracted" / "MANIFEST.txt").write_text("prior run\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["extract_submission.py", str(folder)])
    assert es.main() == 0
    assert es.extraction_dir_for_read(folder) == folder / "_extracted"
    # No second extraction directory was created.
    assert not (folder / "_JAIL Agent Work" / "Reconcile Agent").exists()


def test_an_empty_lane_dir_does_not_count_as_a_completed_extraction(tmp_path):
    """Resolution is by MANIFEST.txt, not directory existence — an interrupted run leaves a
    bare directory behind and it must not read as cached."""
    folder = tmp_path / "Acme - Senior PM"
    (folder / "_JAIL Agent Work" / "Reconcile Agent").mkdir(parents=True)
    (folder / "_extracted").mkdir()
    (folder / "_extracted" / "MANIFEST.txt").write_text("real\n", encoding="utf-8")
    assert es.extraction_dir_for_read(folder) == folder / "_extracted"


@pytest.mark.parametrize("where", [
    ("_JAIL Agent Work", "Cover Letter Agent"),   # current shape
    ("_JAIL Agent Work",),                        # flat (2026-08-04)
    ("_cl_work",),                                # legacy
])
def test_the_baseline_is_found_in_every_historical_shape(tmp_path, where):
    folder = tmp_path / "Acme - Senior PM"
    d = folder.joinpath(*where)
    d.mkdir(parents=True)
    (d / "final.md").write_text("hi\n", encoding="utf-8")
    assert es.coverletter_baseline(folder) == d / "final.md"


def test_the_current_shape_wins_when_several_shapes_coexist(tmp_path):
    """A half-migrated folder is a real state; the newest shape must win, not first-found."""
    folder = tmp_path / "Acme - Senior PM"
    for where in (("_cl_work",), ("_JAIL Agent Work",), ("_JAIL Agent Work", "Cover Letter Agent")):
        d = folder.joinpath(*where)
        d.mkdir(parents=True, exist_ok=True)
        (d / "final.md").write_text("hi\n", encoding="utf-8")
    assert es.coverletter_baseline(folder) == folder / "_JAIL Agent Work" / "Cover Letter Agent" / "final.md"


def test_write_dir_ignores_a_legacy_dir_that_already_exists(tmp_path):
    """agent_work_dir() answers the first EXISTING dir, which is right for reading and wrong for
    writing — it would keep growing "_cl_work/". Writers use work_dir_for_write()."""
    folder = tmp_path / "Acme - Senior PM"
    (folder / "_cl_work").mkdir(parents=True)
    assert es.agent_work_dir(folder) == folder / "_cl_work"          # read: finds the legacy one
    assert es.work_dir_for_write(folder) == folder / "_JAIL Agent Work"
