"""Static coverage for the folder-layout knowledge embedded in agent prompts.

The prompts (workflow JS, agent/skill Markdown) are as load-bearing as the Python — they tell an
agent where to read and write — but nothing executes them, so nothing catches a stale path. The
2026-08-04 rename is what that costs: ~30 hardcoded literals across six files, discovered only by
grepping months later.

These tests are pure text analysis over tracked files. They can't prove an agent follows an
instruction, but they can prove the instruction still points somewhere real.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "ENGINE__PUBLIC_GIT_TRACKED" / "04-TAILOR"))

import job_folder_layout as layout  # noqa: E402

LOOKUP_CLI = "ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/job_folder_layout.py"

WORKFLOWS = [REPO / ".claude/workflows/cover-letter.js", REPO / ".claude/workflows/reconcile.js"]

# Every file that tells an agent where job-folder artifacts live must resolve paths through the
# lookup CLI rather than describing a search order. Prose is a chain a model has to execute
# correctly every time; the command just answers.
MUST_USE_LOOKUP = WORKFLOWS + [
    REPO / ".claude/agents/cover-letter-writer.md",
    REPO / ".claude/agents/job-applier.md",
    REPO / ".claude/skills/revise-cover-letter/SKILL.md",
]

# The baseline is the reconcile learning signal. A file that names `final.md` is a file that can
# silently re-baseline the loop, so the set is pinned: a new member fails this test until someone
# adds it deliberately and looks at what it does with the name.
BASELINE_CONSUMERS = {
    ".claude/workflows/cover-letter.js",
    ".claude/workflows/reconcile.js",
    ".claude/agents/cover-letter-writer.md",
    ".claude/agents/job-applier.md",
    ".claude/skills/revise-cover-letter/SKILL.md",
    "ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/00-job_application_agent.md",
    "ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/README.md",
    "ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/feedback-queue.template.md",
    "ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/cover-letter/formatting-spec.template.md",
    "ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/job_folder_layout.py",
    "ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/learning/extract_submission.py",
    "ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/learning/reconcile-spec.md",
    "docs/final-review-and-cover-letters.md",
    # Prose only — these describe the baseline, nothing resolves or writes it.
    "docs/changelog.md",
    "docs/v2-end-to-end-workflow.md",
    # Tests: the layout suite asserts baseline resolution (that IS its subject); the docx suite
    # only uses "final.md" as a scratch filename.
    "tests/test_app_folder_layout.py",
    "tests/test_cover_letter_docx_bullets.py",
    # The migration names it in order to REFUSE to rename it (a hard-coded refusal, not a flag),
    # and its test asserts that refusal. Reviewed 2026-08-06: neither writes the file.
    "ENGINE__PUBLIC_GIT_TRACKED/04-TAILOR/migrate_job_folder_layout.py",
    "tests/test_migrate_job_folder_layout.py",
}

SEARCH_ROOTS = [".claude", "ENGINE__PUBLIC_GIT_TRACKED", "docs", "tests"]


def _tracked_text_files():
    out = subprocess.run(["git", "ls-files", *SEARCH_ROOTS], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout.splitlines()
    return [REPO / f for f in out
            if f.rsplit(".", 1)[-1] in {"js", "py", "md", "json", "txt"} and (REPO / f).is_file()]


@pytest.mark.parametrize("path", MUST_USE_LOOKUP, ids=lambda p: p.name)
def test_prompts_resolve_paths_by_asking_not_by_assuming(path):
    """Either route counts: the lookup CLI, or (reconcile only) the EXTRACTION_DIR line that
    extract_submission.py prints. What must never appear is a location the prompt composed."""
    text = path.read_text(encoding="utf-8")
    assert LOOKUP_CLI in text or "EXTRACTION_DIR" in text, (
        f"{path.relative_to(REPO)} directs an agent around a job folder but never asks where "
        f"anything is — it is describing a search order in prose instead of resolving one.")


@pytest.mark.parametrize("path", MUST_USE_LOOKUP, ids=lambda p: p.name)
def test_prompts_do_not_point_writers_at_a_legacy_location(path):
    """A legacy path may be MENTIONED (explaining back-compat) but never used as a destination.
    Lines that say so are exempt; anything else naming one is a writer aimed at a dead folder."""
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for legacy in (*layout.LEGACY_WORK_DIRS, layout.LEGACY_EXTRACTION_DIR):
            if legacy in line and not re.search(r"legacy|older|back-compat|historical|earlier", line, re.I):
                pytest.fail(f"{path.relative_to(REPO)}:{i} names {legacy!r} without marking it "
                            f"legacy:\n  {line.strip()[:160]}")


def test_the_set_of_files_naming_the_baseline_is_pinned():
    """`final.md` is the one filename whose mis-resolution corrupts the learning loop silently
    rather than failing loudly. Adding a consumer should be a decision, not a side effect."""
    found = {str(p.relative_to(REPO)) for p in _tracked_text_files()
             if re.search(r"\bfinal\.md\b", p.read_text(encoding="utf-8", errors="ignore"))}
    found -= {str(Path(__file__).relative_to(REPO))}
    new = found - BASELINE_CONSUMERS
    assert not new, (
        "These files newly reference the reconcile baseline `final.md`. Confirm each one resolves "
        "it via the lookup CLI (or coverletter_baseline()) and never writes it, then add it to "
        f"BASELINE_CONSUMERS: {sorted(new)}")


def test_lane_names_in_prompts_match_the_module():
    """A lane named in a prompt must be spelled exactly as the code creates it — the directory is
    created from the constant, so a typo in prose sends an agent to a folder that never exists."""
    misspellings = re.compile(r"\b(Cover ?Letter|Reconcile|Resume ?Tailoring) Agent\b")
    for path in MUST_USE_LOOKUP:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for m in misspellings.finditer(line):
                assert m.group(0) in layout.LANES, (
                    f"{path.relative_to(REPO)}:{i} spells a lane {m.group(0)!r}, "
                    f"which is not one of {layout.LANES}")


def test_shell_usages_of_the_work_dir_are_quoted():
    """`_JAIL Agent Work` contains spaces; an unquoted path silently becomes two arguments."""
    cmd = re.compile(r"(?:cd|mkdir(?:\s+-p)?|ls|cat|rm)\s+(?!['\"])\S*" + re.escape(layout.WORK_DIR))
    for path in MUST_USE_LOOKUP:
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            assert not cmd.search(line), (
                f"{path.relative_to(REPO)}:{i} uses {layout.WORK_DIR!r} unquoted in a shell "
                f"command:\n  {line.strip()[:160]}")


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_scripts_still_parse(path):
    """These are template literals full of prose; an unescaped backtick is a syntax error that
    only shows up at run time, mid-workflow."""
    r = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_the_docx_step_asks_for_the_draft_name_not_the_deliverable_name():
    """The .docx is a copy-paste source, not what gets submitted. If the finalize step ever
    reverts to --cover-letter-filename it silently starts producing a candidate-prefixed name
    one character from the real deliverable sitting beside it."""
    text = (REPO / ".claude/workflows/cover-letter.js").read_text(encoding="utf-8")
    assert "--cover-letter-draft-filename" in text
    assert "--cover-letter-filename" not in text.replace("--cover-letter-draft-filename", "")
