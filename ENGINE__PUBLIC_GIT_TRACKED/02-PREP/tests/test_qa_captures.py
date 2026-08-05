"""Tests for qa_captures.py — the permanent capture acceptance gate.

Every negative fixture is a SYNTHETIC reproduction of a real defect class from the
live 55-job refresh run (2026-07-30):

  1. block fusion              — "…inherit one. Role Details:Employment Type…" glued
                                 (Ashby <br>/<li> shape) and "will:Growth" (LinkedIn
                                 <strong>/<span> shape)
  2. question-section leaks    — standard/demographic fields (work authorization,
                                 sponsorship, demographics) captured as "questions"
  3. choice text in locations  — a Yes/No office-attendance ANSWER leaking into
                                 Working Location(s) (Spring/Knit class)
  4. false absence claims      — header saying "Employer did not mention benefits/
                                 compensation" while the body plainly contains a
                                 benefits section or salary band (Playlist/Meta/
                                 Spring class)
  5. legacy markers            — `== NORMALIZED`, `[found]`, `(verbatim): ""`,
                                 `Re-Captured:` surviving from pre-migration output
  6. one-item bullet lists     — a single Base Salary band rendered as a bullet
                                 instead of inline (Help Scout class)
  7. ORIGINAL/LATEST breakage  — LATEST without ORIGINAL, or ORIGINAL dated after
                                 LATEST (the staged-shard rendering class)
  8. section/label/structure   — missing or misordered sections, wrong banner
                                 underlines, blank required fields, non-canonical
                                 filenames, bodies without JD structure

The positive fixture is the golden BetterUp capture: the gate must pass it clean.
The gate is wired into process_urls: a failing capture is quarantined into
Needs Review with status `needs-review`, never silently USABLE.
"""
import datetime
import re
from pathlib import Path

import pytest

import prep_common as pc
import qa_captures as qa

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GOLDEN = (FIXTURES / "golden_betterup_output.txt").read_text(encoding="utf-8")
GOLDEN_NAME = "betterup__principal-product-manager.txt"


def _valid_capture(**overrides):
    """A minimal contract-valid capture built by the real writer."""
    body = overrides.pop("body", None) or (
        "About the role\nResponsibilities include shipping product.\n"
        "Qualifications: 5+ years of experience.\n" + ("value delivered. " * 60))
    meta = {"title": "PM", "source": "greenhouse-boards-api", "structured_source": True,
            "compensation": "USD 200,000-250,000", "working_location": "Remote",
            "posting_id": "12345", "apply_url": "https://example.com/apply"}
    meta.update(overrides.pop("meta", {}))
    return pc.build_output_text("https://example.com/job/1", "PM", "Acme", body,
                                meta=meta, methods_tried=["ats"],
                                captured="2026-07-30T14:00:00+00:00", **overrides)


def test_the_golden_capture_passes_the_gate_clean():
    assert qa.validate_capture(GOLDEN, filename=GOLDEN_NAME) == []


def test_a_writer_produced_capture_passes_the_gate_clean():
    assert qa.validate_capture(_valid_capture(), filename="acme__pm.txt") == []


# ---- 1. block fusion --------------------------------------------------------
def test_fused_text_shapes_fail():
    fused = GOLDEN.replace(
        "The Opportunity",
        "…rather than inherit one. Role Details:Employment Type: Full Time, Exempt")
    problems = qa.validate_capture(fused, filename=GOLDEN_NAME)
    assert any("fused" in p for p in problems)
    linkedin = GOLDEN.replace("The Opportunity", "You will:Growth Systems & Ownership")
    assert any("fused" in p or "will:Growth" in p
               for p in qa.validate_capture(linkedin, filename=GOLDEN_NAME))


def test_urls_do_not_trip_the_fusion_guard():
    with_url = _valid_capture(body=(
        "About the role\nResponsibilities include shipping product.\n"
        "Apply at https://Example.com/jobs and see mailto:Careers@example.com.\n"
        + ("value delivered. " * 60)))
    assert not any("fused" in p
                   for p in qa.validate_capture(with_url, filename="acme__pm.txt"))


