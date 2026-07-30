"""Tests for the Application Question Drafts scaffolding (B11).

The tailoring agent appends `## Application Question Drafts` to the tailored-resume
output. The SKELETON is generated mechanically by question_drafts.py from the
capture — exact question text preserved, class-specific drafting instruction per
question, `None Found` when the capture holds no questions — so the agent fills in
answers under headings it cannot re-word, re-order, or drop. The agent-spec text
that mandates all of this is pinned here too.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "ENGINE__PUBLIC_GIT_TRACKED" / "04-TAILOR"))

import question_drafts as qd  # noqa: E402

import prep_common as pc  # noqa: E402

_SYNTH_BODY = ("About the role\nResponsibilities include shipping product.\n"
               + ("value delivered. " * 60))


def _capture_with(questions):
    return pc.build_output_text(
        "https://example.com/job/1", "PM", "Acme", _SYNTH_BODY,
        meta={"title": "PM", "structured_source": True,
              "compensation": "USD 200,000", "working_location": "Remote"},
        questions=questions, methods_tried=["ats"])


_SUBSTANTIVE_Q = {"label": "How does our mission resonate with you, and what draws "
                           "you to this role?",
                  "type": "textarea", "required": True, "name": "q1", "names": ["q1"],
                  "options": []}
_LOGISTICAL_Q = {"label": "I understand this role requires attending an office at "
                          "least 2 days per week. Which office are you closest to?",
                 "type": "select", "required": True, "name": "q2", "names": ["q2"],
                 "options": ["San Francisco Bay Area", "New York City"]}


def test_substantive_question_gets_a_draft_slot_with_the_exact_text():
    out = qd.drafts_skeleton(_capture_with([_SUBSTANTIVE_Q]))
    assert out.startswith("## Application Question Drafts\n")
    assert f"### Q1: {_SUBSTANTIVE_Q['label']} [Required]" in out
    assert "substantive — draft ONE concise answer" in out
    assert "Never invent experience or facts" in out
    assert "(draft here)" in out


def test_purely_logistical_question_gets_guidance_not_an_essay():
    out = qd.drafts_skeleton(_capture_with([_LOGISTICAL_Q]))
    assert f"### Q1: {_LOGISTICAL_Q['label']} [Required]" in out
    assert "do NOT draft an essay" in out
    assert "state exactly what the candidate must confirm" in out
    # The options context rides along as quoted context, verbatim.
    assert '> [Options: "San Francisco Bay Area" / "New York City"]' in out


def test_unknown_facts_rule_is_in_the_logistical_stub():
    out = qd.drafts_skeleton(_capture_with([_LOGISTICAL_Q])).replace("\n", " ")
    assert "needs confirming rather than guessing" in out


def test_multiple_questions_keep_order_and_numbering():
    out = qd.drafts_skeleton(_capture_with([_SUBSTANTIVE_Q, _LOGISTICAL_Q]))
    i1 = out.index("### Q1:")
    i2 = out.index("### Q2:")
    assert i1 < i2
    assert _SUBSTANTIVE_Q["label"] in out.split("### Q2:")[0]
    assert _LOGISTICAL_Q["label"] in out.split("### Q2:")[1]


def test_no_question_job_reads_none_found():
    out = qd.drafts_skeleton(_capture_with([]))
    assert out == "## Application Question Drafts\n\nNone Found\n"


def test_an_excluded_standard_field_is_never_answered():
    """The prep filter keeps standard fields out of captures; if one ever slipped
    through, the skeleton refuses to draft for it rather than answering."""
    capture = _capture_with([_SUBSTANTIVE_Q])
    capture = capture.replace(
        "APPLICATION QUESTIONS WORTH PREPARING\n=====================================\n",
        "APPLICATION QUESTIONS WORTH PREPARING\n=====================================\n"
        "1. Are you legally authorized to work in the United States? [Required]\n")
    out = qd.drafts_skeleton(capture)
    auth_block = out.split("### Q1:")[1].split("### Q")[0]
    assert "standard field — no draft" in auth_block
    assert "(draft here)" not in auth_block.split("*(")[1].split(")*")[0]


def test_the_skeleton_round_trips_the_capture_grammar():
    """parse_capture_questions reads exactly what the writer wrote — labels,
    required flags, and context lines, in order."""
    qs = qd.parse_capture_questions(_capture_with([_SUBSTANTIVE_Q, _LOGISTICAL_Q]))
    assert [q["label"] for q in qs] == [_SUBSTANTIVE_Q["label"], _LOGISTICAL_Q["label"]]
    assert qs[0]["required"] is True
    assert qs[1]["context"] == ['[Options: "San Francisco Bay Area" / "New York City"]',
                                "[Office Expectation: At Least 2 Days Per Week]"]


def test_the_cli_prints_the_skeleton(tmp_path):
    import subprocess
    cap = tmp_path / "acme__pm.txt"
    cap.write_text(_capture_with([_SUBSTANTIVE_Q]), encoding="utf-8")
    res = subprocess.run(
        [sys.executable, str(REPO / "ENGINE__PUBLIC_GIT_TRACKED" / "04-TAILOR"
                             / "question_drafts.py"), str(cap)],
        capture_output=True, text=True, check=True)
    assert res.stdout.startswith("## Application Question Drafts")
    assert _SUBSTANTIVE_Q["label"] in res.stdout


def test_the_agent_spec_mandates_the_derived_skeleton_and_the_rules():
    """The drafts-section format is spec-owned, not prompt-improvised: pin the
    spec text that mandates it."""
    spec = (REPO / "ENGINE__PUBLIC_GIT_TRACKED" / "04-TAILOR"
            / "00-job_application_agent.md").read_text(encoding="utf-8")
    for required in ("## Application Question Drafts",
                     "question_drafts.py",
                     "never re-word, re-order, or drop",
                     "Never invent experience or facts",
                     "do NOT invoke the cover-letter eval pipeline",
                     "state exactly what the candidate must confirm",
                     "None Found",
                     "no personal answer text lives in this spec"):
        assert required in spec, required
    agent = (REPO / ".claude" / "agents" / "job-applier.md").read_text(encoding="utf-8")
    for required in ("Application Question Drafts", "question_drafts.py",
                     "never invent facts"):
        assert required in agent, required
    # Fully generic: no personal answer content in the spec files.
    for text in (spec, agent):
        assert "Jessica" not in text
