"""Back-fill migration into the lane layout.

The migration is cosmetic — readers already handle every historical shape — so the bar is not
"does it move things" but "can it ever lose or corrupt something". Most of these tests are about
what it REFUSES to do.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
MODULE = REPO / "ENGINE__PUBLIC_GIT_TRACKED" / "04-TAILOR" / "migrate_job_folder_layout.py"
_spec = importlib.util.spec_from_file_location("migrate_job_folder_layout", MODULE)
mig = importlib.util.module_from_spec(_spec)
sys.modules["migrate_job_folder_layout"] = mig
_spec.loader.exec_module(mig)

CL = "_JAIL Agent Work/Cover Letter Agent"
RC = "_JAIL Agent Work/Reconcile Agent"
RS = "_JAIL Agent Work/Resume Tailoring Agent"


def _write(p, text="x"):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _flat_folder(root, name="Acme - Senior PM"):
    """The 2026-08-04 shape: everything flat inside the work dir."""
    f = root / name
    for n in ("draft-v1.md", "eval-1.md", "final.md", "final-v2.md",
              "coverletter_agent_output - Acme - Senior PM.md", "resume_base_comparison.json"):
        _write(f / "_JAIL Agent Work" / n)
    _write(f / "Jessica Barnett-Cover-Letter - Acme - Senior PM.docx")
    _write(f / "application_resume_output - Acme - Senior PM.md")
    return f


def _inventory(folder):
    return {str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()}


def test_a_flat_folder_lands_in_its_lanes(tmp_path):
    f = _flat_folder(tmp_path)
    assert mig.migrate(tmp_path, apply=True, out=lambda *_: None) == 0
    inv = _inventory(f)
    assert f"{CL}/final.md" in inv and f"{CL}/final-v2.md" in inv and f"{CL}/draft-v1.md" in inv
    assert f"{CL}/coverletter_agent_output - Acme - Senior PM.md" in inv
    assert f"{RS}/resume_base_comparison.json" in inv
    # eval-1.md gains its version letter; final.md never changes name.
    assert f"{CL}/eval-v1.md" in inv and f"{CL}/eval-1.md" not in inv


def test_the_docx_is_renamed_and_the_deliverables_are_untouched(tmp_path):
    f = _flat_folder(tmp_path)
    _write(f / "Jessica Barnett-Resume - Acme - Senior PM.pdf")
    _write(f / "Jessica Barnett-CoverLetter - Acme - Senior PM.pdf")
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    inv = _inventory(f)
    assert "Cover-Letter-Draft - Acme - Senior PM.docx" in inv
    assert "Jessica Barnett-Cover-Letter - Acme - Senior PM.docx" not in inv
    # PDFs and the review packet stay exactly where the candidate expects them.
    assert "Jessica Barnett-Resume - Acme - Senior PM.pdf" in inv
    assert "Jessica Barnett-CoverLetter - Acme - Senior PM.pdf" in inv
    assert "application_resume_output - Acme - Senior PM.md" in inv


def test_the_pre_lane_extraction_folds_into_the_reconcile_lane(tmp_path):
    f = tmp_path / "Acme - Senior PM"
    for n in ("MANIFEST.txt", "submitted-resume.txt", "coverletter-diff.txt"):
        _write(f / "_extracted" / n)
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    inv = _inventory(f)
    assert f"{RC}/MANIFEST.txt" in inv and f"{RC}/coverletter-diff.txt" in inv
    assert not list((f / "_extracted").glob("*"))


def test_legacy_root_sidecars_are_filed_under_their_current_names(tmp_path):
    f = tmp_path / "Acme - Senior PM"
    _write(f / "_cl_work" / "final.md")
    _write(f / "comparison.json")
    _write(f / "application_coverletter_output - Acme - Senior PM.md")
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    inv = _inventory(f)
    assert f"{RS}/resume_base_comparison.json" in inv
    assert f"{CL}/coverletter_agent_output - Acme - Senior PM.md" in inv
    assert f"{CL}/final.md" in inv


# --- what it must refuse ---------------------------------------------------- #

def test_a_dry_run_changes_nothing(tmp_path):
    f = _flat_folder(tmp_path)
    before = _inventory(f)
    assert mig.migrate(tmp_path, apply=False, out=lambda *_: None) == 0
    assert _inventory(f) == before


def test_running_twice_is_a_no_op(tmp_path):
    f = _flat_folder(tmp_path)
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    after_first = _inventory(f)
    lines = []
    mig.migrate(tmp_path, apply=True, out=lines.append)
    assert _inventory(f) == after_first
    assert "1 already current" in "\n".join(lines)


@pytest.mark.parametrize("bystander", [
    "eval-rubric.md",                    # not a numbered eval
    "eval-1__draft-v1-ARCHIVED.md",      # a deliberate archive marker
    "draft-v4-jessica-handwritten.md",   # hand-authored, not the agent's draft-v4
    "final-v2-proposal.md",              # a proposal, not a finalized letter
])
def test_lookalike_filenames_are_left_alone(tmp_path, bystander):
    """Every one of these exists in the real archive. A loose eval-*/final-* glob eats them."""
    f = _flat_folder(tmp_path)
    _write(f / "_JAIL Agent Work" / bystander)
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    assert (f / "_JAIL Agent Work" / bystander).is_file()


def test_a_destination_collision_skips_the_whole_folder(tmp_path):
    """Never half-move: a folder either arrives entirely or is left exactly as it was."""
    f = _flat_folder(tmp_path)
    _write(f / CL / "final.md", "already here")
    before = _inventory(f)
    lines = []
    mig.migrate(tmp_path, apply=True, out=lines.append)
    assert _inventory(f) == before
    assert "SKIP" in "\n".join(lines)


def test_a_symlink_skips_the_folder(tmp_path):
    f = _flat_folder(tmp_path)
    target = _write(tmp_path / "elsewhere.md")
    link = f / "_JAIL Agent Work" / "draft-v2.md"
    link.symlink_to(target)
    before = _inventory(f)
    lines = []
    mig.migrate(tmp_path, apply=True, out=lines.append)
    assert _inventory(f) == before and "SKIP" in "\n".join(lines)
    assert target.is_file()


def test_an_old_conflicted_copy_does_not_block_the_run(tmp_path):
    """Two 2015-era "conflicted copy" aliases sit in the real archive. Refusing on those blocks
    the migration forever over files that say nothing about whether a sync is in flight."""
    import os, time
    f = _flat_folder(tmp_path)
    stale = _write(tmp_path / "old (Jessicas-MacBook's conflicted copy 2015-01-24)")
    old_t = time.time() - 400 * 24 * 3600
    os.utime(stale, (old_t, old_t))
    assert mig.migrate(tmp_path, apply=True, out=lambda *_: None) == 0
    assert f"{CL}/final.md" in _inventory(f)


def test_a_sync_conflict_stops_the_run_before_anything_moves(tmp_path):
    f = _flat_folder(tmp_path)
    _write(tmp_path / "notes (Jessica's conflicted copy 2026-08-06).md")
    before = _inventory(f)
    lines = []
    assert mig.migrate(tmp_path, apply=True, out=lines.append) == 2
    assert _inventory(f) == before
    assert "REFUSING" in "\n".join(lines)


def test_unrelated_directories_are_not_job_folders(tmp_path):
    """The archive is full of loose .docx files in directories that are not applications."""
    d = tmp_path / "Old Cover Letters"
    _write(d / "Cover Letters EDIT.docx")
    _write(d / "360 report.docx")
    before = _inventory(d)
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    assert _inventory(d) == before


def test_pages_bundles_are_not_descended_into(tmp_path):
    """`.pages` files are directories on macOS; walking into one would migrate its internals."""
    f = _flat_folder(tmp_path)
    _write(f / "Resume.pages" / "final.md")
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    assert (f / "Resume.pages" / "final.md").is_file()


def test_nothing_is_ever_deleted(tmp_path):
    f = _flat_folder(tmp_path)
    before = {p.name for p in f.rglob("*") if p.is_file()}
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    after = {p.name for p in f.rglob("*") if p.is_file()}
    # Same file COUNT; only eval-1.md and the .docx changed name.
    assert len(after) == len(before)
    assert "final.md" in after


def test_a_half_migrated_folder_completes_cleanly(tmp_path):
    """A real intermediate state: some files already filed, others still flat."""
    f = tmp_path / "Acme - Senior PM"
    _write(f / CL / "final.md")
    _write(f / "_JAIL Agent Work" / "draft-v1.md")
    _write(f / "_JAIL Agent Work" / "resume_base_comparison.json")
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    inv = _inventory(f)
    assert inv == {f"{CL}/final.md", f"{CL}/draft-v1.md", f"{RS}/resume_base_comparison.json"}


def test_backup_snapshots_are_never_migrated(tmp_path):
    """A folder named "pre-folder-rename" exists precisely to preserve the pre-rename shape."""
    f = _flat_folder(tmp_path / "_backups" / "2026-08-04-pre-folder-rename")
    before = _inventory(f)
    lines = []
    mig.migrate(tmp_path, apply=True, out=lines.append)
    assert _inventory(f) == before
    assert "0 job folder(s)" in "\n".join(lines)


def test_a_job_folder_nested_inside_another_is_still_found(tmp_path):
    """A folder covering two roles at one company keeps the first role's artifacts at its top
    level and the second in a subfolder. Stopping at the first match strands the nested one."""
    outer = _flat_folder(tmp_path, "Dropbox - Staff & Principal PM")
    inner = outer / "Principal PM - Teams & Collab"
    for n in ("MANIFEST.txt", "submitted-resume.txt"):
        _write(inner / "_extracted" / n)
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    assert f"{RC}/MANIFEST.txt" in _inventory(inner)
    assert f"{CL}/final.md" in _inventory(outer)


def test_the_walker_does_not_recurse_into_a_migrated_lane(tmp_path):
    """Lanes live inside a job folder; treating one as a folder to migrate would loop."""
    f = _flat_folder(tmp_path)
    mig.migrate(tmp_path, apply=True, out=lambda *_: None)
    found = [str(p) for p in mig.find_job_folders(tmp_path)]
    assert found == [str(f)]