# ---- 2. question-section leaks ----------------------------------------------
@pytest.mark.parametrize("leak", [
    "1. Are you legally authorized to work in the United States? [Required]",
    "1. Will you now or in the future require visa sponsorship? [Required]",
    "2. Gender [Optional]",
    "1. First Name [Required]",
    "3. How did you hear about us? [Optional]",
])
def test_standard_and_demographic_fields_fail_the_questions_check(leak):
    text = _valid_capture().replace("None Found.", leak)
    problems = qa.validate_capture(text, filename="acme__pm.txt")
    assert any("standard/demographic" in p for p in problems), leak


def test_thoughtful_questions_pass():
    text = _valid_capture().replace(
        "None Found.",
        "1. How does our mission resonate with you? [Required]\n"
        '   [Context: 2-3 sentences is plenty.]\n'
        "2. Which office are you closest to? [Optional]\n"
        '   [Options: "NYC" / "SF"]')
    assert qa.validate_capture(text, filename="acme__pm.txt") == []


def test_off_grammar_question_lines_fail():
    text = _valid_capture().replace("None Found.", "1. [LongText, required] \"Old grammar?\"")
    assert any("off-grammar" in p
               for p in qa.validate_capture(text, filename="acme__pm.txt"))


# ---- 3. choice text in location fields --------------------------------------
def test_yes_no_text_in_a_location_field_fails():
    text = _valid_capture().replace("Working Location(s): Remote",
                                    "Working Location(s): Yes")
    assert any("application-choice text" in p
               for p in qa.validate_capture(text, filename="acme__pm.txt"))
    text2 = _valid_capture().replace("Office Expectation: Not Specified",
                                     "Office Expectation: Yes / No")
    assert any("application-choice text" in p
               for p in qa.validate_capture(text2, filename="acme__pm.txt"))


def test_a_stated_cadence_and_not_specified_pass_the_office_check():
    ok = _valid_capture().replace("Office Expectation: Not Specified",
                                  "Office Expectation: 3 Days Per Week, Tuesday–Thursday")
    assert qa.validate_capture(ok, filename="acme__pm.txt") == []
    prose = _valid_capture().replace("Office Expectation: Not Specified",
                                     "Office Expectation: in the office")
    assert any("not a stated cadence" in p
               for p in qa.validate_capture(prose, filename="acme__pm.txt"))


# ---- 4. false absence claims -------------------------------------------------
def test_did_not_mention_benefits_with_a_benefits_section_in_the_body_fails():
    body = ("About the role\nResponsibilities include shipping product.\n"
            "Benefits:\n- Medical, dental, and vision insurance\n- Flexible PTO\n"
            + ("value delivered. " * 60))
    text = _valid_capture(body=body)
    # Force the false claim (the real writer mines the section; the gate must still
    # catch a writer regression independently).
    text = re.sub(r"(?m)^Benefits: .*$", "Benefits: Employer did not mention benefits.", text)
    assert any("false absence" in p and "benefits" in p
               for p in qa.validate_capture(text, filename="acme__pm.txt"))


def test_did_not_mention_compensation_with_a_salary_band_in_the_body_fails():
    body = ("About the role\nResponsibilities include shipping product.\n"
            "The base salary range for this role is $150,000 - $180,000 annually.\n"
            + ("value delivered. " * 60))
    text = _valid_capture(body=body)
    text = re.sub(r"(?m)^Base Salary: .*$",
                  "Base Salary: Employer did not mention compensation.", text)
    assert any("false absence" in p and "compensation" in p
               for p in qa.validate_capture(text, filename="acme__pm.txt"))


def test_an_honest_absence_with_a_silent_body_passes():
    text = _valid_capture(meta={"compensation": None, "comp_expected": False})
    problems = [p for p in qa.validate_capture(text, filename="acme__pm.txt")
                if "false absence" in p]
    assert problems == []


