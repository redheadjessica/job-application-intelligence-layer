"""
Guards for the tailoring output contract.

The repo has now had the same bug at least seven times: a rule defined in two places, the
two drift, and the drift is invisible until an artifact is read by hand. For Python that
class is already caught mechanically (norm_contracts is the single source, and a test
asserts STATUS_COLORS keys equal STATUS_VALUES). For the PROMPT layer — spec + agent files
+ workflow prompts — there was no single source and no test, so on 2026-08-07 a spec
restructure left `job-applier.md` still enumerating the retired section list, and 31 of 35
résumés were built to the old shape. That list omitted `Selected Writing` and `Read Log`,
so 32 of 35 shipped with no writing links at all.

Prompt duplication is far more dangerous than code duplication: two disagreeing Python
definitions produce an error, while two disagreeing prompt definitions are resolved
independently by each agent — partial compliance, which survives spot-checks and looks
like success.

These tests make the duplication break the build instead of the batch.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
TAILOR = ROOT / "ENGINE__PUBLIC_GIT_TRACKED" / "04-TAILOR"
SPEC = TAILOR / "00-job_application_agent.md"
sys.path.insert(0, str(TAILOR))
import check_tailoring_output as cto  # noqa: E402

# Files that TELL an agent how to produce the tailoring output. Any of them enumerating
# the output's sections is a second definition of the contract.
OVERLAY_FILES = [
    ROOT / ".claude" / "agents" / "job-applier.md",
    ROOT / ".claude" / "workflows" / "tailor-jobs.js",
    ROOT / ".claude" / "workflows" / "run-batch.js",
]

# Headings retired by the 2026-08-07 restructure. An overlay naming one of these as the
# section to produce is exactly the drift that caused the regression.
RETIRED_IN_OVERLAYS = [
    "Questions for the candidate** section added at the top",
    "Questions for the candidate\" section at the top",
    "with the **Questions for the candidate**",
]


def _spec_text() -> str:
    return SPEC.read_text(encoding="utf-8")


def test_spec_declares_a_parseable_output_structure():
    """The single source must be machine-readable, or the validator has to hardcode a
    copy — which would be a third definition and the next thing to drift."""
    sections = cto.required_sections(_spec_text())
    names = [s["name"] for s in sections]
    assert len(names) >= 5, names
    assert any(n.endswith("Decisions Needed") for n in names)
    assert any("Build" in n for n in names)


def test_selected_writing_and_read_log_are_in_the_structure():
    """The two sections the retired overlay list omitted. Their absence from the contract
    is what let them vanish from 27 and 35 files respectively."""
    spec = _spec_text()
    children = cto.required_children(spec, "2")
    assert any("Selected Writing" in c for c in children), children
    assert "### Read Log" in spec


@pytest.mark.parametrize("path", OVERLAY_FILES, ids=lambda p: p.name)
def test_overlay_files_do_not_re_enumerate_the_output_sections(path: Path):
    """An overlay may POINT at the spec's structure. It may not restate it.

    The 08-07-26 failure in one line: `job-applier.md` listed "job analysis, gap check,
    resume-base recommendation, work-experience changes, 3 summary options, skills line,
    integrity check" — seven sections, omitting Selected Writing and Read Log — and agents
    followed the list they were handed rather than the spec they were pointed at."""
    if not path.is_file():
        pytest.skip(f"{path.name} not present")
    text = path.read_text(encoding="utf-8")
    # An enumeration = three or more distinct section names in one sentence/line.
    section_words = ["job analysis", "gap check", "resume-base recommendation",
                     "work-experience changes", "summary options", "skills line",
                     "integrity check", "strategic evidence"]
    for line in text.splitlines():
        low = line.lower()
        hits = [w for w in section_words if w in low]
        if len(hits) >= 3 and "must not" not in low and "omitted" not in low:
            pytest.fail(
                f"{path.name} enumerates the output's sections ({hits}). The spec's "
                f"Primary Output Format block is the only enumeration; point at it instead."
            )


@pytest.mark.parametrize("path", OVERLAY_FILES, ids=lambda p: p.name)
def test_overlays_do_not_demand_the_retired_questions_section(path: Path):
    """"Add a Questions for the candidate section at the top" names a section the current
    structure does not have. Telling an agent to bolt an extra section onto a structure it
    doesn't fit is what made agents abandon the new structure wholesale."""
    if not path.is_file():
        pytest.skip(f"{path.name} not present")
    text = path.read_text(encoding="utf-8")
    for phrase in RETIRED_IN_OVERLAYS:
        assert phrase not in text, (
            f"{path.name} still instructs the agent to add the retired "
            f"'Questions for the candidate' section: {phrase!r}"
        )