# ---- 5. legacy markers --------------------------------------------------------
@pytest.mark.parametrize("marker", [
    "== NORMALIZED (for vetting) ==", "[found]", '(verbatim): ""', "Re-Captured:",
    "== APPLICATION QUESTIONS ==",
])
def test_legacy_markers_fail(marker):
    text = _valid_capture() + f"\n{marker}\n"
    assert any("legacy marker" in p
               for p in qa.validate_capture(text, filename="acme__pm.txt")), marker


# ---- 6. compensation structure -------------------------------------------------
def test_a_one_item_bullet_list_fails_and_inline_passes():
    inline = _valid_capture()
    assert "Base Salary: $200-250K" in inline
    assert qa.validate_capture(inline, filename="acme__pm.txt") == []
    bulleted = inline.replace("Base Salary: $200-250K", "Base Salary:\n- $200-250K")
    assert any("SINGLE band" in p
               for p in qa.validate_capture(bulleted, filename="acme__pm.txt"))
    multi = inline.replace("Base Salary: $200-250K",
                           "Base Salary:\n- Zone A: $200-250K\n- Zone B: $180-225K")
    assert qa.validate_capture(multi, filename="acme__pm.txt") == []


# ---- 7. ORIGINAL / LATEST sanity ------------------------------------------------
def test_latest_without_original_fails():
    text = _valid_capture().replace("ORIGINAL CAPTURE DETAILS\n------------------------",
                                    "LATEST CAPTURE DETAILS\n----------------------")
    assert any("without ORIGINAL" in p
               for p in qa.validate_capture(text, filename="acme__pm.txt"))