# --------------------------------------------------------------------------- #
# Golden-file behaviour of the validator — one case per defect actually shipped
# on 2026-08-07, so a regression to any of them fails here rather than in a batch.
# --------------------------------------------------------------------------- #
GOOD = """\
## 1. Decisions Needed
None — straightforward fit.

## 2. Résumé Build
### Base
Chosen: <Base A>. Considered and rejected: <Base B> (page 1 is the wrong shape for this JD).
### Work Experience
#### Anchor Role
Notes: swapped the funnel bullet.

- Led the earliest dedicated new-user experience work across onboarding and activation experiments.
- Drove the largest product expansion in the org, from MVP to the number one driver of paid upgrades.
### Summary — pick one
Option A: ...
### Skills
Product Strategy, Acquisition & Onboarding, Activation, Subscription Monetization, Experimentation, Data-Informed Decisions, Cross-Functional Leadership, Roadmap Prioritization, Growth, User Research, Product Analytics, Stakeholder Management, Technical Tradeoffs, Systems Thinking
### Selected Writing / Projects
- "A Piece About Onboarding" — https://example.com/a-piece — matches the JD's activation thesis

## 3. Application Questions
None Found.

## 5. Analysis & Audit (reference)
### Read Log
- 04-experience-bank.md
"""


def _check(md: str):
    return cto.check(md, _spec_text())


def test_golden_good_output_passes():
    assert _check(GOOD) == [], _check(GOOD)


def test_writing_piece_without_a_url_fails():
    bad = GOOD.replace(' — https://example.com/a-piece', '')
    rules = {f["rule"] for f in _check(bad)}
    assert "writing-piece-without-url" in rules


def test_missing_selected_writing_fails():
    bad = re.sub(r"### Selected Writing / Projects\n.*?\n\n", "\n", GOOD, flags=re.S)
    rules = {f["rule"] for f in _check(bad)}
    assert "missing-subsection" in rules


def test_retired_structure_fails():
    bad = GOOD.replace("## 1. Decisions Needed", "## Questions for the candidate")
    rules = {f["rule"] for f in _check(bad)}
    assert "retired-heading" in rules or "missing-section" in rules


def test_numbered_quoted_bullets_fail():
    bad = GOOD.replace(
        "- Led the earliest dedicated new-user experience work across onboarding and activation experiments.\n"
        "- Drove the largest product expansion in the org, from MVP to the number one driver of paid upgrades.",
        '1. Expansion: "Drove the largest product expansion in the org, from MVP to the number one driver of paid upgrades."')
    rules = {f["rule"] for f in _check(bad)}
    assert "bullet-not-paste-ready" in rules


def test_driver_annotation_under_a_bullet_fails():
    bad = GOOD.replace(
        "- Drove the largest product expansion in the org, from MVP to the number one driver of paid upgrades.",
        "- Drove the largest product expansion in the org, from MVP to the number one driver of paid upgrades.\n"
        "   *(Driver: subscription conversion is the JD thesis.)*")
    rules = {f["rule"] for f in _check(bad)}
    assert "bullet-annotation" in rules


def test_thin_or_missing_skills_fails():
    thin = GOOD.replace(
        "Product Strategy, Acquisition & Onboarding, Activation, Subscription Monetization, "
        "Experimentation, Data-Informed Decisions, Cross-Functional Leadership, Roadmap Prioritization, Growth",
        "Product Strategy, Growth, Experimentation")
    assert "skills-too-thin" in {f["rule"] for f in _check(thin)}
    gone = re.sub(r"### Skills\n.*?\n(?=###)", "", GOOD, flags=re.S)
    assert "missing-skills" in {f["rule"] for f in _check(gone)}


def test_missing_read_log_fails():
    bad = GOOD.replace("### Read Log\n- 04-experience-bank.md\n", "")
    assert "missing-read-log" in {f["rule"] for f in _check(bad)}


def test_conditional_section_absence_is_not_a_failure():
    """§4 Content Opportunity is spec-marked "ONLY if the candidate opted in ... omit the
    section entirely otherwise". Flagging its absence would be the checker inventing a rule
    the spec does not have — and a checker that flags valid output trains people to ignore it."""
    assert "missing-section" not in {f["rule"] for f in _check(GOOD)}


# --------------------------------------------------------------------------- #
# Job-folder rules: exactly one base résumé artifact, in its native format.
# On 08-07-26, 4 of 35 folders received both a .pages and a .pdf of the same
# résumé and 3 received a PDF with no editable source — agents copying the PDF
# so they could score it, which was never needed (the comparison pass reads the
# base's PDF in place, from the base's own folder).
# --------------------------------------------------------------------------- #
def _folder(tmp_path, *names):
    for n in names:
        (tmp_path / n).write_text("x")
    return cto.check_job_folder(tmp_path)


def test_one_native_base_copy_is_clean(tmp_path):
    assert _folder(tmp_path, "Someone-Resume - Acme - Senior PM.pages") == []


def test_same_resume_in_two_formats_is_flagged(tmp_path):
    rules = {f["rule"] for f in _folder(
        tmp_path,
        "Someone-Resume - Acme - Senior PM.pages",
        "Someone-Resume - Acme - Senior PM.pdf")}
    assert "duplicate-base-artifact" in rules


def test_pdf_only_leaves_nothing_to_tailor_from(tmp_path):
    rules = {f["rule"] for f in _folder(tmp_path, "Someone-Resume - Acme - Senior PM.pdf")}
    assert "no-editable-base" in rules


def test_a_cover_letter_is_not_a_base_artifact(tmp_path):
    """The folder legitimately holds a cover letter and the job capture; neither is a
    second copy of the résumé, and flagging them would train people to ignore the check."""
    assert _folder(
        tmp_path,
        "Someone-Resume - Acme - Senior PM.pages",
        "Cover-Letter-Draft - Acme - Senior PM.docx",
        "Someone-CoverLetter - Acme - Senior PM.pdf",
        "acme__senior-product-manager.txt") == []


def test_skills_count_reads_the_line_not_the_notes():
    """The first version took "the longest comma-rich line in the section" and cheerfully
    measured a notes bullet, reporting a 13-item skills line as having 5. A checker that
    measures the wrong line is worse than none: it reports confident numbers about
    something it never looked at."""
    body = """
Product Strategy, Product Discovery, Healthcare Products, CRM & Workflow Products, Complex Workflow Design, Operational Product Management, Hands-On AI Product Building, Stakeholder Management, Cross-Functional Leadership, Agile & Lean Practices, Roadmap Prioritization, Data-Informed Decision Making, Product Analytics, Technical Tradeoffs

Notes:
- Intentionally omitted: the psychology cluster, the growth cluster, the retention cluster, and several other long comma-laden phrases that are prose, not a skills line.
"""
    assert cto.skills_item_count(body) == 14


def test_a_bolded_lead_in_paragraph_is_not_the_skills_line():
    body = """
**One targeted swap, driven by the JD's ask:** drop **"B2B SaaS"**, add **"AI Product Building"**, keeping length, with commas, commas, commas.

Alpha, Beta, Gamma, Delta, Epsilon, Zeta, Eta, Theta, Iota, Kappa, Lambda, Mu, Nu, Xi
"""
    assert cto.skills_item_count(body) == 14


def test_thin_skills_line_fails_at_the_reviewed_floor():
    """13 items was called "too short" by the candidate on review; 14 is the floor."""
    # Locate the fixture's skills line rather than restating it — a second copy of that
    # string here would be one more thing to drift, which is the bug this file guards.
    line = re.search(r"(?m)^Product Strategy,.*$", GOOD).group(0)
    thirteen = ", ".join(f"Skill {i}" for i in range(13))
    fourteen = ", ".join(f"Skill {i}" for i in range(14))
    assert "skills-too-thin" in {f["rule"] for f in _check(GOOD.replace(line, thirteen))}
    assert "skills-too-thin" not in {f["rule"] for f in _check(GOOD.replace(line, fourteen))}