def test_original_dated_after_latest_fails(tmp_path):
    src = tmp_path / "3 - Source Material" / "All Job Posts (full text)"
    src.mkdir(parents=True)
    url = "https://boards.greenhouse.io/acme/jobs/123456"
    body = ("About the role\nResponsibilities include shipping product.\n"
            + ("value delivered. " * 60))

    def fetch(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": body,
                "method": "ats", "error": None,
                "meta": {"title": "PM", "source": "greenhouse-boards-api",
                         "structured_source": True, "compensation": "USD 200,000",
                         "working_location": "Remote"}, "questions": []}

    pc.process_urls([url], src, fetch, registry_path=tmp_path / "reg.json")
    m2 = pc.process_urls([url], src, fetch, force=True, registry_path=tmp_path / "reg.json")
    good = (src / Path(m2["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    assert qa.validate_capture(good, filename="acme__pm.txt") == []
    # Swap the two Captured At lines to fabricate the inversion.
    dates = re.findall(r"^Captured At: (.*)$", good, re.M)
    if dates[0] != dates[1]:
        swapped = good.replace(f"Captured At: {dates[0]}", "\x00", 1)
        swapped = swapped.replace(f"Captured At: {dates[1]}", f"Captured At: {dates[0]}", 1)
        swapped = swapped.replace("\x00", f"Captured At: {dates[1]}", 1)
        assert any("immutable and earliest" in p
                   for p in qa.validate_capture(swapped, filename="acme__pm.txt"))
    else:
        # Both stamps are the fixture's run time, so fabricate the inversion by pushing ORIGINAL
        # into the FUTURE relative to that run time. Derive it — a hardcoded date is a time bomb:
        # this line used to read "July 31, 2026 at 5:00 PM ET", which stopped being later than the
        # fixture's own timestamp once the clock passed it, and the test silently stopped testing
        # anything (it failed on 8/4/26). Never pin a "later than now" date to a literal.
        later = datetime.datetime.now() + datetime.timedelta(days=365)
        stamp = later.strftime("%B %-d, %Y at %-I:%M %p ET")
        inverted = good.replace(f"Captured At: {dates[0]}", f"Captured At: {stamp}", 1)
        assert any("immutable and earliest" in p
                   for p in qa.validate_capture(inverted, filename="acme__pm.txt"))


# ---- 8. sections / labels / structure --------------------------------------------
def test_missing_and_misordered_sections_fail():
    missing = _valid_capture().replace("WORK DETAILS\n============\n", "")
    assert any("missing" in p and "WORK DETAILS" in p
               for p in qa.validate_capture(missing, filename="acme__pm.txt"))


def test_wrong_banner_underline_fails():
    text = _valid_capture().replace("COMPENSATION\n============",
                                    "COMPENSATION\n=====")
    assert any("underline" in p for p in qa.validate_capture(text, filename="acme__pm.txt"))


def test_blank_required_fields_fail():
    text = _valid_capture().replace("Job Posted At: Unknown", "Job Posted At:")
    assert any("blank" in p and "Job Posted At" in p
               for p in qa.validate_capture(text, filename="acme__pm.txt"))


@pytest.mark.parametrize("name,ok", [
    ("acme__senior-pm.txt", True),
    ("help-scout__lead-principal-product-manager-resolve.txt", True),
    ("acme__senior-pm-greenhouse.txt", True),        # collision suffix
    ("Acme__Senior PM.txt", False),                  # case + spaces
    ("acme-senior-pm.txt", False),                   # no double-underscore
    ("golden_betterup_output.txt", False),
])
def test_filename_shapes(name, ok):
    problems = qa.validate_capture(_valid_capture(), filename=name)
    assert (not any("filename" in p for p in problems)) is ok, name


def test_a_body_without_jd_structure_fails():
    text = _valid_capture(body="nav chrome " * 100)
    assert any("no recognizable job-description structure" in p
               for p in qa.validate_capture(text, filename="acme__pm.txt"))


# ---- wiring: the gate runs inside process_urls ------------------------------------
def test_process_urls_quarantines_a_gate_failing_capture(tmp_path, monkeypatch):
    """A capture that would ship broken must land in Needs Review with status
    needs-review and its problems in the notes — never silently usable."""
    src = tmp_path / "3 - Source Material" / "All Job Posts (full text)"
    src.mkdir(parents=True)
    # Simulate a writer regression by making the fetched body carry a fused shape
    # the writer would pass through verbatim.
    body = ("About the role\nResponsibilities include shipping product.\n"
            "…rather than inherit one. Role Details:Employment Type: Full Time\n"
            + ("value delivered. " * 60))

    def fetch(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": body,
                "method": "ats", "error": None,
                "meta": {"title": "PM", "source": "greenhouse-boards-api",
                         "structured_source": True, "compensation": "USD 200,000",
                         "working_location": "Remote"}, "questions": []}

    manifest = pc.process_urls(["https://example.com/job/1"], src, fetch,
                               registry_path=tmp_path / "reg.json")
    entry = manifest["entries"][0]
    assert entry["status"] == pc.NEEDS_REVIEW
    assert entry["output_path"] is None
    assert "failed the capture QA gate" in entry["notes"]
    assert "fused" in entry["notes"]
    quarantined = tmp_path / "3 - Source Material" / "Needs Review"
    assert any(quarantined.iterdir())
    assert not any(src.iterdir())          # nothing joined the batch as usable
    assert manifest["counts"][pc.NEEDS_REVIEW] == 1
    assert manifest["counts"][pc.USABLE] == 0


def test_process_urls_passes_a_clean_capture_through_the_gate(tmp_path):
    src = tmp_path / "3 - Source Material" / "All Job Posts (full text)"
    src.mkdir(parents=True)
    body = ("About the role\nResponsibilities include shipping product.\n"
            + ("value delivered. " * 60))

    def fetch(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": body,
                "method": "ats", "error": None,
                "meta": {"title": "PM", "source": "greenhouse-boards-api",
                         "structured_source": True, "compensation": "USD 200,000",
                         "working_location": "Remote"}, "questions": []}

    manifest = pc.process_urls(["https://example.com/job/1"], src, fetch,
                               registry_path=tmp_path / "reg.json")
    assert manifest["entries"][0]["status"] == pc.USABLE


# ---- CLI ----------------------------------------------------------------------------
def test_cli_reports_per_file_and_exits_nonzero_on_failure(tmp_path):
    good = tmp_path / "acme__pm.txt"
    good.write_text(_valid_capture(), encoding="utf-8")
    bad = tmp_path / "broken__pm.txt"
    bad.write_text(_valid_capture() + "\n== NORMALIZED ==\n", encoding="utf-8")
    msgs: list = []
    rc = qa.run([tmp_path], out=msgs.append)
    assert rc == 1
    joined = "\n".join(msgs)
    assert "✓ acme__pm.txt" in joined
    assert "✗ broken__pm.txt" in joined
    assert "legacy marker" in joined
    assert "1 passed, 1 failed of 2." in joined
    bad.unlink()
    assert qa.run([tmp_path], out=msgs.append) == 0


# ---- Gate precision (Tranche 2): the Ordergroove false positive -----------------
def test_the_ordergroove_shape_is_a_must_pass():
    """A capture that HONESTLY reports base as not broken out, while the body's only
    figure is a total-comp (base + bonus) statement and the header's Additional
    Compensation explains exactly that, must PASS. A permanent gate that cries wolf
    gets ignored — precision matters as much as recall."""
    body = ("About the role\nResponsibilities include shipping product.\n"
            "The total compensation range (base + annual bonus) for this position "
            "is starting at $209,000.\n" + ("value delivered. " * 60))
    text = _valid_capture(body=body, meta={"compensation": None, "comp_expected": False})
    text = re.sub(r"(?m)^Base Salary: .*$",
                  "Base Salary: Employer did not mention compensation.", text)
    text = re.sub(r"(?m)^Additional Compensation: .*$",
                  "Additional Compensation: Total compensation (base + annual bonus) "
                  "starting at $209,000; base is not broken out.", text)
    problems = qa.validate_capture(text, filename="ordergroove__group-product-manager.txt")
    assert not any("false absence" in p for p in problems), problems


def test_total_comp_context_alone_suppresses_the_false_absence_check():
    """(a): an OTE / base+bonus figure is not a base band even with no Additional
    Compensation accounting."""
    for phrase in ("OTE for this role is $200,000 - $260,000.",
                   "On-target earnings of $250,000.",
                   "Total cash compensation: $209,000 - $240,000."):
        body = ("About the role\nResponsibilities include shipping product.\n"
                f"{phrase}\n" + ("value delivered. " * 60))
        text = _valid_capture(body=body, meta={"compensation": None, "comp_expected": False})
        text = re.sub(r"(?m)^Base Salary: .*$",
                      "Base Salary: Employer did not mention compensation.", text)
        problems = qa.validate_capture(text, filename="acme__pm.txt")
        assert not any("false absence" in p for p in problems), phrase


def test_the_header_accounting_for_the_figure_suppresses_the_check():
    """(b): even a plain figure is fine when Additional Compensation already carries it."""
    body = ("About the role\nResponsibilities include shipping product.\n"
            "Compensation for this position is $209,000 - $240,000.\n"
            + ("value delivered. " * 60))
    text = _valid_capture(body=body, meta={"compensation": None, "comp_expected": False})
    text = re.sub(r"(?m)^Base Salary: .*$",
                  "Base Salary: Employer did not mention compensation.", text)
    text = re.sub(r"(?m)^Additional Compensation: .*$",
                  "Additional Compensation: Package of $209,000 - $240,000 including "
                  "bonus; base not broken out.", text)
    problems = qa.validate_capture(text, filename="acme__pm.txt")
    assert not any("false absence" in p for p in problems)


def test_a_genuine_base_band_still_fails_the_false_absence_check():
    """Recall preserved: a REAL base band with a did-not-mention header still fails
    (the Playlist/Meta/Spring class the check exists for)."""
    body = ("About the role\nResponsibilities include shipping product.\n"
            "The base salary range for this role is $150,000 - $180,000 annually.\n"
            + ("value delivered. " * 60))
    text = _valid_capture(body=body)
    text = re.sub(r"(?m)^Base Salary: .*$",
                  "Base Salary: Employer did not mention compensation.", text)
    assert any("false absence" in p and "compensation" in p
               for p in qa.validate_capture(text, filename="acme__pm.txt"))
