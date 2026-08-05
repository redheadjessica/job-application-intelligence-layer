import re  # noqa: E402  (used by the HTML-structure tests)
import sys  # noqa: E402  (used by the CLI subprocess tests)
"""Regression suite for the comp/working-location completeness gate, provenance,
statuses, and the narrow application-question filter (Priorities 1-3).

All tests read saved fixtures from disk — no network. The 10 cases mirror the
plan's "Durable fixtures + regression tests" section.
"""
import json
from pathlib import Path

import pytest

import ats_fetchers as af
import prep_common as pc

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _ashby_result_with_questions():
    job = _load("ashby_betterup_principal_pm.json")
    res = af._ashby_job_to_result(job, "betterup")
    form = _load("ashby_betterup_apply_form.json")
    kept = af.filter_questions(af.normalize_ashby_apply_fields(form))
    res["questions"] = kept
    return res, kept


def _office_question(kept):
    return next(q for q in kept if af.question_provides_working_location(q))


# 1 --------------------------------------------------------------------------
def test_greenhouse_filter_keeps_exactly_three_essays():
    gh = _load("greenhouse_bloomerang_4705550005.json")
    res = af._greenhouse_job_to_result(gh, "bloomerang", "Bloomerang", "http://x")
    kept = res["questions"]
    assert len(kept) == 3, [q["label"] for q in kept]
    labels = " ".join(q["label"].lower() for q in kept)
    assert "customer outcome" in labels          # customer-outcome essay
    assert "ai tools" in labels or "modern ai" in labels  # AI-tools essay
    assert "apply to bloomerang" in labels       # motivation essay
    # Everything routine/identity/comp-expectation/work-auth dropped.
    for dropped in ("first name", "last name", "email", "phone", "resume",
                    "preferred", "linkedin", "requested compensation",
                    "authorized to work", "visa"):
        assert dropped not in labels
    # EEO/demographics/location probes never merged into `questions`.
    all_q = af.parse_greenhouse_questions(gh)
    assert all(q["name"] not in ("disability_status", "gender", "race") for q in all_q)


# 2 --------------------------------------------------------------------------
def test_ashby_comp_location_extraction_and_apply_filter():
    res, kept = _ashby_result_with_questions()
    # Per-zone tiers captured (not dropped like Lark's salary was).
    assert "Zone A" in res["compensation"] and "Zone B" in res["compensation"]
    assert "236" in res["compensation"] and "213" in res["compensation"]
    assert res["compensation_raw"]
    # Primary + secondary metros in the working location.
    for metro in ("Austin", "San Francisco", "New York", "Arlington"):
        assert metro in res["working_location"]
    assert res["workplace"] == "Hybrid"
    # Apply-form filter: mission essay + office-cadence kept; systemfields dropped.
    assert len(kept) == 2
    types = sorted(q["type"] for q in kept)
    assert types == ["select", "textarea"]
    for q in kept:
        assert not q["name"].startswith("_systemfield_")


# 3 --------------------------------------------------------------------------
def test_employer_comp_vs_candidate_expectations():
    expectations = {"label": "What are your compensation expectations?",
                    "type": "input_text", "name": "q1", "names": ["q1"], "options": []}
    # The expectations question is dropped and never satisfies employer comp.
    assert af.filter_questions([expectations]) == []
    assert af.question_provides_employer_comp(expectations) is False
    meta = {"title": "PM", "compensation": None, "comp_expected": True}
    fs = pc.assess_completeness(meta, "Responsibilities...", [expectations])
    assert fs["compensation"] != pc.FOUND
    # A real employer figure DOES satisfy comp.
    meta2 = {"title": "PM", "compensation": "USD 180,000–210,000", "comp_expected": True}
    fs2 = pc.assess_completeness(meta2, "Responsibilities...", [])
    assert fs2["compensation"] == pc.FOUND


# 4 --------------------------------------------------------------------------
def test_home_location_is_not_working_location():
    home = {"label": "Where do you currently live?", "type": "input_text",
            "name": "q2", "names": ["q2"], "options": []}
    assert af.filter_questions([home]) == []
    assert af.question_provides_working_location(home) is False
    meta = {"title": "PM", "working_location": None, "location": None, "location_expected": True}
    fs = pc.assess_completeness(meta, "Responsibilities...", [home])
    assert fs["working_location"] != pc.FOUND


# 5 --------------------------------------------------------------------------
def test_office_cadence_parses_to_metro_list_and_days():
    _res, kept = _ashby_result_with_questions()
    office = _office_question(kept)
    parsed = af.parse_office_cadence(office)
    assert parsed is not None
    assert parsed["metros"] == ["San Francisco Bay Area", "New York City",
                                "Austin, TX", "Washington, D.C."]
    assert "2 days per week" in parsed["cadence"]
    # It also satisfies working-location in the completeness assessment.
    meta = {"title": "PM", "working_location": None, "location": None, "location_expected": True}
    fs = pc.assess_completeness(meta, "Responsibilities...", [office])
    assert fs["working_location"] == pc.FOUND


# 6 --------------------------------------------------------------------------
def _batch_source(tmp_path):
    src = tmp_path / "3 - Source Material" / "All Job Posts (full text)"
    src.mkdir(parents=True)
    return src


_LONG_BODY = "About the role\nResponsibilities include shipping product. " + ("value delivered. " * 60)


def test_retry_cascade_advances_methods_on_missing_field(tmp_path):
    src = _batch_source(tmp_path)
    url = "https://example.com/job/1"

    def first(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": _LONG_BODY,
                "method": "requests", "error": None,
                "meta": {"title": "PM", "compensation": None, "comp_expected": True,
                         "working_location": "Remote", "location_expected": True},
                "questions": []}

    def fallback(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": _LONG_BODY,
                "method": "playwright", "error": None,
                "meta": {"title": "PM", "compensation": "USD 150,000–180,000",
                         "comp_expected": True, "working_location": "Remote",
                         "location_expected": True},
                "questions": []}

    manifest = pc.process_urls([url], src, first, fetch_fallback=fallback, fallback_label="playwright")
    entry = manifest["entries"][0]
    assert entry["status"] == pc.USABLE
    assert entry["methods_tried"] == ["requests", "playwright"]
    assert entry["field_status"]["compensation"] == pc.FOUND
    assert entry["has_compensation"] is True


# 7 --------------------------------------------------------------------------
def test_not_posted_vs_capture_failed():
    # Employer simply didn't publish comp (no ATS reason to expect it).
    fs_np = pc.assess_completeness(
        {"title": "PM", "compensation": None, "comp_expected": False,
         "working_location": "NYC", "location_expected": True}, "Responsibilities...", [])
    assert fs_np["compensation"] == pc.NOT_POSTED
    # Comp was expected from the ATS but came back empty -> capture failure.
    fs_cf = pc.assess_completeness(
        {"title": "PM", "compensation": None, "comp_expected": True,
         "working_location": "NYC", "location_expected": True}, "Responsibilities...", [])
    assert fs_cf["compensation"] == pc.CAPTURE_FAILED


# 8 --------------------------------------------------------------------------
def test_conflicting_sources_kept_and_flagged():
    meta = {"title": "PM",
            "compensation_sources": [("ashby", "USD 100,000–120,000"),
                                     ("jsonld", "USD 180,000–210,000")],
            "compensation": "USD 100,000–120,000", "comp_expected": True,
            "working_location": "NYC", "location_expected": True}
    fs = pc.assess_completeness(meta, "Responsibilities...", [])
    assert fs["compensation"] == pc.CONFLICTING
    assert fs["conflicts"] and "compensation" in fs["conflicts"][0]
    out = pc.build_output_text("http://x", "PM", "Acme", "Responsibilities...",
                               meta=meta, field_status=fs, methods_tried=["ats"])
    assert "Conflicting employer information:" in out
    assert "100,000" in out and "180,000" in out  # both readings preserved


# 9 --------------------------------------------------------------------------
def test_golden_output_is_stable():
    res, kept = _ashby_result_with_questions()
    fs = pc.assess_completeness(res, res["text"], kept)
    out = pc.build_output_text(
        "https://jobs.ashbyhq.com/betterup/fa0a5d05-39f9-47d5-9fc9-0a0540ff9018",
        res["title"], res["company"], res["text"], meta=res, questions=kept,
        field_status=fs, methods_tried=["ats", "playwright"],
        captured="2026-07-29T20:06:00+00:00")
    golden = (FIXTURES / "golden_betterup_output.txt").read_text(encoding="utf-8")
    assert out == golden


# 10 -------------------------------------------------------------------------
@pytest.mark.parametrize("label", [
    "Are you legally authorized to work in the United States?",
    "Will you now or in the future require visa sponsorship?",
    "Requested Compensation Range",
    "What are your salary expectations?",
    "Gender", "Race/Ethnicity", "Are you a protected veteran?",
    "Preferred First Name", "LinkedIn Profile URL", "Resume/CV",
])
def test_filter_excludes_routine_identity_and_workauth(label):
    q = {"label": label, "type": "input_text", "name": "question_x",
         "names": ["question_x"], "options": []}
    assert af.filter_questions([q]) == [], f"should have dropped: {label}"


def test_filter_keeps_a_compose_essay():
    q = {"label": "Describe the most impactful product decision you have made.",
         "type": "textarea", "name": "question_y", "names": ["question_y"], "options": []}
    assert len(af.filter_questions([q])) == 1


# 11 -------------------------------------------------------------------------
def test_generic_scrape_missing_fields_is_capture_failed_not_not_posted():
    """The Airbnb bug: a plain (non-structured) HTML scrape that finds no comp and
    no location must yield capture_failed (could-not-verify), NEVER not_posted —
    a plain scrape routinely misses fields the real ATS/render would catch."""
    meta = {"title": "Software Engineer", "source": "requests/html",
            "structured_source": False, "compensation": None, "comp_expected": False,
            "working_location": None, "location": None, "location_expected": False}
    fs = pc.assess_completeness(meta, "Responsibilities include shipping product.", [])
    assert fs["compensation"] == pc.CAPTURE_FAILED
    assert fs["working_location"] == pc.CAPTURE_FAILED
    assert fs["compensation"] != pc.NOT_POSTED
    assert fs["working_location"] != pc.NOT_POSTED
    # And capture_failed (not not_posted) is what arms the retry cascade.
    assert set(pc.missing_hard_fields(fs)) == {"compensation", "working_location"}


# 12 -------------------------------------------------------------------------
def test_structured_scrape_absent_field_is_not_posted():
    """Contrast with 11: when the source WAS structured (JSON-LD JobPosting / ATS),
    a genuinely absent field is honestly not_posted."""
    meta = {"title": "PM", "source": "requests/html", "structured_source": True,
            "compensation": None, "comp_expected": False,
            "working_location": "NYC", "location_expected": True}
    fs = pc.assess_completeness(meta, "Responsibilities...", [])
    assert fs["compensation"] == pc.NOT_POSTED
    assert pc.missing_hard_fields(fs) == []  # not_posted is not a retry trigger


# 13 -------------------------------------------------------------------------
def test_generic_capture_failure_triggers_retry(tmp_path):
    """End-to-end through process_urls: a generic scrape missing comp/location is
    capture_failed and DOES fire the fallback (a second method is attempted)."""
    src = _batch_source(tmp_path)
    url = "https://example.com/careers/some-role"  # no GH id -> no recovery detour

    def generic(u):
        return {"ok": True, "title": "Some Role", "company": "Example", "body": _LONG_BODY,
                "method": "requests", "error": None,
                "meta": {"title": "Some Role", "source": "requests/html",
                         "structured_source": False, "compensation": None,
                         "comp_expected": False, "working_location": None,
                         "location": None, "location_expected": False},
                "questions": []}

    calls = {"n": 0}

    def fallback(u):
        calls["n"] += 1
        # Render also can't find the missing fields (genuinely could-not-verify).
        return {"ok": True, "title": "Some Role", "company": "Example", "body": _LONG_BODY,
                "method": "playwright", "error": None,
                "meta": {"title": "Some Role", "source": "playwright/html",
                         "structured_source": False, "compensation": None,
                         "comp_expected": False, "working_location": None,
                         "location": None, "location_expected": False},
                "questions": []}

    manifest = pc.process_urls([url], src, generic, fetch_fallback=fallback,
                               fallback_label="playwright")
    entry = manifest["entries"][0]
    assert calls["n"] == 1, "the retry cascade must have attempted the fallback"
    assert entry["methods_tried"] == ["requests", "playwright"]
    assert entry["field_status"]["compensation"] == pc.CAPTURE_FAILED
    assert entry["field_status"]["working_location"] == pc.CAPTURE_FAILED
    assert entry["field_status"]["compensation"] != pc.NOT_POSTED


# 14 -------------------------------------------------------------------------
class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def _gh_job_fixture(title):
    return {
        "id": 8044715, "title": title,
        "content": "<p>We are hiring. Responsibilities include building payments "
                   "systems and shipping product to millions of guests.</p>",
        "location": {"name": "San Francisco, CA"},
        "offices": [{"name": "San Francisco"}],
        "pay_input_ranges": [{"min_cents": 23200000, "max_cents": 28200000,
                              "currency_type": "USD", "title": ""}],
        "absolute_url": "https://boards.greenhouse.io/airbnb/jobs/8044715",
        "questions": [],
    }


def _install_fake_gh(monkeypatch, job_for_airbnb):
    class FakeRequests:
        def get(self, url, **kw):
            if url.endswith("/boards/airbnb/jobs/8044715"):
                return _FakeResp(200, job_for_airbnb) if job_for_airbnb else _FakeResp(404, {})
            if url.endswith("/boards/airbnb"):
                return _FakeResp(200, {"name": "Airbnb"})
            return _FakeResp(404, {})
    monkeypatch.setattr(af, "requests", FakeRequests())
    af._GH_COMPANY_CACHE.clear()


def test_embedded_greenhouse_recovery_recovers_comp_and_location(monkeypatch):
    _install_fake_gh(monkeypatch, _gh_job_fixture("Staff Software Engineer, Payments"))
    res = af.recover_embedded_greenhouse(
        "https://careers.airbnb.com/positions/8044715/",
        page_title="Staff Software Engineer, Payments | Airbnb Careers", body="")
    assert res is not None
    assert "232" in res["compensation"] and "282" in res["compensation"]
    assert "San Francisco" in (res["working_location"] or "")
    assert res["company"] == "Airbnb"
    assert res.get("structured_source") is True
    # A structured source: recovered comp/location assess as FOUND.
    fs = pc.assess_completeness({**res, "method": "ats"}, res["text"], res["questions"])
    assert fs["compensation"] == pc.FOUND
    assert fs["working_location"] == pc.FOUND


def test_embedded_greenhouse_recovery_guards_wrong_board(monkeypatch):
    # The 'airbnb' board returns SOME job at that id, but its title is unrelated to
    # the page and its words aren't in the (empty) body -> must be discarded.
    _install_fake_gh(monkeypatch, _gh_job_fixture("Warehouse Forklift Operator"))
    res = af.recover_embedded_greenhouse(
        "https://careers.airbnb.com/positions/8044715/",
        page_title="Staff Software Engineer, Payments | Airbnb Careers", body="")
    assert res is None


def test_embedded_greenhouse_recovery_no_job_id_is_noop(monkeypatch):
    # No Greenhouse-style numeric id in the URL -> recovery bails without a network call.
    called = {"n": 0}

    class Boom:
        def get(self, *a, **k):
            called["n"] += 1
            raise AssertionError("should not hit the network")
    monkeypatch.setattr(af, "requests", Boom())
    assert af.recover_embedded_greenhouse("https://example.com/careers/role",
                                          page_title="Role") is None
    assert called["n"] == 0


# 15 -------------------------------------------------------------------------
def test_question_label_trailing_quote_not_doubled():
    """POLISH: a verbatim label carrying a stray wrapping double-quote must not
    render it (the Bloomerang question-2 bug, carried into the unquoted format)."""
    q = {"label": 'How are you using modern AI tools for accelerating delivery?"',
         "type": "textarea", "source_type": "LongText", "required": True,
         "name": "q", "names": ["q"], "options": []}
    out = pc.build_output_text("http://x", "PM", "Acme", "Responsibilities...",
                               questions=[q], methods_tried=["ats"])
    assert 'delivery?"' not in out
    assert "1. How are you using modern AI tools for accelerating delivery? [Required]" in out


# 16 -------------------------------------------------------------------------
# Ashby posting-api ALWAYS returns comp/location but NEVER returns questions, so a
# normal requests-first Ashby run is "complete" and no fallback fires — the
# thoughtful questions must be captured by an always-on apply-page render on the
# primary pass, merged into the API meta without losing comp/location.

def test_ashby_questions_always_rendered_even_when_api_complete(monkeypatch):
    pju = pytest.importorskip("prep_job_urls")
    job = _load("ashby_betterup_principal_pm.json")
    ats_res = af._ashby_job_to_result(job, "betterup")
    ats_res["questions"] = []  # posting-api carries none
    assert ats_res["compensation"] and ats_res["working_location"]  # API is "complete"
    monkeypatch.setattr(pju, "fetch_via_ats", lambda u, **k: dict(ats_res))

    form = _load("ashby_betterup_apply_form.json")
    kept = af.filter_questions(af.normalize_ashby_apply_fields(form))
    calls = {"n": 0}

    def renderer(u, apply_hint=None):
        calls["n"] += 1
        calls["apply_hint"] = apply_hint
        return kept

    out = pju.fetch_one(
        "https://jobs.ashbyhq.com/betterup/fa0a5d05-39f9-47d5-9fc9-0a0540ff9018",
        ashby_question_renderer=renderer)
    assert calls["n"] == 1, "the apply-page render must fire on the primary pass"
    # The ATS-provided apply URL must be handed to the renderer (canonical; also the
    # only way custom-domain Ashby jobs can be resolved to an apply page).
    assert calls["apply_hint"] == ats_res["apply_url"]
    assert out["questions"] == kept and len(kept) == 2
    assert out["meta"]["questions"] == kept
    # Rich comp/location from the posting-api are preserved (not lost / re-fetched).
    assert out["meta"]["compensation"] == ats_res["compensation"]
    assert "Austin" in out["meta"]["working_location"]


def test_ashby_render_failure_degrades_gracefully(monkeypatch):
    pju = pytest.importorskip("prep_job_urls")
    job = _load("ashby_betterup_principal_pm.json")
    ats_res = af._ashby_job_to_result(job, "betterup")
    ats_res["questions"] = []
    monkeypatch.setattr(pju, "fetch_via_ats", lambda u, **k: dict(ats_res))

    def boom(u):
        raise RuntimeError("Playwright not installed / render failed")

    out = pju.fetch_one("https://jobs.ashbyhq.com/betterup/abc",
                        ashby_question_renderer=boom)
    assert out["ok"] is True and out["questions"] == []  # never fails the fetch
    assert out["meta"]["compensation"] == ats_res["compensation"]


def test_ashby_render_only_for_ashby_hosts(monkeypatch):
    """The always-render is Ashby-only: a non-Ashby ATS never invokes it (no
    requests-first speed regression for other jobs)."""
    pju = pytest.importorskip("prep_job_urls")
    gh = _load("greenhouse_bloomerang_4705550005.json")
    gh_res = af._greenhouse_job_to_result(gh, "bloomerang", "Bloomerang", "http://x")
    gh_res["questions"] = []  # force the empty-questions branch so only host gates
    monkeypatch.setattr(pju, "fetch_via_ats", lambda u, **k: dict(gh_res))
    calls = {"n": 0}

    def renderer(u):
        calls["n"] += 1
        return [{"label": "should never be called"}]

    out = pju.fetch_one("https://boards.greenhouse.io/bloomerang/jobs/4705550005",
                        ashby_question_renderer=renderer)
    assert calls["n"] == 0
    assert out["questions"] == []


# 17 — prose-aware completeness -----------------------------------------------
# The completeness verdict must match what the vetting scorer reads (the JD body),
# so comp/location written into prose count as found — no false capture_failed.

def test_prose_compensation_found_when_no_structured_comp():
    body = ("About the role\nWe are hiring a Staff Engineer. The base salary range "
            "for this role is $174,000 - $290,000 depending on location. " + ("x " * 40))
    # Generic scrape (not structured), no structured comp figure.
    meta = {"title": "Staff Engineer", "source": "requests/html",
            "structured_source": False, "compensation": None, "comp_expected": False,
            "working_location": "Remote", "location_expected": True}
    fs = pc.assess_completeness(meta, body, [])
    assert fs["compensation"] == pc.FOUND
    assert fs.get("compensation_source") == "description"
    assert "174,000" in fs.get("compensation_prose", "")
    assert pc.missing_hard_fields(fs) == []  # no longer a false capture_failed
    # And the Base Salary bullets carry the prose figure (the employer's own value).
    out = pc.build_output_text("http://x", "Staff Engineer", "Acme", body,
                               meta=meta, field_status=fs, methods_tried=["requests"])
    assert "Base Salary:" in out and "174,000" in out
    assert "Could Not Verify." not in out.split("COMPENSATION")[1].split("Additional")[0]


def test_prose_compensation_variants():
    for line, needle in [
        ("Compensation: USD 232,000–282,000 per year", "232,000"),
        ("The pay range for this role is $110K–$180K.", "110K"),
        ("Salary: $95,000 to $130,000 annually", "95,000"),
        # Google-style: comma-less amounts, but currency-marked (was the miss).
        ("US: $240000 - $334000 (USD) + 25% bonus target + equity", "240000"),
    ]:
        assert pc._prose_compensation(line) and needle in pc._prose_compensation(line), line
    # Non-salary numeric ranges must NOT be read as pay.
    assert pc._prose_compensation("We have 20-50 employees across three offices.") is None
    assert pc._prose_compensation("Worked there 2019 - 2023 building teams.") is None


def test_total_comp_only_is_found_not_not_posted():
    # The "Ordergroove shape": pay published ONLY as total comp (base + bonus), no base
    # band. Must be FOUND (employer posted pay), not NOT_POSTED, so the Verification line
    # shows a real value and the scorer doesn't read "no comp."
    body = ("About the role\nWe help brands build subscription commerce. "
            "The total compensation range (base + annual bonus) for this role is "
            "starting at $209,000 + equity. " + ("x " * 40))
    meta = {"title": "Group PM", "source": "ashby", "structured_source": True,
            "compensation": None, "comp_expected": False,
            "working_location": "Remote", "location_expected": True}
    fs = pc.assess_completeness(meta, body, [])
    assert fs["compensation"] == pc.FOUND
    assert fs.get("compensation_source") == "total_comp"
    out = pc.build_output_text("http://x", "Group PM", "Acme", body,
                               meta=meta, field_status=fs, methods_tried=["ats"])
    comp_block = out.split("COMPENSATION")[1].split("APPLICATION QUESTIONS")[0]
    # The base line must NOT read as "no comp"; it points at Additional Compensation.
    assert "did not mention compensation" not in comp_block
    assert "Not broken out separately" in comp_block
    assert "209,000" in comp_block  # the published figure survives on the Additional line
    # And the Verification footer must not mark compensation as not-posted.
    assert pc.missing_hard_fields(fs) == []


def test_true_no_comp_still_not_posted():
    # Guard the fix doesn't over-fire: a structured source with genuinely no pay figure
    # (and no total-comp language) stays NOT_POSTED.
    body = ("About the role\nWe are hiring a Product Manager to own the roadmap. "
            "Join a mission-driven team. " + ("x " * 40))
    meta = {"title": "PM", "source": "ashby", "structured_source": True,
            "compensation": None, "comp_expected": False,
            "working_location": "Remote", "location_expected": True}
    fs = pc.assess_completeness(meta, body, [])
    assert fs["compensation"] == pc.NOT_POSTED


def test_prose_working_location_found_from_named_city():
    body = ("About the team\nThis position is based in Austin, TX and works with "
            "partners nationwide. " + ("y " * 40))
    meta = {"title": "PM", "source": "requests/html", "structured_source": False,
            "compensation": "USD 150,000", "working_location": None,
            "location": None, "location_expected": False}
    fs = pc.assess_completeness(meta, body, [])
    assert fs["working_location"] == pc.FOUND
    assert fs.get("working_location_source") == "description"
    assert "Austin, TX" in fs.get("working_location_prose", "")


def test_prose_working_location_remote_and_no_false_positive():
    remote = pc._prose_working_location("This is a fully remote role open to the US.")
    assert remote and "Remote" in remote
    # A structured source with genuinely no location and no prose stays not_posted.
    meta = {"title": "PM", "source": "requests/html", "structured_source": True,
            "compensation": "x", "working_location": None, "location": None}
    fs = pc.assess_completeness(meta, "Responsibilities include shipping product.", [])
    assert fs["working_location"] == pc.NOT_POSTED


# 18 — custom-domain ATS dispatch ---------------------------------------------

def test_custom_domain_ashby_jid_dispatches_to_ashby(monkeypatch):
    """lark.com/careers?ashby_jid=<uuid> -> Ashby, org guessed from the domain,
    matched by UUID against the board feed."""
    job = _load("ashby_betterup_principal_pm.json")
    uuid = str(job["id"])
    captured = {"org": None}

    def fake_board(org, timeout=20):
        captured["org"] = org
        return [job] if org == "lark" else []

    monkeypatch.setattr(af, "_ashby_board", fake_board)
    url = f"https://lark.com/careers/open-positions?ashby_jid={uuid}"
    res = af.fetch_via_ats(url)
    assert res is not None, "ashby_jid on a custom domain must route to Ashby"
    assert captured["org"] == "lark"
    assert res["compensation"] and res["working_location"]
    assert "custom-domain jid" in res["source"]


def test_custom_domain_ashby_jid_no_match_returns_none(monkeypatch):
    monkeypatch.setattr(af, "_ashby_board", lambda org, timeout=20: [])
    res = af.fetch_via_ats(
        "https://lark.com/careers?ashby_jid=4ccf1e87-0000-0000-0000-000000000000")
    assert res is None


def test_pinterest_gh_jid_board_token_derivation():
    """pinterestcareers.com must yield the real Greenhouse board token 'pinterest'
    (brand-suffix stripping), and gh_jid is read straight from the query."""
    url = "https://www.pinterestcareers.com/jobs/7300000/apply?gh_jid=8046820"
    tokens = af._gh_board_tokens_from_domain(url)
    assert "pinterest" in tokens
    assert af._embedded_gh_job_id(url, None) == "8046820"


def test_embedded_gh_recovery_routes_via_gh_jid(monkeypatch):
    """A gh_jid on a custom domain drives the embedded-Greenhouse recovery to the
    right board+id, gated by the title-match guard."""
    calls = {"urls": []}

    class FakeResp:
        def __init__(self, status, payload):
            self.status_code = status
            self._payload = payload

        def json(self):
            return self._payload

    job = _gh_job_fixture("Senior Software Engineer, Ads")

    class FakeRequests:
        def get(self, url, **kw):
            calls["urls"].append(url)
            if url.endswith("/boards/pinterest/jobs/8046820"):
                return FakeResp(200, job)
            if url.endswith("/boards/pinterest"):
                return FakeResp(200, {"name": "Pinterest"})
            return FakeResp(404, {})

    monkeypatch.setattr(af, "requests", FakeRequests())
    af._GH_COMPANY_CACHE.clear()
    res = af.recover_embedded_greenhouse(
        "https://www.pinterestcareers.com/jobs/7300000?gh_jid=8046820",
        page_title="Senior Software Engineer, Ads | Pinterest Careers", body="")
    assert res is not None
    assert res["company"] == "Pinterest"
    assert any("/boards/pinterest/jobs/8046820" in u for u in calls["urls"])


def test_embedded_gh_recovery_matches_via_url_slug_when_page_is_thin(monkeypatch):
    """Even when the fetched page is a thin shell (no useful title/body), the role
    slug in the URL path lets a correct board hit pass the guard."""
    class FakeResp:
        def __init__(self, status, payload):
            self.status_code = status
            self._payload = payload

        def json(self):
            return self._payload

    job = _gh_job_fixture("Sr. Product Manager, Core Saving Experience")

    class FakeRequests:
        def get(self, url, **kw):
            if url.endswith("/boards/pinterest/jobs/8046820"):
                return FakeResp(200, job)
            if url.endswith("/boards/pinterest"):
                return FakeResp(200, {"name": "Pinterest"})
            return FakeResp(404, {})

    monkeypatch.setattr(af, "requests", FakeRequests())
    af._GH_COMPANY_CACHE.clear()
    res = af.recover_embedded_greenhouse(
        "https://www.pinterestcareers.com/jobs/8046820/"
        "sr-product-manager-core-saving-experience/?gh_jid=8046820",
        page_title="Careers at Pinterest", body="")  # generic title, empty body
    assert res is not None and res["company"] == "Pinterest"


# 19 — location prose sanitizer (2026-07-29 completeness-audit regressions) --------
# The working-location prose fallback used to declare `found` on garbage: a plural
# nav label ("Locations"/"Office locations") leaked its trailing "s"; a city glued
# onto the previous line's trailing token across a newline ("Google Cloud\nAustin,
# TX"); and a marketing sentence/URL rode along after the real place. Each must now
# resolve to a clean location or None — never junk-marked-found.

@pytest.mark.parametrize("raw", [
    "Office locations", "Locations", "s", "location", "Careers", "Menu",
])
def test_sanitize_location_rejects_nav_label_leak(raw):
    assert pc._sanitize_location(raw) is None


@pytest.mark.parametrize("raw,expected", [
    ("Google Cloud\nAustin, TX", "Austin, TX"),            # division prefix + multiline
    ("Product\nMenlo Park, CA", "Menlo Park, CA"),
    ("San Francisco, CA, [Rippling has raised $1.4B+](https://x) from investors",
     "San Francisco, CA"),                                 # trailing marketing + URL
    ("New York, NY", "New York, NY"),
    ("London, UK", "London, UK"),                          # international City, Region
    ("Fully Remote", "Fully Remote"),
])
def test_sanitize_location_cleans_to_trustworthy_value(raw, expected):
    assert pc._sanitize_location(raw) == expected


def test_city_state_regex_does_not_span_newlines():
    # The inter-word separator must not cross a line break (the Google/Meta bug):
    # match the real city, never glue the previous line's trailing token onto it.
    m = pc._CITY_STATE_RE.search("Google Cloud\nAustin, TX")
    assert m and m.group(1) == "Austin" and m.group(2) == "TX"


def test_prose_working_location_nav_label_body_yields_none():
    # A page whose only location-ish text is a plural nav label must NOT be mined
    # into a bogus location (this produced working_location = "s" pre-fix).
    body = "Senior PM\nResponsibilities include shipping product.\nOffice locations\nApply"
    assert pc._prose_working_location(body) is None


def test_assess_completeness_no_false_found_on_nav_label():
    # End-to-end: a generic scrape whose body carries only a plural nav label must
    # report working_location capture_failed (retryable), NOT a bogus `found`.
    body = ("About the role\nResponsibilities include building product.\n"
            "Office locations\n" + ("x " * 40))
    meta = {"title": "PM", "source": "requests/html", "structured_source": False,
            "compensation": "USD 150,000", "working_location": None,
            "location": None, "location_expected": False}
    fs = pc.assess_completeness(meta, body, [])
    assert fs["working_location"] == pc.CAPTURE_FAILED
    assert not fs.get("working_location_prose")


# --------------------------------------------------------------------------- #
# Ashby apply-URL construction (REGRESSION 2026-07-29)
#
# The apply URL used to be built as `url.rstrip('/') + '/application'`, which
# broke silently for any job URL carrying a query string: `.../<id>?src=LinkedIn`
# became `.../<id>?src=LinkedIn/application`, the apply page never loaded, and
# question capture degraded to [] with no error. Every prior test used a CLEAN
# url, so the suite passed while real LinkedIn/job-board URLs (which nearly always
# carry ?src=/?departmentId=/?utm_source=) failed in production. These tests pin
# the query-string cases specifically.
# --------------------------------------------------------------------------- #
def _apply_url(url):
    import prep_job_urls_playwright as pjp
    return pjp.ashby_apply_url(url)


@pytest.mark.parametrize("raw,expected", [
    # clean url (the only case the original suite covered)
    ("https://jobs.ashbyhq.com/betterup/fa0a5d05",
     "https://jobs.ashbyhq.com/betterup/fa0a5d05/application"),
    # trailing slash
    ("https://jobs.ashbyhq.com/betterup/fa0a5d05/",
     "https://jobs.ashbyhq.com/betterup/fa0a5d05/application"),
    # THE BUG: single query param (LinkedIn src)
    ("https://jobs.ashbyhq.com/headway/82fd0412?src=LinkedIn",
     "https://jobs.ashbyhq.com/headway/82fd0412/application"),
    # THE BUG: multiple query params (departmentId + src)
    ("https://jobs.ashbyhq.com/betterup/f0a6faee?departmentId=988d779c&src=LinkedIn",
     "https://jobs.ashbyhq.com/betterup/f0a6faee/application"),
    # THE BUG: utm params, mixed case keys
    ("https://jobs.ashbyhq.com/grow-therapy/80716f86?utm_source=vgRZolJeYV&Source=LinkedIn",
     "https://jobs.ashbyhq.com/grow-therapy/80716f86/application"),
    # fragment as well as query
    ("https://jobs.ashbyhq.com/lark/4ccf1e87?x=1#top",
     "https://jobs.ashbyhq.com/lark/4ccf1e87/application"),
    # already an apply url — must not double-append
    ("https://jobs.ashbyhq.com/betterup/fa0a5d05/application",
     "https://jobs.ashbyhq.com/betterup/fa0a5d05/application"),
    # already an apply url WITH a query string
    ("https://jobs.ashbyhq.com/betterup/fa0a5d05/application?src=LinkedIn",
     "https://jobs.ashbyhq.com/betterup/fa0a5d05/application"),
])
def test_ashby_apply_url_strips_query_and_fragment(raw, expected):
    assert _apply_url(raw) == expected


def test_ashby_apply_url_never_puts_path_after_query():
    # The precise failure signature: '/application' must never appear after a '?'.
    for raw in [
        "https://jobs.ashbyhq.com/headway/82fd0412?src=LinkedIn",
        "https://jobs.ashbyhq.com/betterup/f0a6faee?departmentId=988d779c",
        "https://jobs.ashbyhq.com/grow-therapy/80716f86?utm_source=x&Source=LinkedIn",
    ]:
        out = _apply_url(raw)
        assert "?" not in out, f"query string must be dropped: {out}"
        assert out.endswith("/application")


# --------------------------------------------------------------------------- #
# Voluntary diversity-statement prompts must be KEPT (decided 2026-07-29)
#
# History: these were briefly EXCLUDED as self-identification. That was wrong for
# this system's purpose and the candidate reversed it. The distinction that matters
# is FORM, not topic: a gender/race DROPDOWN is a routine self-ID field (excluded),
# but a free-text prompt inviting you to write about your background requires
# genuinely sitting down and composing something — so it passes the
# "think and compose a response" keep-test. Do not re-add an exclusion for these.
# --------------------------------------------------------------------------- #
_DIVERSITY_PROMPTS = [
    ("optional free-text diversity statement",
     "We are invested in advancing the diversity of our teams by recruiting from "
     "underrepresented communities. If you believe you bring a diverse perspective "
     "based on your background, communities or experience, we invite you to share "
     "more here. This is completely optional."),
    ("underrepresented groups phrasing",
     "We recruit from underrepresented groups — tell us about your background."),
    ("diverse perspective phrasing",
     "Do you bring a diverse perspective you'd like to share?"),
]


@pytest.mark.parametrize("name,label", _DIVERSITY_PROMPTS)
def test_voluntary_diversity_statements_are_kept(name, label):
    # Free-text => compose-a-response => KEEP (see the note above).
    fields = [{"label": label, "type": "textarea", "required": False, "options": []}]
    kept = af.filter_questions(fields)
    assert len(kept) == 1, f"{name} must be KEPT (free-text, requires composition)"


def test_dropdown_style_self_id_fields_are_still_excluded():
    # The revert above must NOT weaken the routine self-ID exclusions: a gender/race
    # style SELECT is administrative, not a composed response.
    fields = [
        {"label": "Gender", "type": "select", "required": False,
         "options": [{"label": "Male"}, {"label": "Female"}, {"label": "Decline"}]},
        {"label": "Race / Ethnicity", "type": "select", "required": False,
         "options": [{"label": "Decline to self-identify"}]},
        {"label": "Veteran Status", "type": "select", "required": False, "options": []},
        {"label": "Disability Status", "type": "select", "required": False, "options": []},
    ]
    assert af.filter_questions(fields) == []


def test_question_about_building_for_diverse_users_is_kept():
    # A genuine job-material question that happens to mention diverse USERS is a
    # compose-a-response question and must SURVIVE.
    fields = [{
        "label": "How would you approach designing an onboarding flow that works for "
                 "a diverse set of users with very different needs?",
        "type": "textarea", "required": True, "options": [],
    }]
    kept = af.filter_questions(fields)
    assert len(kept) == 1


# --------------------------------------------------------------------------- #
# Multi-ATS question capture (2026-07-29)
#
# Before this, only Greenhouse (boards API) and Ashby (rendered apply page) could
# produce application questions; every other source hardcoded []. These tests pin
# the three new fetchers (Rippling / Workable / Workday), Lever question capture,
# and the generalized apply-page renderer. All fixtures are REAL saved API
# payloads — no test here touches the network.
# --------------------------------------------------------------------------- #

RIPPLING_WITH_QUESTIONS = "rippling_workplace_coordinator.json"
RIPPLING_NO_EXTRA_QUESTIONS = "rippling_product_lead_no_extra_questions.json"
WORKABLE_JOB = "workable_feeld_cpo.json"
WORKDAY_JOB = "workday_wonder_assoc_dir_product.json"
LEVER_JOB = "lever_findem_posting.json"


def _rippling(name):
    return af._rippling_job_to_result(_load(name), "rippling")


# Rippling -------------------------------------------------------------------
def test_rippling_parses_title_company_comp_and_all_work_locations():
    res = _rippling(RIPPLING_NO_EXTRA_QUESTIONS)
    assert res["title"] == "Product Lead, Talent Products"
    # companyName gives the clean name; never the board slug guess.
    assert res["company"] == "Rippling"
    # Pay zone + both range ends, from payRangeDetails.
    assert "US Tier 1" in res["compensation"]
    assert "174,000" in res["compensation"] and "290,000" in res["compensation"]
    assert res["compensation_raw"] == res["compensation"]
    # EVERY work location is kept, not just the first.
    assert res["location"] == "San Francisco, CA"
    assert "San Francisco, CA" in res["working_location"]
    assert "New York, NY" in res["working_location"]
    # Rippling inverts label/id: `id` holds the human string.
    assert res["employment_type"] == "Salaried, full-time"
    assert res["source"] == "rippling-ats-api"
    assert res["structured_source"] is True
    assert res["posting_id"] == "0889e2ac-a30c-43b7-8c8c-5312264416db"
    assert res["apply_url"].startswith("https://ats.rippling.com/rippling/jobs/")
    # Both description blocks (company blurb + role) land in the body.
    assert len(res["text"]) > 2000


def test_rippling_null_additional_questions_yields_zero_kept_without_crashing():
    """`activeJobApplication.additionalQuestions` is None whenever the employer
    added no custom questions — the common case. It must parse to zero KEPT
    questions rather than raising."""
    job = _load(RIPPLING_NO_EXTRA_QUESTIONS)
    assert job["activeJobApplication"]["additionalQuestions"] is None
    parsed = af.parse_rippling_questions(job)
    assert parsed, "the routine basicQuestions must still be parsed"
    assert _rippling(RIPPLING_NO_EXTRA_QUESTIONS)["questions"] == []


def test_rippling_keeps_essay_and_office_cadence_and_drops_routine_fields():
    res = _rippling(RIPPLING_WITH_QUESTIONS)
    kept = res["questions"]
    assert len(kept) == 2, [q["label"] for q in kept]
    essay = next(q for q in kept if q["type"] == "textarea")
    assert "competing priorities" in essay["label"]
    assert essay["required"] is True
    office = _office_question(kept)
    assert "5 days a week" in office["label"]
    assert office["options"] == ["Yes", "No"]
    # The routine basicQuestions set is dropped by the SHARED filter, by name.
    labels = " ".join(q["label"].lower() for q in kept)
    for dropped in ("first name", "last name", "email", "pronouns", "phone",
                    "resume", "cover letter", "linkedin", "current company",
                    "location (city only)"):
        assert dropped not in labels


def test_rippling_office_cadence_question_is_recognized_as_working_location():
    office = next(q for q in _rippling(RIPPLING_WITH_QUESTIONS)["questions"]
                  if q["type"] == "select")
    assert af.question_provides_working_location(office)
    parsed = af.parse_office_cadence(office)
    assert parsed and parsed["cadence"] == "5 days a week"


def test_rippling_hourly_comp_keeps_its_frequency():
    """A non-annual pay frequency must survive: $27–44 an HOUR read as a salary
    band would be a catastrophic mis-score."""
    comp = _rippling(RIPPLING_WITH_QUESTIONS)["compensation"]
    assert comp.endswith("/hour"), comp
    assert "27" in comp and "44" in comp


def test_rippling_long_answer_is_a_compose_type_despite_text_datatype():
    """Rippling's `dataType` is an unreliable compose signal (a LONG_ANSWER essay
    can carry dataType "Text"); `questionType` is the one to trust."""
    raw = next(q for qs in _load(RIPPLING_WITH_QUESTIONS)["activeJobApplication"]
               ["additionalQuestions"] for q in qs["form"]["questions"]
               if q["questionType"] == "LONG_ANSWER")
    assert raw["dataType"] == "Text"  # the trap
    parsed = next(q for q in af.parse_rippling_questions(_load(RIPPLING_WITH_QUESTIONS))
                  if q["label"] == raw["title"])
    assert parsed["type"] == "textarea"


@pytest.mark.parametrize("url,expected", [
    ("https://ats.rippling.com/rippling/jobs/0889e2ac-a30c-43b7-8c8c-5312264416db",
     ("rippling", "0889e2ac-a30c-43b7-8c8c-5312264416db")),
    # a jobSite query param must not confuse the id parse
    ("https://ats.rippling.com/acme-co/jobs/0889E2AC-A30C-43B7-8C8C-5312264416DB?jobSite=LinkedIn",
     ("acme-co", "0889e2ac-a30c-43b7-8c8c-5312264416db")),
    ("https://ats.rippling.com/acme-co", ("acme-co", None)),
])
def test_rippling_url_id_parsing(url, expected):
    assert af._rippling_ids(url) == expected


# Workable -------------------------------------------------------------------
def _workable():
    return af._workable_job_to_result(_load(WORKABLE_JOB), "feeldco", "Feeld")


def test_workable_parses_title_location_workplace_and_employment_type():
    res = _workable()
    assert res["title"] == "Chief Product Officer"
    # The account API's display name, not the raw subdomain ("feeldco").
    assert res["company"] == "Feeld"
    assert res["location"] == "New York, New York"
    for metro in ("New York", "Los Angeles", "London"):
        assert metro in res["working_location"]
    assert res["workplace"] == "Remote" and res["remote"] is True
    assert res["employment_type"] == "Full-time"
    assert res["source"] == "workable-api" and res["structured_source"] is True
    assert res["posting_id"] == "AA731B2DD7"
    assert res["apply_url"] == "https://apply.workable.com/feeldco/j/AA731B2DD7/"
    # description + requirements + benefits all folded into the body.
    assert len(res["text"]) > 5000


def test_workable_api_carries_no_comp_and_no_questions():
    """Workable's job API has no questions and usually a null salary. Those must
    come back empty (so the caller renders the apply page / reports not-posted),
    never invented."""
    res = _workable()
    assert res["compensation"] is None and res["compensation_raw"] is None
    assert res["questions"] == []


@pytest.mark.parametrize("url,expected", [
    ("https://apply.workable.com/feeldco/j/AA731B2DD7", ("feeldco", "AA731B2DD7")),
    ("https://apply.workable.com/feeldco/j/AA731B2DD7/apply/", ("feeldco", "AA731B2DD7")),
    ("https://apply.workable.com/feeldco/j/AA731B2DD7/?utm_source=x", ("feeldco", "AA731B2DD7")),
])
def test_workable_url_id_parsing(url, expected):
    assert af.workable_ids(url) == expected


# Workday --------------------------------------------------------------------
@pytest.mark.parametrize("url,expected", [
    # The Job_Posting_Site_ID is simply the first path segment ("WG"), NOT the
    # company name — guessing the company 404s with `not found: Job_Posting_Site_ID`.
    ("https://acme.wd1.myworkdayjobs.com/WG/job/New-York-NY/Product-Lead_JR101195?source=LinkedIn",
     "https://acme.wd1.myworkdayjobs.com/wday/cxs/acme/WG/job/New-York-NY/Product-Lead_JR101195"),
    # a locale segment before the site id is dropped
    ("https://acme.wd108.myworkdayjobs.com/en-US/Acme_Careers/job/NY/Product-Manager_JR8636-1",
     "https://acme.wd108.myworkdayjobs.com/wday/cxs/acme/Acme_Careers/job/NY/Product-Manager_JR8636-1"),
])
def test_workday_cxs_url_uses_the_path_site_id(url, expected):
    assert af.workday_cxs_url(url) == expected


@pytest.mark.parametrize("url", [
    "https://acme.wd1.myworkdayjobs.com/WG",                 # board root, no job
    "https://acme.wd1.myworkdayjobs.com/WG/search/Product",  # search page
])
def test_workday_cxs_url_none_without_a_job_path(url):
    assert af.workday_cxs_url(url) is None


def test_workday_payload_parses_title_company_location_and_type():
    res = af._workday_payload_to_result(
        _load(WORKDAY_JOB), "https://acme.wd1.myworkdayjobs.com/WG/job/x/y")
    assert res["title"] == "Associate Director of Product, Retention"
    # hiringOrganization, not the tenant slug.
    assert "Wonder" in res["company"]
    assert res["location"] == "New York, NY"
    assert res["employment_type"] == "Full time"
    assert res["source"] == "workday-cxs-api" and res["structured_source"] is True
    assert res["posting_id"] == "JR101195"
    assert len(res["text"]) > 2000


def test_workday_reports_comp_and_questions_as_absent_not_invented():
    """Workday CxS exposes no pay and only a `questionnaireId` (the questionnaire
    itself is behind candidate auth), so both must come back empty."""
    res = af._workday_payload_to_result(_load(WORKDAY_JOB), "http://x")
    assert res["compensation"] is None and res["compensation_raw"] is None
    assert res["questions"] == []


def test_workday_company_from_url_is_the_tenant_not_the_site_id():
    """The first path segment is the posting SITE id ("WG"), which would otherwise
    be written out as the hiring company."""
    assert af.ats_company_from_url(
        "https://acme.wd1.myworkdayjobs.com/WG/job/New-York-NY/Product-Lead_JR1") == "Acme"


# Lever ----------------------------------------------------------------------
def test_lever_exposes_the_apply_url_that_carries_its_questions(monkeypatch):
    """Lever's postings API has no questions field but DOES carry `applyUrl`, which
    is how the renderer reaches them."""
    job = _load(LEVER_JOB)
    assert "questions" not in job

    class FakeRequests:
        def get(self, url, **kw):
            return _FakeResp(200, job) if "api.lever.co" in url else _FakeResp(404, {})

    monkeypatch.setattr(af, "requests", FakeRequests())
    res = af._fetch_lever(
        "https://jobs.lever.co/findem/d1f48556-a8c9-46b7-b089-4317ec2dd280")
    assert res["source"] == "lever-postings-api"
    assert res["structured_source"] is True
    assert res["questions"] == []          # never on the API
    assert res["apply_url"].endswith("/apply")
    assert af.detect_apply_ats(res["apply_url"], None, res["source"]) == "lever"


# Dispatch -------------------------------------------------------------------
@pytest.mark.parametrize("url,fetcher", [
    ("https://ats.rippling.com/acme/jobs/0889e2ac-a30c-43b7-8c8c-5312264416db",
     "_fetch_rippling"),
    ("https://apply.workable.com/acme/j/AA731B2DD7", "_fetch_workable"),
    ("https://acme.wd1.myworkdayjobs.com/WG/job/NY/Product_JR1", "_fetch_workday"),
])
def test_fetch_via_ats_dispatches_the_new_hosts(monkeypatch, url, fetcher):
    seen = {}
    for name in ("_fetch_rippling", "_fetch_workable", "_fetch_workday"):
        monkeypatch.setattr(af, name,
                            lambda u, name=name, **kw: seen.setdefault("hit", name))
    af.fetch_via_ats(url)
    assert seen.get("hit") == fetcher


# Generalized apply-page renderer -------------------------------------------
def _pjp():
    return pytest.importorskip("prep_job_urls_playwright")


@pytest.mark.parametrize("url,expected", [
    ("https://jobs.ashbyhq.com/acme/fa0a5d05?src=LinkedIn",
     "https://jobs.ashbyhq.com/acme/fa0a5d05/application"),
    ("https://jobs.lever.co/acme/d1f48556?lever-source=LinkedIn",
     "https://jobs.lever.co/acme/d1f48556/apply"),
    ("https://jobs.lever.co/acme/d1f48556/apply",     # no double-append
     "https://jobs.lever.co/acme/d1f48556/apply"),
    ("https://apply.workable.com/acme/j/AA731B2DD7?utm_source=x",
     "https://apply.workable.com/acme/j/AA731B2DD7/apply/"),
    ("https://apply.workable.com/acme/j/AA731B2DD7/",
     "https://apply.workable.com/acme/j/AA731B2DD7/apply/"),
    ("https://acme.homerun.co/founding-product-manager",
     "https://acme.homerun.co/founding-product-manager/apply"),
])
def test_apply_page_url_per_ats_drops_query_and_never_double_appends(url, expected):
    assert _pjp().apply_page_url(url) == expected


@pytest.mark.parametrize("url", [
    # These ATSes return their questions ON the job API, so there is nothing to
    # render and no apply URL to build — rendering them would be pure cost.
    "https://ats.rippling.com/acme/jobs/0889e2ac-a30c-43b7-8c8c-5312264416db",
    "https://job-boards.greenhouse.io/acme/jobs/4705550005",
    "https://acme.wd1.myworkdayjobs.com/WG/job/NY/Product_JR1",
])
def test_apply_page_url_is_none_when_questions_come_from_the_api(url):
    assert _pjp().apply_page_url(url) is None


@pytest.mark.parametrize("hint,expected", [
    ("https://jobs.ashbyhq.com/acme/fa0a5d05", "ashby"),
    ("https://jobs.lever.co/acme/d1f48556", "lever"),
    ("https://apply.workable.com/acme/j/AA731B2DD7", "workable"),
    ("https://acme.homerun.co/role", "homerun"),
    # custom employer domain carrying the Ashby job id
    ("https://www.acme.com/careers/open-positions?ashby_jid=4ccf1e87-0317-4dca-949d-f7cb4f76fad7",
     "ashby"),
    # a `source` label, which is how custom-domain jobs get identified
    ("ashby-posting-api (custom-domain jid)", "ashby"),
    ("workable-api", "workable"),
    # ATSes whose API carries the questions must NOT be routed to a render
    ("https://job-boards.greenhouse.io/acme/jobs/4705550005", None),
    ("greenhouse-boards-api", None),
    ("rippling-ats-api", None),
    # a URL is matched on HOST only, so a role slug can't masquerade as an ATS
    ("https://boards.acme.com/jobs/clever-analytics-product-manager", None),
    ("https://careers.acme.com/jobs/workable-integrations-engineer", None),
])
def test_detect_apply_ats(hint, expected):
    assert af.detect_apply_ats(hint) == expected


def test_detect_apply_ats_prefers_the_first_informative_hint():
    assert af.detect_apply_ats(None, "", "https://jobs.lever.co/a/b") == "lever"
    assert af.detect_apply_ats("https://jobs.ashbyhq.com/a/b",
                               "https://www.acme.com/careers") == "ashby"


def test_workable_apply_page_is_rendered_on_the_primary_pass(monkeypatch):
    """Workable's API looks 'complete' (content + location), so no fallback pass
    would ever fire — the questions must be captured by the always-on apply-page
    render, merged in WITHOUT losing the API's location/workplace."""
    pju = pytest.importorskip("prep_job_urls")
    ats_res = af._workable_job_to_result(_load(WORKABLE_JOB), "feeldco", "Feeld")
    monkeypatch.setattr(pju, "fetch_via_ats", lambda u, **k: dict(ats_res))
    rendered = [{"label": "Have you worked in an all-remote environment?",
                 "type": "textarea", "required": True, "name": "CA_6815",
                 "names": ["CA_6815"], "options": []}]
    calls = {"n": 0}

    def renderer(u, apply_hint=None):
        calls["n"] += 1
        calls["hint"] = apply_hint
        return rendered

    out = pju.fetch_one("https://apply.workable.com/feeldco/j/AA731B2DD7",
                        question_renderer=renderer)
    assert calls["n"] == 1
    assert calls["hint"] == ats_res["apply_url"]
    assert out["questions"] == rendered and out["meta"]["questions"] == rendered
    assert "London" in out["meta"]["working_location"]
    assert out["meta"]["workplace"] == "Remote"


def test_rippling_never_renders_an_apply_page(monkeypatch):
    """Rippling returns its questions inline, so the render must not fire for it —
    no speed regression for an ATS that needs no browser."""
    pju = pytest.importorskip("prep_job_urls")
    ats_res = _rippling(RIPPLING_WITH_QUESTIONS)
    ats_res["questions"] = []  # force the empty branch so only the ATS gate decides
    monkeypatch.setattr(pju, "fetch_via_ats", lambda u, **k: dict(ats_res))
    calls = {"n": 0}

    def renderer(u, apply_hint=None):
        calls["n"] += 1
        return [{"label": "should never be called"}]

    out = pju.fetch_one(
        "https://ats.rippling.com/rippling/jobs/8df88337-6e68-4137-96b3-6045f7865d6f",
        question_renderer=renderer)
    assert calls["n"] == 0
    assert out["questions"] == []


def test_apply_render_failure_prints_and_degrades(monkeypatch, capsys):
    """A render failure must never fail the fetch — and must never be silent
    either: a swallowed exception is what hid the broken Ashby apply-URL builder."""
    pju = pytest.importorskip("prep_job_urls")
    ats_res = af._workable_job_to_result(_load(WORKABLE_JOB), "feeldco", "Feeld")
    monkeypatch.setattr(pju, "fetch_via_ats", lambda u, **k: dict(ats_res))

    def boom(u, apply_hint=None):
        raise RuntimeError("render failed")

    out = pju.fetch_one("https://apply.workable.com/feeldco/j/AA731B2DD7",
                        question_renderer=boom)
    assert out["ok"] is True and out["questions"] == []
    assert "render failed" in capsys.readouterr().out


# Rendered-label cleanup ----------------------------------------------------
@pytest.mark.parametrize("raw,options,label,required", [
    # Workable puts the required marker on its own line ABOVE the label.
    ("*\nHave you worked in an all-remote or a remote-first environment?", [],
     "Have you worked in an all-remote or a remote-first environment?", True),
    # Lever / Homerun put it after the label.
    ("Full name\n✱", [], "Full name", True),
    ("Tell us about a launch you shipped. *", [],
     "Tell us about a launch you shipped.", True),
    # A select's own option text lands in the container innerText — drop it, or the
    # option list is duplicated into the question label.
    ("Which location are you applying for?\nSelect...\nUS (Remote)\nSan Francisco",
     [{"label": "Select..."}, {"label": "US (Remote)"}, {"label": "San Francisco"}],
     "Which location are you applying for?", False),
    # File-input chrome.
    ("Resume/CV\nATTACH RESUME/CV", [], "Resume/CV", False),
    # An unadorned label is returned untouched.
    ("Why do you want to work here?", [], "Why do you want to work here?", False),
])
def test_clean_apply_label(raw, options, label, required):
    assert af.clean_apply_label(raw, options) == (label, required)


def test_normalize_apply_fields_infers_required_from_a_visual_marker():
    """Homerun marks required-ness only with a trailing asterisk (no `required`
    attribute), so the marker is the only signal available."""
    out = af.normalize_apply_fields({"fields": [
        {"title": "Describe a feature you took from discovery to launch. *",
         "type": "LongText", "path": "", "isRequired": False, "options": []},
    ]})
    assert out[0]["required"] is True
    assert out[0]["label"].endswith("launch.")
    assert out[0]["type"] == "textarea"


# Filter: routine sourcing / accommodation / candidate-location free-text -----
@pytest.mark.parametrize("label", [
    "Where are you based? (More than one place is fine!)",
    "Where did you find out about this open role?",
    "How did you hear about us?",
    "Are there any accommodations you require for the interview process?",
])
def test_routine_free_text_fields_are_dropped(label):
    """These are free-text, so the compose keep-rule would otherwise retain them,
    but they are administrative: they say nothing about the job."""
    assert af.filter_questions(
        [{"label": label, "type": "textarea", "required": False, "options": []}]) == []


# ===========================================================================
# Captured-identity contract — `company-name__job-title.txt` (spec 2026-07-29)
#
# One normalizer (`normalize_capture_identity`) at ONE choke point in process_urls, so
# every fetch route lands on the same filename + the same Company:/Role: header.
# ===========================================================================
AIRBNB_URL = "https://careers.airbnb.com/positions/8044715"
AIRBNB_FILE = "airbnb__product-manager-incubations.txt"


def _airbnb_html():
    return (FIXTURES / "airbnb_incubations_head.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("company,title", [
    # Company wrappers, every direction.
    ("Careers at Airbnb", "Product Manager, Incubations"),
    ("careers at airbnb", "Product Manager, Incubations"),
    ("Jobs at Airbnb", "Product Manager, Incubations"),
    ("Airbnb Careers", "Product Manager, Incubations"),
    ("Airbnb Jobs", "Product Manager, Incubations"),
    # Title site-branding suffixes, every separator.
    ("Airbnb", "Product Manager, Incubations - Careers at Airbnb"),
    ("Airbnb", "Product Manager, Incubations | Airbnb Careers"),
    ("Airbnb", "Product Manager, Incubations — Airbnb Careers"),
    ("Airbnb", "Product Manager, Incubations - Airbnb"),
    # The two identities actually observed in the field.
    ("Careers at Airbnb", "Product Manager, Incubations - Careers at Airbnb"),
    ("Product Manager, Incubations", "Product Manager, Incubations - Careers at Airbnb"),
    # Already clean — must pass through untouched (idempotence).
    ("Airbnb", "Product Manager, Incubations"),
])
def test_capture_identity_matrix_yields_one_company_and_role(company, title):
    co, ro = pc.normalize_capture_identity(company, title, url=AIRBNB_URL)
    assert (co, ro) == ("Airbnb", "Product Manager, Incubations")
    # Idempotent: normalizing the normalized pair changes nothing.
    assert pc.normalize_capture_identity(co, ro, url=AIRBNB_URL) == (co, ro)
    # And the FINAL artifact — the filename — is the one correct name.
    assert pc.base_filename(co, ro) == AIRBNB_FILE
    assert pc.unique_filename(co, ro, "n1", {}, AIRBNB_URL) == AIRBNB_FILE


def test_capture_identity_requests_route():
    """requests path: extract_title (og:title, branded) + detect_company."""
    import prep_job_urls as pj
    html = _airbnb_html()
    title = pj.extract_title(html)
    assert title == "Product Manager, Incubations - Careers at Airbnb"  # branded, as scraped
    company = pj.detect_company(AIRBNB_URL, title)
    co, ro = pc.normalize_capture_identity(company, title, url=AIRBNB_URL)
    assert (co, ro) == ("Airbnb", "Product Manager, Incubations")
    assert pc.base_filename(co, ro) == AIRBNB_FILE


def test_capture_identity_playwright_route():
    """playwright path: best_company_from_title over the branded page title."""
    import prep_job_urls_playwright as pjp
    title = "Product Manager, Incubations - Careers at Airbnb"
    company = pjp.best_company_from_title(title, pjp.detect_company_from_url(AIRBNB_URL))
    co, ro = pc.normalize_capture_identity(company, title, url=AIRBNB_URL)
    assert (co, ro) == ("Airbnb", "Product Manager, Incubations")
    assert pc.base_filename(co, ro) == AIRBNB_FILE


def test_best_company_from_title_rejects_branding_segments_by_pattern():
    """The old exact-set `bad` test let "Careers at Airbnb" through as the company —
    that is what produced `careers-at-airbnb__…txt`. Reject by PATTERN instead."""
    import prep_job_urls_playwright as pjp
    for branded in ("Careers at Airbnb", "Airbnb Careers", "Jobs at Airbnb", "View all jobs"):
        assert pjp.best_company_from_title(f"Some Role | {branded}", "Fallback") != branded


def test_capture_identity_prefers_jsonld_over_scraped_chrome():
    jsonld = af.extract_jsonld_jobposting(_airbnb_html())
    assert jsonld["hiring_organization"] == "Airbnb"
    assert jsonld["title"] == "Product Manager, Incubations"
    identity = {"hiring_organization": jsonld["hiring_organization"], "title": jsonld["title"]}
    # Even with BOTH scraped values wrong, structured identity wins.
    co, ro = pc.normalize_capture_identity(
        "Careers at Airbnb", "Product Manager, Incubations - Careers at Airbnb",
        url=AIRBNB_URL, jsonld=identity)
    assert (co, ro) == ("Airbnb", "Product Manager, Incubations")
    assert pc.base_filename(co, ro) == AIRBNB_FILE


def test_jsonld_identity_does_not_change_structured_source_semantics():
    """`structured_source: bool(jobposting)` must behave exactly as before — the
    return-None criterion stays keyed on location/employment_type/compensation only."""
    identity_only = """<script type="application/ld+json">
      {"@type": "JobPosting", "title": "PM", "hiringOrganization": {"name": "Acme"}}
    </script>"""
    assert af.extract_jsonld_jobposting(identity_only) is None


def test_capture_identity_never_uses_the_role_as_the_company():
    """No wrapper name available: fall back to the DOMAIN, never the role."""
    co, ro = pc.normalize_capture_identity(
        "Product Manager, Incubations", "Product Manager, Incubations",
        url=AIRBNB_URL)
    assert co == "Airbnb"
    assert ro == "Product Manager, Incubations"
    # An ATS host names the platform, not the employer — no domain fallback there, so a
    # conservative normalizer keeps what it was given rather than inventing "Greenhouse".
    co2, _ = pc.normalize_capture_identity(
        "Staff PM", "Staff PM", url="https://job-boards.greenhouse.io/acme/jobs/123")
    assert co2 == "Staff PM"


def test_capture_identity_leaves_clean_ats_values_alone():
    """ATS API routes already produce clean identities (this is the embedded-GH
    recovery shape too) — normalization must be a no-op for them."""
    for company, title in [("Bloomerang", "Senior Product Manager"),
                           ("Betterup", "Principal Product Manager"),
                           ("Feeld", "Chief Product Officer")]:
        assert pc.normalize_capture_identity(
            company, title, url="https://boards.greenhouse.io/x/jobs/1") == (company, title)


def test_capture_identity_normalizes_at_the_choke_point(tmp_path):
    """The FINAL artifact, through process_urls: the written file name and the
    Company:/Role: header lines, for a fetch result carrying the bad identity."""
    src = _batch_source(tmp_path)
    body = af._html_to_text(_airbnb_html())

    def fetch(u):
        return {"ok": True, "title": "Product Manager, Incubations - Careers at Airbnb",
                "company": "Careers at Airbnb", "body": body, "method": "requests",
                "error": None,
                "meta": {"title": "Product Manager, Incubations - Careers at Airbnb",
                         "company": "Careers at Airbnb", "source": "requests/html",
                         "structured_source": False, "working_location": None,
                         "compensation": None},
                "questions": []}

    manifest = pc.process_urls([AIRBNB_URL], src, fetch)
    entry = manifest["entries"][0]
    assert entry["status"] == pc.USABLE
    assert entry["company"] == "Airbnb"
    assert entry["title"] == "Product Manager, Incubations"
    assert Path(entry["output_path"]).name == AIRBNB_FILE
    written = (src / AIRBNB_FILE).read_text(encoding="utf-8")
    assert "Company: Airbnb" in written
    assert "Role: Product Manager, Incubations" in written


# ===========================================================================
# Capture completeness — all offices, the third benefits/equity state, verbatim
# source fields, base-only prose comp, and reachable CONFLICTING.
# ===========================================================================
def test_all_employer_listed_cities_are_preserved():
    body = ("About the role\nThis role can be based in San Francisco, CA or New York, NY. "
            + ("work " * 60))
    assert pc._prose_city_states(body) == ["San Francisco, CA", "New York, NY"]
    value = pc._prose_working_location(body)
    assert "San Francisco, CA" in value and "New York, NY" in value


def test_benefits_and_equity_mentioned_without_details_is_not_not_posted():
    body = ("About the role\nResponsibilities include shipping product. You may also be "
            "eligible for bonus, equity, benefits, and Employee Travel Credits.")
    benefits, equity = af.mine_benefits_equity(body)
    assert equity == af.MENTIONED_NO_DETAILS
    assert benefits == af.MENTIONED_NO_DETAILS
    out = pc.build_output_text("http://x", "PM", "Airbnb", body,
                               meta={"title": "PM", "benefits": benefits, "equity": equity},
                               field_status={"conflicts": []}, methods_tried=["requests"])
    # The equity/bonus/travel-credit eligibility lives in Additional Compensation,
    # split out of the old Equity shoehorn — honest mention phrasing, never "Not Posted".
    assert ("Additional Compensation: Bonus, equity, and Employee Travel Credits "
            "mentioned, but details not provided.") in out
    assert "Benefits: Mentioned, but details not provided." in out
    assert "Not Posted" not in out and "Not posted" not in out


def test_a_posting_that_says_nothing_still_reports_did_not_mention():
    """The third state must not swallow the genuine "employer published nothing" case."""
    benefits, equity = af.mine_benefits_equity(
        "About the role\nResponsibilities include shipping product every quarter.")
    assert benefits is None and equity is None
    out = pc.build_output_text("http://x", "PM", "Acme", "Responsibilities...",
                               meta={"title": "PM"}, field_status={"conflicts": []})
    assert "Benefits: Employer did not mention benefits." in out
    assert "Additional Compensation: Employer did not mention additional compensation." in out


def test_comp_disclaimer_sentence_is_never_surfaced_as_the_equity_value():
    """The BetterUp regression: a base-salary DISCLAIMER became the Equity value."""
    _b, equity = af.mine_benefits_equity(
        "The range below is representative of base salary only and does not include equity, "
        "sales bonus plans (when applicable) and benefits")
    assert equity == af.MENTIONED_NO_DETAILS
    # A real equity description still comes through verbatim.
    _b2, equity2 = af.mine_benefits_equity(
        "This role includes an equity grant of 4,000 restricted stock units vesting over 4 years.")
    assert "4,000 restricted stock units" in equity2


def test_prose_derived_fields_populate_the_capture_when_structured_is_absent():
    body = af._html_to_text(_airbnb_html())
    meta = {"title": "Product Manager, Incubations", "source": "requests/html",
            "structured_source": False, "compensation": None, "compensation_raw": None,
            "working_location": None, "location": None, "location_raw": None}
    fs = pc.assess_completeness(meta, body, [])
    assert fs["compensation"] == pc.FOUND and fs["working_location"] == pc.FOUND
    assert "220,000" in fs["compensation_prose_verbatim"]
    assert "San Francisco, CA" in fs["working_location_prose_verbatim"]
    out = pc.build_output_text(AIRBNB_URL, "Product Manager, Incubations", "Airbnb", body,
                               meta=meta, field_status=fs, methods_tried=["requests"])
    # The employer's own prose values fill the sections — never a blank/quoted-empty field.
    assert "Base Salary:" in out and "220,000" in out
    assert "SF or NYC" in out.split("WORK DETAILS")[1].split("COMPENSATION")[0]
    # The prose states a "3 days per week" cadence — mined into Office Expectation.
    assert "Office Expectation: 3 Days Per Week" in out
    assert ': ""' not in out  # no empty quoted fields anywhere in the new contract


def test_ote_and_total_comp_no_longer_qualify_a_base_salary_range():
    """A variable-pay figure is not base salary and must not become the comp value."""
    for line in ("OTE for this role is 200,000-260,000.",
                 "Total comp is 300,000-400,000 for this level."):
        assert pc._prose_compensation(line) is None, line
    # A base-salary keyword still qualifies the same shape.
    assert pc._prose_compensation("Base salary range is 200,000-260,000.") is not None


def test_all_prose_comp_bands_are_collected_not_just_the_first():
    body = ("Compensation\nZone A base salary: $236,000 - $296,000 per year. "
            "Zone B base salary: $213,000 - $266,000 per year.")
    found = pc._prose_compensation_all(body)
    assert len(found) == 2
    assert "236,000" in found[0]["value"] and "213,000" in found[1]["value"]
    fs = pc.assess_completeness(
        {"title": "PM", "source": "requests/html", "structured_source": False,
         "compensation": None, "working_location": "Remote"}, body, [])
    assert len(fs["compensation_prose_all"]) == 2


def test_conflicting_is_reachable_when_ats_and_prose_envelopes_are_disjoint():
    body = ("About the role\nThe base salary range for this role is $110,000 - $130,000 "
            "annually. " + ("value " * 60))
    meta = {"title": "PM", "source": "greenhouse-boards-api", "structured_source": True,
            "compensation": "USD 236,000–296,000", "working_location": "Remote"}
    fs = pc.assess_completeness(meta, body, [])
    assert fs["compensation"] == pc.CONFLICTING
    # Both readings preserved machine-readably (rides into the manifest via field_status).
    labels = [s for s, _ in fs["compensation_sources"]]
    values = [v for _, v in fs["compensation_sources"]]
    assert labels == ["greenhouse-boards-api", "description"]
    assert "236,000" in values[0] and "110,000" in values[1]
    out = pc.build_output_text("http://x", "PM", "Acme", body, meta=meta, field_status=fs)
    assert "Conflicting employer information:" in out
    assert "Compensation ⚠ Conflicting" in out  # the Verification line flags it too


def test_identical_figures_in_ats_and_prose_do_not_false_flag_a_conflict():
    """Repeating the structured range in the prose is the COMMON case, not a conflict —
    "materially disagree" means disjoint envelopes."""
    body = ("About the role\nThe base salary range for this role is $213,000 - $296,000 "
            "annually. " + ("value " * 60))
    meta = {"title": "PM", "source": "ashby-posting-api", "structured_source": True,
            "compensation": "Zone A: $236K – $296K · Zone B: $213K – $266K",
            "working_location": "Remote"}
    fs = pc.assess_completeness(meta, body, [])
    assert fs["compensation"] == pc.FOUND
    assert "compensation_sources" not in fs


def test_location_conflict_only_when_city_sets_are_disjoint():
    disjoint = ("About the role\nThis position is based in Denver, CO. " + ("x " * 60))
    overlap = ("About the role\nThis position is based in Austin, TX. " + ("x " * 60))
    base = {"title": "PM", "source": "greenhouse-boards-api", "structured_source": True,
            "compensation": "USD 200,000", "working_location": "Austin, TX; New York, NY"}
    assert pc.assess_completeness(dict(base), disjoint, [])["working_location"] == pc.CONFLICTING
    assert pc.assess_completeness(dict(base), overlap, [])["working_location"] == pc.FOUND


# ===========================================================================
# Posting dates — every ATS carries one and we used to discard all of them.
# The only date in a capture was `Captured:` (our fetch date), so nothing
# downstream could tell a week-old posting from a nine-month-old one.
# ===========================================================================
@pytest.mark.parametrize("raw,expected", [
    ("2026-06-13T09:05:32-04:00", "2026-06-13"),   # ISO + TZ offset (Greenhouse)
    ("2026-03-25T17:55:55.843+00:00", "2026-03-25"),  # Ashby
    ("2026-07-14T00:00:00.000Z", "2026-07-14"),    # Workable
    ("2026-06-29", "2026-06-29"),                  # plain date (Workday startDate)
    (1782932070272, "2026-07-01"),                 # Lever: epoch MILLISECONDS
    ("1782932070272", "2026-07-01"),
    # Never fabricate:
    ("Posted 30 Days Ago", None),                  # Workday's relative wording
    ("Posted Yesterday", None),
    ("", None), (None, None), ("not a date", None),
    ("2026-13-45T00:00:00Z", None),                # impossible date
    (0, None), (True, None),
])
def test_posting_date_normalization(raw, expected):
    assert af.normalize_posting_date(raw) == expected


def test_posting_date_is_idempotent():
    once = af.normalize_posting_date("2026-06-13T09:05:32-04:00")
    assert af.normalize_posting_date(once) == once


def test_every_ats_fixture_yields_a_posted_date():
    """Real payloads, real fields — all of these were already parsed and discarded."""
    gh = af._greenhouse_job_to_result(
        _load("greenhouse_bloomerang_4705550005.json"), "bloomerang", "Bloomerang", "http://x")
    assert gh["posted_date"] == "2026-06-13" and gh["updated_date"] == "2026-06-13"

    ashby = af._ashby_job_to_result(_load("ashby_betterup_principal_pm.json"), "betterup")
    assert ashby["posted_date"] == "2026-03-25"

    rip = af._rippling_job_to_result(
        _load("rippling_workplace_coordinator.json"), "board", "http://x")
    assert rip["posted_date"] == "2026-06-29"

    wk = af._workable_job_to_result(
        _load("workable_feeld_cpo.json"), "feeldco", "Feeld", "http://x")
    assert wk["posted_date"] == "2026-07-14"

    wd = af._workday_payload_to_result(_load("workday_wonder_assoc_dir_product.json"), "http://x")
    # Workday's postedOn is the relative string "Posted 30 Days Ago" — rejected, so the
    # payload's real ISO startDate is used instead of inventing a date.
    assert wd["posted_date"] == "2026-06-29"


def test_lever_posting_date_converts_epoch_milliseconds():
    job = _load("lever_findem_posting.json")
    assert isinstance(job["createdAt"], int) and job["createdAt"] > 10 ** 12
    assert af.normalize_posting_date(job["createdAt"]) == "2026-07-01"


def test_jsonld_date_posted_is_captured_for_generic_pages():
    html = """<script type="application/ld+json">{"@type":"JobPosting","title":"PM",
      "employmentType":"FULL_TIME","datePosted":"2026-05-02T00:00:00Z",
      "dateModified":"2026-05-09"}</script>"""
    jp = af.extract_jsonld_jobposting(html)
    assert jp["posted_date"] == "2026-05-02" and jp["updated_date"] == "2026-05-09"


def test_posted_and_updated_lines_are_always_present_and_human_readable():
    base = dict(title="PM", source="greenhouse-boards-api")
    out = pc.build_output_text("http://x", "PM", "Acme", "Responsibilities...",
                               meta={**base, "posted_date": "2026-06-13",
                                     "updated_date": "2026-06-20"},
                               field_status={"conflicts": []}, captured="2026-07-29")
    assert "Job Posted At: June 13, 2026" in out
    assert "Job Updated At: June 20, 2026" in out
    # No posted/updated date at all -> the lines are STILL present, honestly `Unknown`
    # (replaces the legacy omit-when-unknown behavior; never a fabricated date).
    none = pc.build_output_text("http://x", "PM", "Acme", "Responsibilities...",
                                meta=base, field_status={"conflicts": []}, captured="2026-07-29")
    assert "Job Posted At: Unknown" in none
    assert "Job Updated At: Unknown" in none
    # The legacy `Posted:` provenance line is gone from newly written captures.
    assert "\nPosted:" not in out and "\nPosted:" not in none


def test_posted_and_updated_are_distinct_from_captured():
    """Job Posted At / Job Updated At are the EMPLOYER's dates (JOB SNAPSHOT);
    Captured is OUR fetch moment (ORIGINAL CAPTURE DETAILS, in ET) — never conflated."""
    out = pc.build_output_text("http://x", "PM", "Acme", "Responsibilities...",
                               meta={"title": "PM", "posted_date": "2026-06-13",
                                     "updated_date": "2026-06-20"},
                               field_status={"conflicts": []},
                               captured="2026-07-29T20:06:00+00:00")
    head, _, tail = out.partition("--- JOB TEXT START ---")
    assert "Job Posted At: June 13, 2026" in head and "Captured At:" not in head
    assert "Captured At: July 29, 2026 at 4:06 PM ET" in tail
    assert "June 13, 2026" not in tail.split("Captured At:")[1].splitlines()[0]


def test_manifest_records_the_posting_dates(tmp_path):
    src = _batch_source(tmp_path)

    def fetch(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": _LONG_BODY,
                "method": "ats", "error": None,
                "meta": {"title": "PM", "source": "greenhouse-boards-api",
                         "structured_source": True, "compensation": "USD 200,000",
                         "working_location": "Remote", "posted_date": "2026-06-13",
                         "updated_date": "2026-06-20"},
                "questions": []}

    manifest = pc.process_urls(["https://example.com/job/9"], src, fetch)
    entry = manifest["entries"][0]
    assert entry["posted_date"] == "2026-06-13"
    assert entry["updated_date"] == "2026-06-20"
    written = (src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
    assert "Job Posted At: June 13, 2026" in written
    assert "Job Updated At: June 20, 2026" in written


# ===========================================================================
# Canonical apply-URL deep links — four employer-hosted Greenhouse apply URLs are
# LISTING/SEARCH pages that only redirect via ?gh_jid=. Saved as the Application
# URL, they open a job SEARCH later, not the posting.
# ===========================================================================
_GH_JOB_ID = 4705550005


def _gh_result(absolute_url):
    job = dict(_load("greenhouse_bloomerang_4705550005.json"))
    job["absolute_url"] = absolute_url
    job["id"] = _GH_JOB_ID
    return af._greenhouse_job_to_result(job, "acmeboard", "Acme", "http://original")


@pytest.mark.parametrize("listing_url", [
    f"https://stripe.com/jobs/search?gh_jid={_GH_JOB_ID}",
    f"https://www.pinterestcareers.com/jobs/?gh_jid={_GH_JOB_ID}",
    f"https://www.ordergroove.com/jobs/?gh_jid={_GH_JOB_ID}",
    f"https://careers.onepeloton.com/en/all-jobs/?gh_jid={_GH_JOB_ID}&gh_src=abc",
])
def test_listing_page_apply_urls_become_canonical_deep_links(listing_url):
    assert af.greenhouse_apply_url_is_listing_page(listing_url, _GH_JOB_ID) is True
    res = _gh_result(listing_url)
    assert res["apply_url"] == f"https://job-boards.greenhouse.io/acmeboard/jobs/{_GH_JOB_ID}"
    # The employer URL is preserved in the fetch result (manifest-side) — nothing is
    # lost — but the capture itself carries only Job Posting URL + Application URL
    # (no duplicative `Employer Apply Page:` field, per the 2026-07-29 spec).
    assert res["employer_apply_url"] == listing_url
    out = pc.build_output_text("http://original", res["title"], res["company"], res["text"],
                               meta=res, questions=[], methods_tried=["ats"])
    assert f"Application URL: https://job-boards.greenhouse.io/acmeboard/jobs/{_GH_JOB_ID}" in out
    assert listing_url not in out.split("Job Posting URL:")[1]
    assert "Employer Apply Page" not in out and "Employer apply page" not in out


@pytest.mark.parametrize("deep_link", [
    f"https://careers.airbnb.com/positions/{_GH_JOB_ID}",
    f"https://asana.com/jobs/apply/{_GH_JOB_ID}/product-manager",
    f"https://job-boards.greenhouse.io/acmeboard/jobs/{_GH_JOB_ID}",
    f"https://boards.greenhouse.io/acmeboard/jobs/{_GH_JOB_ID}?gh_src=x",
])
def test_real_employer_deep_links_are_kept_unchanged(deep_link):
    assert af.greenhouse_apply_url_is_listing_page(deep_link, _GH_JOB_ID) is False
    res = _gh_result(deep_link)
    assert res["apply_url"] == deep_link
    assert res["employer_apply_url"] is None
    out = pc.build_output_text("http://original", res["title"], res["company"], res["text"],
                               meta=res, questions=[], methods_tried=["ats"])
    assert "Employer apply page (verbatim):" not in out


def test_listing_detection_needs_the_id_in_the_query_and_not_the_path():
    # A listing-ish path with no job id anywhere: don't second-guess it.
    assert af.greenhouse_apply_url_is_listing_page("https://acme.com/jobs/", _GH_JOB_ID) is False
    # Missing pieces are never a match.
    assert af.greenhouse_apply_url_is_listing_page(None, _GH_JOB_ID) is False
    assert af.greenhouse_apply_url_is_listing_page("https://acme.com/jobs/?gh_jid=1", None) is False


def test_other_ats_apply_urls_are_untouched():
    """The rewrite is Greenhouse-specific: no other ATS result gains an override."""
    ashby = af._ashby_job_to_result(_load("ashby_betterup_principal_pm.json"), "betterup")
    assert ashby["apply_url"].endswith("/application")
    assert ashby.get("employer_apply_url") is None
    rip = af._rippling_job_to_result(
        _load("rippling_workplace_coordinator.json"), "board", "http://x")
    assert rip.get("employer_apply_url") is None
    wk = af._workable_job_to_result(
        _load("workable_feeld_cpo.json"), "feeldco", "Feeld", "http://x")
    assert "apply.workable.com" in wk["apply_url"]
    assert wk.get("employer_apply_url") is None


# ===========================================================================
# "Never company-as-role" — the guard symmetric to never-role-as-company.
#
# Real failing capture: metacareers.com wrote `Company: Meta Careers` /
# `Role: Meta Careers` into `meta-careers__meta-careers.txt`. Cleaning the company was
# not enough; a branding-only ROLE must be RECOVERED from the page (JSON-LD title ->
# first heading -> first non-navigation body heading) or marked a capture failure.
# ===========================================================================
META_URL = "https://www.metacareers.com/profile/job_details/903804022277159/"
META_FILE = "meta__product-manager-central-product.txt"
META_ROLE = "Product Manager, Central Product"


def _meta_html():
    return (FIXTURES / "metacareers_central_product.html").read_text(encoding="utf-8")


def _meta_body():
    return af._html_to_text(_meta_html())


def test_branding_only_title_is_recovered_from_the_body_heading():
    """No JSON-LD, and the only heading is branding too — the real title exists only as
    the first content line of the body, after the nav chrome."""
    co, ro = pc.normalize_capture_identity(
        "Meta Careers", "Meta Careers", url=META_URL,
        html=_meta_html(), body=_meta_body())
    assert (co, ro) == ("Meta", META_ROLE)
    assert pc.base_filename(co, ro) == META_FILE
    # Idempotent: the recovered identity re-normalizes to itself.
    assert pc.normalize_capture_identity(co, ro, url=META_URL, html=_meta_html(),
                                         body=_meta_body()) == (co, ro)


@pytest.mark.parametrize("company,title", [
    ("Meta Careers", "Meta Careers"),      # the observed pair
    ("Meta", "Meta Careers"),              # branding suffix, nothing else
    ("Meta", "Careers at Meta"),           # branding prefix
    ("Meta", "Jobs — Meta"),               # branding with a dash separator
    ("Meta", "Careers"),                   # bare branding
    ("Meta", ""),                          # nothing captured at all
])
def test_invalid_titles_all_recover_to_the_real_role(company, title):
    co, ro = pc.normalize_capture_identity(company, title, url=META_URL,
                                           html=_meta_html(), body=_meta_body())
    assert (co, ro) == ("Meta", META_ROLE)


@pytest.mark.parametrize("scraped_title", [
    "job details", "Job Details", "Job Description", "Open Positions", "Apply Now",
])
def test_generic_page_titles_are_branding_not_roles(scraped_title):
    """An ATS page whose title names the PAGE ("job details") carries no role information,
    so it must trigger recovery. Observed live: a careers site served
    `Role: job details` with the real role sitting in the company slot."""
    role = "Product Manager, Workspace Ecosystem"
    body = f"{role}\n- linkCopy link\n- Health, dental, vision insurance\n"
    url = "https://www.google.com/about/careers/applications/jobs/results/93719465-pm"
    co, ro = pc.normalize_capture_identity(role, scraped_title, url=url, body=body)
    assert (co, ro) == ("Google", role)
    assert pc.base_filename(co, ro) == "google__product-manager-workspace-ecosystem.txt"


def test_the_employer_name_alone_never_masks_the_title_line():
    """The employer's words count as nav vocabulary only alongside a real nav word
    ("Working at <Co>"). When the company slot holds the ROLE text, its words must not hide
    the matching title line in the body."""
    role = "Product Manager, Workspace Ecosystem"
    assert pc._first_content_heading(f"{role}\nmore text here\n", [role]) == role
    assert pc._first_content_heading("Working at Acme\nStaff PM, Growth\n",
                                     ["Acme"]) == "Staff PM, Growth"


def test_title_recovery_ignores_h2_footer_chrome_and_uses_the_body_instead():
    """Observed live: h1 was "job details" and the h2 list ran "Jobs search results",
    "Follow Life at <Employer> on", "More about us" — footer chrome that outranked the body's
    own first content line and became the role. Recovery reads h1 ONLY."""
    role = "Product Manager, Workspace Ecosystem"
    html = ("<html><body><h1>job details</h1><h2>Jobs search results</h2>"
            "<h2>Follow Life at Google on</h2><h2>More about us</h2></body></html>")
    body = f"{role}\n- linkCopy link\n- Health, dental, vision insurance\n"
    url = "https://www.google.com/about/careers/applications/jobs/results/93719465-pm"
    co, ro = pc.normalize_capture_identity(role, "job details", url=url, html=html, body=body)
    assert (co, ro) == ("Google", role)
    assert pc._headings_from_html(html) == ["job details"]


@pytest.mark.parametrize("label", ["Jobs search results", "Search Results", "job details"])
def test_a_short_label_made_only_of_nav_vocabulary_is_branding(label):
    """Generalizes past a fixed list: the same careers SPA served a different chrome title on
    every visit ("job details", then "Jobs search results")."""
    assert pc._title_is_branding(label) is True


@pytest.mark.parametrize("real", [
    "Product Manager, Central Product", "Director of Product", "Staff PM",
    "Head of Design", "Senior Software Engineer",
])
def test_real_titles_are_never_branding(real):
    assert pc._title_is_branding(real) is False


def test_a_plain_collision_is_fixed_on_the_COMPANY_side_not_by_rewriting_the_title():
    """When a non-branding title merely equals the company, the ambiguity is resolved by the
    never-role-as-company guard — the title is NOT rewritten from loose body text. A real
    capture proved why: the body's own chrome ("linkCopy link") would have become the role."""
    body = "Product Manager, Workspace Ecosystem\n- linkCopy link\n- emailEmail a friend\n"
    role = "Product Manager, Workspace Ecosystem"
    co, ro = pc.normalize_capture_identity(role, role, url="https://careers.acme.com/x", body=body)
    assert ro == role
    assert co == "Acme"        # the COMPANY is what gets repaired
    # High-confidence structured sources may still correct such a title.
    co2, ro2 = pc.normalize_capture_identity(
        role, role, url="https://careers.acme.com/x", body=body,
        html="<h1>Staff PM, Workspace Ecosystem</h1>")
    assert ro2 == "Staff PM, Workspace Ecosystem"


def test_an_employer_careers_path_on_a_board_host_still_names_the_employer():
    """A big-company domain can be both a job board and its own careers site. On an explicit
    `/careers` path the host names the employer — without this, a careers-site posting whose
    title also sat in the company slot had no alternative name and the filename doubled the
    role (`<role>__<role>.txt`)."""
    role = "Product Manager, Workspace Ecosystem"
    url = "https://www.google.com/about/careers/applications/jobs/results/937194656-pm"
    co, ro = pc.normalize_capture_identity(role, role, url=url)
    assert (co, ro) == ("Google", role)
    assert pc.base_filename(co, ro) == "google__product-manager-workspace-ecosystem.txt"
    # A board host WITHOUT a careers path is still not an employer name.
    assert pc._company_from_domain("https://www.linkedin.com/jobs/view/123") is None
    assert pc._company_from_domain("https://www.google.com/search/jobs?q=pm") is None


def test_an_unresolvable_collision_keeps_the_role_text_rather_than_destroying_it():
    """No alternative company name exists (ATS host, no careers path): leave the pair as-is.
    Only a BRANDING title is failed loudly — a probable-real role is never discarded."""
    role = "Staff PM"
    co, ro = pc.normalize_capture_identity(
        role, role, url="https://job-boards.greenhouse.io/acme/jobs/123")
    assert (co, ro) == (role, role)


def test_a_company_named_inside_a_longer_title_is_not_role_as_company():
    """`Director, Product Management, ClassPass Consumer` legitimately names its employer.
    Treating that containment as role-as-company replaced an ATS-authoritative employer name
    with a domain-derived parent-company name the user would not recognize."""
    co, ro = pc.normalize_capture_identity(
        "ClassPass", "Director, Product Management, ClassPass Consumer",
        url="https://www.playlist.com/careers/opportunities/4627850006")
    assert (co, ro) == ("ClassPass", "Director, Product Management, ClassPass Consumer")


def test_jsonld_title_is_the_first_recovery_source():
    identity = {"hiring_organization": "Meta", "title": META_ROLE}
    co, ro = pc.normalize_capture_identity("Meta Careers", "Meta Careers", url=META_URL,
                                           jsonld=identity)
    assert (co, ro) == ("Meta", META_ROLE)


def test_page_heading_is_the_second_recovery_source():
    """When the first heading IS a real title, it is used (no body scan needed)."""
    html = f"<html><head><title>Acme Careers</title></head><body><h1>{META_ROLE}</h1></body></html>"
    co, ro = pc.normalize_capture_identity("Acme Careers", "Acme Careers",
                                           url="https://careers.acme.com/jobs/9", html=html)
    assert (co, ro) == ("Acme", META_ROLE)


def test_a_real_title_containing_a_branding_word_is_never_discarded():
    """The guard is narrow on purpose: a genuine role may contain 'Careers'/'Jobs'."""
    for role in ("PM, Careers Platform Experience", "Director of Career Products",
                 "Staff Product Manager, Jobs Marketplace"):
        co, ro = pc.normalize_capture_identity("Acme", role, url="https://careers.acme.com/x")
        assert (co, ro) == ("Acme", role)


def test_unrecoverable_title_is_a_loud_capture_failure_not_a_branding_filename(tmp_path):
    """Nothing recoverable: the title must NOT become a branding string. It is marked
    `title: capture_failed`, which surfaces on the capture's Completeness line, in the
    manifest entry, and in the prep report — never silently accepted."""
    src = _batch_source(tmp_path)
    url = "https://www.example-careers.com/job/1"

    def fetch(u):
        return {"ok": True, "title": "Example Careers", "company": "Example Careers",
                "body": _LONG_BODY, "method": "requests", "error": None,
                "meta": {"title": "Example Careers", "company": "Example Careers",
                         "source": "requests/html", "structured_source": False,
                         "working_location": "Remote", "compensation": "$1 - $2"},
                "questions": []}

    manifest = pc.process_urls([url], src, fetch)
    entry = manifest["entries"][0]
    assert entry["title"] == "Unknown Title"
    assert entry["field_status"]["title"] == pc.CAPTURE_FAILED
    assert "title capture failed" in entry["notes"]
    written = (src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
    assert "Role: Unknown Title" in written  # loud placeholder, never a branding string
    report = (tmp_path / "0 - Prep Report" / "prep-report.md").read_text(encoding="utf-8")
    assert "JOB TITLE could not be captured" in report


def test_company_as_role_normalizes_at_the_choke_point(tmp_path):
    """The FINAL artifact through process_urls: filename + Company:/Role: header."""
    src = _batch_source(tmp_path)
    html = _meta_html()

    def fetch(u):
        return {"ok": True, "title": "Meta Careers", "company": "Meta Careers",
                "body": af._html_to_text(html), "method": "playwright", "error": None,
                "meta": {"title": "Meta Careers", "company": "Meta Careers",
                         "source": "playwright/html", "structured_source": False,
                         "raw_html": html, "working_location": "Menlo Park, CA",
                         "compensation": None},
                "questions": []}

    manifest = pc.process_urls([META_URL], src, fetch)
    entry = manifest["entries"][0]
    assert entry["status"] == pc.USABLE
    assert (entry["company"], entry["title"]) == ("Meta", META_ROLE)
    assert Path(entry["output_path"]).name == META_FILE
    assert entry["field_status"]["title"] == pc.FOUND
    written = (src / META_FILE).read_text(encoding="utf-8")
    assert "Company: Meta" in written
    assert f"Role: {META_ROLE}" in written
    # The old wrong name must not exist anywhere in the batch.
    assert not (src / "meta-careers__meta-careers.txt").exists()


def test_html_comments_never_leak_into_the_captured_body_text():
    """Found while building the fixture: bs4 hands comment text back from get_text(), so a
    page with a big comment block leaked it straight into the captured job text."""
    body = _meta_body()
    assert "DURABLE REGRESSION FIXTURE" not in body
    assert body.splitlines()[0] == "Meta Careers"


# ===========================================================================
# The human-readable capture contract (JOB SNAPSHOT format, spec 2026-07-29).
# All fixtures below are synthetic/public-safe (revision #9).
# ===========================================================================
_SYNTH_BODY = ("About the role\nResponsibilities include shipping product.\n"
               "Qualifications: 5+ years of experience.\n"
               "The base salary range for this role is $150,000 - $180,000 annually.\n"
               + ("value delivered. " * 50))


def _synth_out(**overrides):
    kwargs = dict(meta={"title": "PM", "source": "greenhouse-boards-api",
                        "structured_source": True, "compensation": "USD 150,000–180,000",
                        "working_location": "Remote", "posted_date": "2026-06-13",
                        "updated_date": "2026-06-20", "posting_id": "12345",
                        "apply_url": "https://example.com/apply"},
                  methods_tried=["ats"], captured="2026-07-29T20:06:00+00:00")
    kwargs.update(overrides)
    return pc.build_output_text("https://example.com/job/1", "PM", "Acme",
                                _SYNTH_BODY, **kwargs)


_TITLE_CASE_LABELS = [
    "Company:", "Role:", "Job Posting URL:", "Job Posted At:", "Job Updated At:",
    "Employment:", "Work Arrangement:", "Working Location(s):", "Office Expectation:",
    "Base Salary:", "Additional Compensation:", "Benefits:",
    "Captured At:", "Application URL:", "Source:", "Posting ATS ID:", "Methods Checked:",
    "Verification:",
]


def test_every_field_label_is_title_case_and_present():
    out = _synth_out()
    for label in _TITLE_CASE_LABELS:
        assert f"\n{label}" in out or out.startswith(label), f"missing label: {label}"
    # None of the implementation-language leftovers survive.
    for gone in ("== NORMALIZED", "== APPLICATION QUESTIONS", "== EMPLOYER-PROVIDED",
                 "[found]", "[not posted]", "[capture failed]", "[capture_failed]",
                 "[conflicting]", "(verbatim)", "Employment Type:", "Workplace:",
                 "Completeness:", "(none kept)", "n/a"):
        assert gone not in out, f"legacy fragment survived: {gone}"


def test_sections_appear_in_the_exact_specified_order():
    out = _synth_out()
    order = ["JOB SNAPSHOT", "WORK DETAILS", "COMPENSATION",
             "APPLICATION QUESTIONS WORTH PREPARING",
             "--- JOB TEXT START ---", "--- JOB TEXT END ---", "ORIGINAL CAPTURE DETAILS"]
    positions = [out.index(s) for s in order]
    assert positions == sorted(positions)
    # Banner underlines match their banner text exactly.
    lines = out.splitlines()
    for banner, ch in [("JOB SNAPSHOT", "="), ("WORK DETAILS", "="), ("COMPENSATION", "="),
                       ("APPLICATION QUESTIONS WORTH PREPARING", "="),
                       ("ORIGINAL CAPTURE DETAILS", "-")]:
        i = lines.index(banner)
        assert lines[i + 1] == ch * len(banner), banner


def test_capture_details_sits_after_the_end_marker():
    out = _synth_out()
    assert out.index("ORIGINAL CAPTURE DETAILS") > out.index("--- JOB TEXT END ---")
    assert "LATEST CAPTURE DETAILS" not in out  # never on a first capture


def test_et_conversion_is_dst_aware_january_and_july():
    # July: UTC-4 (EDT).
    assert pc.capture_timestamp("2026-07-29T20:06:00+00:00") == "July 29, 2026 at 4:06 PM ET"
    # January: UTC-5 (EST) — same UTC wall time renders an hour earlier.
    assert pc.capture_timestamp("2026-01-29T20:06:00+00:00") == "January 29, 2026 at 3:06 PM ET"
    # Morning + midnight edges.
    assert pc.capture_timestamp("2026-07-29T04:30:00+00:00") == "July 29, 2026 at 12:30 AM ET"


def test_date_only_historical_captured_never_invents_a_time():
    assert pc.capture_timestamp("2026-07-29") == "July 29, 2026 — Time Unavailable"
    out = _synth_out(captured="2026-07-29")
    assert "Captured At: July 29, 2026 — Time Unavailable" in out
    assert "12:00 AM" not in out


def test_benefits_render_as_period_separated_short_sentences():
    out = _synth_out(meta={"title": "PM", "structured_source": True,
                           "compensation": "USD 150,000",
                           "working_location": "Remote",
                           "benefits": "Medical, dental, and vision insurance; "
                                       "Flexible paid time off; 401(k) self contribution"})
    assert ("Benefits: Medical, dental, and vision insurance. "
            "Flexible paid time off. 401(k) self contribution.") in out


def test_required_marker_sits_at_the_question_end_and_context_is_bracketed_lines():
    qs = [
        {"label": "Why do you want this role?", "type": "textarea", "required": True,
         "help": "2-3 sentences is plenty.", "name": "q1", "names": ["q1"], "options": []},
        {"label": "Pick a start month.", "type": "select", "required": False,
         "name": "q2", "names": ["q2"], "options": ["June", "July"]},
    ]
    out = _synth_out(questions=qs)
    assert "1. Why do you want this role? [Required]" in out
    assert "2. Pick a start month. [Optional]" in out
    # Bracketed context lines are SEPARATE indented lines, never inline.
    assert "\n   [Context: 2-3 sentences is plenty.]" in out
    assert '\n   [Options: "June" / "July"]' in out
    assert "[Required]\n" in out and "? [Required] " not in out


def test_no_questions_renders_none_found():
    out = _synth_out(questions=[])
    section = out.split("APPLICATION QUESTIONS WORTH PREPARING")[1].split("---")[0]
    assert "None Found." in section


def test_office_cadence_prose_fallback_shapes_named_days():
    body = ("About the role\nResponsibilities include shipping product.\n"
            "This role works onsite from our NYC or San Francisco hub location three "
            "days per week: Tuesday, Wednesday, Thursday.\n" + ("x " * 60))
    assert pc._mine_office_expectation(body) == "3 Days Per Week, Tuesday–Thursday"
    out = pc.build_output_text("http://x", "PM", "Acme", body,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 150,000",
                                     "working_location": "NYC; San Francisco"},
                               methods_tried=["ats"])
    assert "Office Expectation: 3 Days Per Week, Tuesday–Thursday" in out


def test_office_cadence_is_never_inferred_when_unstated():
    out = _synth_out()
    assert "Office Expectation: Not Specified" in out
    # Non-consecutive named days list, and open-ended minimums, keep their shape.
    assert pc._format_cadence("at least 2 days per week") == "At Least 2 Days Per Week"
    assert pc._format_cadence(
        "two days per week: Monday, Wednesday") == "2 Days Per Week, Monday, Wednesday"


def test_employment_full_time_exempt_mined_from_prose_when_structured_is_bare():
    body = ("About the role\nResponsibilities include shipping product.\n"
            "Full Time, Exempt\n" + ("x " * 60))
    out = pc.build_output_text("http://x", "PM", "Acme", body,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 150,000",
                                     "working_location": "Remote"},
                               methods_tried=["ats"])
    assert "Employment: Full Time, Exempt" in out
    # Structured CamelCase maps to readable Title Case.
    out2 = _synth_out(meta={"title": "PM", "structured_source": True,
                            "employment_type": "FullTime",
                            "compensation": "USD 150,000", "working_location": "Remote"})
    assert "Employment: Full Time" in out2
    # Marketing prose alone ("we're a full-time remote company") is never enough.
    assert pc._mine_employment("We love being a full-time remote company.") is None


def test_labeled_benefits_section_is_mined_into_sentences():
    body = ("About the role\nResponsibilities include shipping product.\n"
            "Full Time Employee Benefits:\n"
            "- Comprehensive health insurance\n"
            "- Flexible working hours\n"
            "- 401(k) with company match\n" + ("x " * 60))
    benefits, _e = af.mine_benefits_equity(body)
    assert benefits and "Comprehensive health insurance" in benefits
    out = pc.build_output_text("http://x", "PM", "Acme", body,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 150,000",
                                     "working_location": "Remote"},
                               methods_tried=["ats"])
    assert ("Benefits: Comprehensive health insurance. Flexible working hours. "
            "401(k) with company match.") in out


def test_base_salary_and_additional_compensation_stay_separated():
    body = ("About the role\nResponsibilities include shipping product.\n"
            "You may also be eligible for a discretionary bonus and equity.\n" + ("x " * 60))
    out = pc.build_output_text("http://x", "PM", "Acme", body,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 232,000–282,000",
                                     "working_location": "Remote"},
                               methods_tried=["ats"])
    comp_section = out.split("COMPENSATION")[1].split("APPLICATION QUESTIONS")[0]
    base = comp_section.split("Additional Compensation:")[0]
    assert "$232-282K" in base and "bonus" not in base.lower() and "equity" not in base.lower()
    assert ("Additional Compensation: Bonus and equity mentioned, but details "
            "not provided.") in out


def test_base_salary_multi_band_renders_abbreviated_bullets():
    out = _synth_out(meta={"title": "PM", "structured_source": True,
                           "compensation": "Zone A: $236K – $296K · Zone B: $213K – $266K",
                           "working_location": "Remote"},
                     field_status={"compensation": pc.FOUND,
                                   "working_location": pc.FOUND,
                                   "description": pc.FOUND, "conflicts": []})
    # Multiple geo/level ranges keep bullets, abbreviated thousands, no USD tag.
    assert "\n- Zone A: $236-296K\n" in out
    assert "\n- Zone B: $213-266K\n" in out
    assert "USD" not in out.split("COMPENSATION")[1].split("Additional")[0]


def test_body_is_preserved_byte_for_byte_between_the_markers():
    body = ("Odd   spacing\tand\ttabs\n\n\n== fake heading ==\nJob Posted At: 1999-01-01\n"
            "Responsibilities include everything.\n" + ("x " * 60))
    out = pc.build_output_text("http://x", "PM", "Acme", body,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 150,000",
                                     "working_location": "Remote"},
                               methods_tried=["ats"])
    assert pc.body_from_capture(out) == body


# ---- Re-fetch: LATEST CAPTURE DETAILS + best-verified merge -----------------
def _refetch_manifest(tmp_path, first_fetch, second_fetch):
    src = _batch_source(tmp_path)
    url = "https://example.com/job/refetch"
    pc.process_urls([url], src, first_fetch)
    manifest = pc.process_urls([url], src, second_fetch, force=True)
    return src, manifest["entries"][0]


def _fetch_result(body, comp="USD 150,000", posted="2026-06-13"):
    def fetch(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": body,
                "method": "ats", "error": None,
                "meta": {"title": "PM", "source": "greenhouse-boards-api",
                         "structured_source": True, "compensation": comp,
                         "working_location": "Remote", "posted_date": posted},
                "questions": []}
    return fetch


def test_first_capture_has_no_update_details_and_a_refetch_gets_one(tmp_path):
    src = _batch_source(tmp_path)
    url = "https://example.com/job/one"
    manifest = pc.process_urls([url], src, _fetch_result(_SYNTH_BODY))
    first = (src / Path(manifest["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    assert "LATEST CAPTURE DETAILS" not in first
    original_captured_line = next(l for l in first.splitlines() if l.startswith("Captured At:"))
    # Verified re-fetch of the SAME url -> UPDATE DETAILS present, original Captured kept.
    manifest2 = pc.process_urls([url], src, _fetch_result(_SYNTH_BODY), force=True)
    entry = manifest2["entries"][0]
    second = (src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
    assert "LATEST CAPTURE DETAILS" in second
    assert second.index("LATEST CAPTURE DETAILS") > second.index("ORIGINAL CAPTURE DETAILS")
    assert original_captured_line in second          # original Captured never overwritten
    assert "Captured At:" in second.split("LATEST CAPTURE DETAILS")[1]
    assert "Additional Notes: No material changes detected." in second
    # The manifest carries the capture-history record for future re-fetches.
    assert entry["capture_history"] and entry["capture_history"][0]["fetched_at"]


def test_material_content_diff_not_length_drives_additional_notes(tmp_path):
    old = ("About the role\nResponsibilities include shipping product.\n"
           "The base salary range for this role is $150,000 - $180,000 annually.\n"
           + ("filler words here. " * 40))
    # Same material content, VERY different length (chrome churn) -> no material change.
    chrome_only = old + "\nCookie notice\nSite map\nFollow us on social media\n" + ("nav " * 200)
    assert pc.material_change_notes(old, chrome_only) == "No material changes detected."
    # Nearly identical length but the salary changed -> material change, named.
    edited = old.replace("$150,000 - $180,000", "$160,000 - $190,000")
    notes = pc.material_change_notes(old, edited)
    assert notes == "Employer materially updated the posting."
    # End-to-end through a re-fetch.
    _src, entry = _refetch_manifest(
        tmp_path, _fetch_result(old), _fetch_result(edited, comp="USD 160,000–190,000"))
    out = (_src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
    assert "Employer materially updated the posting." in out


def test_best_field_merge_never_degrades_a_better_body(tmp_path):
    good = ("About the role\nResponsibilities include shipping product.\n"
            "Qualifications: 5+ years of experience.\n"
            "The base salary range for this role is $150,000 - $180,000 annually.\n"
            + ("value delivered. " * 60))
    shell = "Please enable JavaScript to continue. Sign in to apply."
    src, entry = _refetch_manifest(tmp_path, _fetch_result(good), _fetch_result(shell))
    assert entry["status"] == pc.USABLE
    out = (src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
    # The better existing body survives the degraded re-fetch, and the notes say so.
    assert pc.body_from_capture(out) == good
    assert "kept the prior job text" in entry["notes"]
    assert "prior job text was kept" in out
    # Posting dates verified earlier survive a re-fetch whose source lost them.
    src2 = _batch_source(tmp_path / "b2")
    url = "https://example.com/job/dates"
    pc.process_urls([url], src2, _fetch_result(good, posted="2026-06-13"))
    m2 = pc.process_urls([url], src2, _fetch_result(good, posted=None), force=True)
    assert m2["entries"][0]["posted_date"] == "2026-06-13"
    out2 = (src2 / Path(m2["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    assert "Job Posted At: June 13, 2026" in out2


# ===========================================================================
# Acceptance-standard fixes (2026-07-29 review of the first live re-capture).
# All synthetic fixtures — no real capture data.
# ===========================================================================
_GROW_SHAPED_BENEFITS_BODY = (
    "About the role\nResponsibilities include shipping product.\n"
    "Qualifications: 5+ years of experience.\n\n"
    "Full Time Employee Benefits:\n\n"
    "- Comprehensive Health Coverage: Medical, dental, and vision insurance, plus life "
    "and disability coverage.\n\n"
    "- Parental Leave & Family Support: Up to 18 weeks of paid parental leave and a "
    "new-child stipend.\n\n"
    "- Financial Wellness: 401(k) program and equity opportunities.\n\n"
    "- Time Off: Flexible PTO, 12 paid holidays, and a winter break week.\n\n"
    "- Meals & Home Office Support: Home-office, meal, development, and wellness stipends.\n\n"
    "- Mental & Physical Health: No-cost therapy and wellness app memberships.\n\n"
    "- Perks: Pet insurance discounts and commuter benefits.\n\n"
    "How to apply:\nSend us your application.\n" + ("x " * 60))


def test_whole_labeled_benefits_section_is_summarized_not_truncated():
    """Defect 1: blank lines between bullets used to truncate a 7-bullet labeled
    benefits section to its FIRST bullet. The whole section must be summarized as
    period-separated sentences, label prefixes stripped, no bullet markers."""
    benefits, _e = af.mine_benefits_equity(_GROW_SHAPED_BENEFITS_BODY)
    out = pc.build_output_text("http://x", "PM", "Acme", _GROW_SHAPED_BENEFITS_BODY,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 150,000",
                                     "working_location": "Remote"},
                               methods_tried=["ats"])
    line = next(l for l in out.splitlines() if l.startswith("Benefits:"))
    # Every bullet's content is represented, not just the first.
    for needle in ("Medical, dental, and vision insurance",
                   "18 weeks of paid parental leave",
                   "401(k) program",
                   "Flexible PTO, 12 paid holidays",
                   "wellness stipends",
                   "No-cost therapy"):
        assert needle in line, needle
    # EVERY bullet's label prefix is stripped — including multi-word labels
    # containing `&` — along with bullet markers; sentences are period-separated.
    for gone in ("Comprehensive Health Coverage:", "Parental Leave & Family Support:",
                 "Financial Wellness:", "Meals & Home Office Support:",
                 "Mental & Physical Health:", "Perks:", "- "):
        assert gone not in line, gone
    assert line.count(". ") >= 4 and line.endswith(".")
    # The next section's content never bleeds in.
    assert "Send us your application" not in line


def test_benefits_summary_truncates_at_sentence_boundaries_keeping_distinctive_details():
    """Live-run defects (second review): the summary ended `Mental & Physical He…`
    — a hard char cap chopping mid-word — and the cut dropped the distinctive
    no-cost-therapy detail while generic stipend wording survived. An over-budget
    summary must drop whole LEAST-DISTINCTIVE sentences, never slice characters."""
    long_body = (
        "About the role\nResponsibilities include shipping product.\n\n"
        "Full Time Employee Benefits:\n\n"
        "- Comprehensive Health Coverage: Medical, dental, and vision insurance, plus "
        "life and disability coverage for you and your dependents.\n\n"
        "- Parental Leave & Family Support: Up to 18 weeks of paid parental leave and a "
        "new child stipend to support your growing family.\n\n"
        "- Meals & Home Office Support: Stipends for home office setup and ongoing funds "
        "for meals, with tailored perks for both remote and in-office employees.\n\n"
        "- Time Off: Flexible PTO, 12 paid holidays, and a full winter break week.\n\n"
        "- Growth: Annual stipends to put towards personal and professional growth "
        "opportunities of your choosing.\n\n"
        "- Mental & Physical Health: No-cost therapy through the employer's platform "
        "and wellness-app memberships.\n\n"
        "- Perks: Tailored perks, wellness discounts, and other supportive offerings.\n\n"
        + ("x " * 60))
    out = pc.build_output_text("http://x", "PM", "Acme", long_body,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 150,000",
                                     "working_location": "Remote"},
                               methods_tried=["ats"])
    line = next(l for l in out.splitlines() if l.startswith("Benefits:"))
    # Never a mid-word cut, never an ellipsis; always ends at a sentence boundary.
    assert "…" not in line
    assert line.endswith(".")
    assert "He." not in line and "He " not in line  # the observed mid-word chop shape
    # The budget is enforced by dropping whole sentences...
    assert len(line) <= len("Benefits: ") + 500
    # ...and the distinctive concrete detail SURVIVES while generic perk wording drops.
    assert "No-cost therapy through the employer's platform" in line
    assert "Tailored perks, wellness discounts" not in line
    # Every sentence in the output is one of the cleaned source sentences, whole.
    for sentence in line[len("Benefits: "):].rstrip(".").split(". "):
        assert sentence in long_body or sentence[0].upper() + sentence[1:] in long_body


def test_mid_sentence_colon_clauses_are_not_stripped_as_labels():
    """The label strip applies only at the START of a bullet — a mid-sentence
    `Note:`-style clause is content, not a label."""
    assert pc._strip_bullet_and_label(
        "- Health Coverage: Full medical. Note: details vary by state."
    ) == "Full medical. Note: details vary by state."
    assert pc._strip_bullet_and_label(
        "Coverage begins day one. Note: details vary by state."
    ) == "Coverage begins day one. Note: details vary by state."


def test_additional_compensation_never_emits_bullet_junk():
    """Defect 2: `Additional Compensation: - Financial Wellness: 401(k) program and
    equity opportunities.` — a raw benefits bullet. Required: clean comp-only
    wording; 401(k) stays a benefit."""
    out = pc.build_output_text("http://x", "PM", "Acme", _GROW_SHAPED_BENEFITS_BODY,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 150,000",
                                     "working_location": "Remote"},
                               methods_tried=["ats"])
    line = next(l for l in out.splitlines() if l.startswith("Additional Compensation:"))
    assert line == "Additional Compensation: Equity Opportunities."
    # 401(k) belongs in Benefits (and equity is removed from that benefits item).
    bline = next(l for l in out.splitlines() if l.startswith("Benefits:"))
    assert "401(k) program" in bline and "equity" not in bline.lower()
    # A real grant description still passes through, cleaned of bullets/labels.
    body2 = ("About the role\nResponsibilities include shipping product.\n"
             "- Equity: This role includes an equity grant of 4,000 restricted stock "
             "units vesting over 4 years.\n" + ("x " * 60))
    out2 = pc.build_output_text("http://x", "PM", "Acme", body2,
                                meta={"title": "PM", "structured_source": True,
                                      "compensation": "USD 150,000",
                                      "working_location": "Remote"},
                                methods_tried=["ats"])
    line2 = next(l for l in out2.splitlines() if l.startswith("Additional Compensation:"))
    assert "4,000 restricted stock units" in line2
    assert ": -" not in line2 and "Equity: This" not in line2


def test_capture_update_details_carries_the_new_fetch_fields(tmp_path):
    """Defect 3: the UPDATE block must carry Re-Captured, Source, Posting ATS ID,
    Methods Checked, Verification, Additional Notes — describing the NEW fetch —
    while ORIGINAL CAPTURE DETAILS keeps describing the ORIGINAL capture."""
    src = _batch_source(tmp_path)
    url = "https://example.com/job/update-fields"

    def first(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": _SYNTH_BODY,
                "method": "ats", "error": None,
                "meta": {"title": "PM", "source": "greenhouse-boards-api",
                         "structured_source": True, "compensation": "USD 150,000",
                         "working_location": "Remote", "posting_id": "gh-1"},
                "questions": []}

    def second(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": _SYNTH_BODY,
                "method": "ats", "error": None,
                "meta": {"title": "PM", "source": "ashby-posting-api",
                         "structured_source": True, "compensation": "USD 150,000",
                         "working_location": "Remote", "posting_id": "ashby-2"},
                "questions": []}

    pc.process_urls([url], src, first)
    manifest = pc.process_urls([url], src, second, force=True)
    out = (src / Path(manifest["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    details, update = out.split("LATEST CAPTURE DETAILS")
    # Original capture's identity stays in ORIGINAL CAPTURE DETAILS.
    assert "Source: Greenhouse" in details and "Posting ATS ID: gh-1" in details
    # The new fetch's identity lives in the UPDATE block, fields in spec order.
    labels = ["Captured At:", "Source:", "Posting ATS ID:", "Methods Checked:",
              "Verification:", "Additional Notes:"]
    positions = [update.index(lbl) for lbl in labels]
    assert positions == sorted(positions)
    assert "Source: Ashby" in update and "Posting ATS ID: ashby-2" in update
    assert "Verification: Job Description ✓" in update


def test_additional_notes_compare_snapshot_fields_not_only_the_body(tmp_path):
    """Defect 4: a re-capture that ADDED the posting date and CORRECTED employment /
    cadence / benefits reported `No Material Changes Detected.` because only the
    body was compared. The notes must diff the snapshot FIELDS too."""
    src = _batch_source(tmp_path)
    url = "https://example.com/job/field-notes"
    thin_meta = {"title": "PM", "source": "requests/html", "structured_source": True,
                 "compensation": "USD 182,000-227,000", "working_location": "Remote"}
    rich_meta = {"title": "PM", "source": "ashby-posting-api", "structured_source": True,
                 "compensation": "USD 182,000-227,000", "working_location": "Remote",
                 "employment_type": "FullTime", "posted_date": "2026-06-13"}
    body_rich = ("About the role\nResponsibilities include shipping product.\n"
                 "Full Time, Exempt\n"
                 "Onsite three days per week: Tuesday, Wednesday, Thursday.\n"
                 + ("value delivered. " * 60))

    def first(u):
        return {"ok": True, "title": "PM", "company": "Acme",
                "body": "About the role\nResponsibilities include shipping product.\n"
                        + ("value delivered. " * 60),
                "method": "requests", "error": None, "meta": dict(thin_meta), "questions": []}

    def second(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": body_rich,
                "method": "ats", "error": None, "meta": dict(rich_meta), "questions": []}

    pc.process_urls([url], src, first)
    manifest = pc.process_urls([url], src, second, force=True)
    out = (src / Path(manifest["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    notes = next(l for l in out.splitlines() if l.startswith("Additional Notes:"))
    assert "No material changes detected." not in notes
    assert "Added the" in notes
    assert "employer's posting date" in notes
    assert "employment type" in notes
    assert "office expectation" in notes


def test_field_notes_read_a_legacy_format_prior_capture():
    """The field diff must parse LEGACY `== NORMALIZED ==` labels too, so a
    legacy-format prior capture compares faithfully — formatting drift alone
    (FullTime vs Full Time, long vs short metro names) is NOT a correction."""
    legacy_prior = (
        "URL: https://example.com/job/1\n"
        "Application URL: https://example.com/job/1\n"
        "Company: Acme\nRole: PM\n"
        "Source: ashby-posting-api · Posting ID: a1 · Captured: 2026-07-01 · Methods tried: ats\n\n"
        "== NORMALIZED (for vetting) ==\n"
        "Employment Type: FullTime\n"
        "Workplace: Hybrid\n"
        "Working Location: New York City; San Francisco   [found]\n"
        "Compensation: USD 182,000-227,000   [found]\n"
        "Benefits: Not posted\n"
        "Equity: Not posted\n\n"
        "--- JOB TEXT START ---\n\nAbout the role\nResponsibilities include shipping.\n\n"
        "--- JOB TEXT END ---\n")
    same_new = pc.build_output_text(
        "https://example.com/job/1", "PM", "Acme",
        "About the role\nResponsibilities include shipping.",
        meta={"title": "PM", "structured_source": True, "employment_type": "FullTime",
              "compensation": "USD 182,000-227,000", "workplace": "Hybrid",
              "working_location": "New York City; San Francisco"},
        methods_tried=["ats"])
    # Identical content, different formatting -> no false "corrected".
    notes = pc.capture_update_notes(legacy_prior, same_new)
    assert "Corrected" not in notes
    # A REAL employment correction against the legacy header is detected.
    corrected_new = pc.build_output_text(
        "https://example.com/job/1", "PM", "Acme",
        "About the role\nResponsibilities include shipping.\nFull Time, Exempt\n",
        meta={"title": "PM", "structured_source": True,
              "compensation": "USD 182,000-227,000", "workplace": "Hybrid",
              "working_location": "New York City; San Francisco"},
        methods_tried=["ats"])
    notes2 = pc.capture_update_notes(legacy_prior, corrected_new)
    assert "Corrected the" in notes2 and "employment type" in notes2
    # No prior text at all keeps the honest sentence.
    assert pc.capture_update_notes(None, same_new) == \
        "Previous capture was not available for comparison."


def test_working_locations_render_as_short_metro_or_list():
    """Defect 5: multi-city lists render `NYC or SF` style — short canon names,
    Title Case Or, deduped after canonicalization."""
    out = _synth_out(meta={"title": "PM", "structured_source": True,
                           "compensation": "USD 150,000",
                           "working_location": "New York City; San Francisco"})
    assert "Working Location(s): NYC or SF" in out
    # Dedupe after canonicalization; unknown cities pass through verbatim.
    assert pc._format_working_locations(
        "New York, NY; New York City; Austin, TX") == "NYC or Austin"
    # Single values (Remote / one city) stay simple.
    assert pc._format_working_locations("Remote") == "Remote"
    assert pc._format_working_locations("San Francisco, CA") == "SF"


def test_base_salary_annual_range_renders_en_dash_and_annually():
    """Revised spec: `Base Salary: $182-227K Annually` — inline single range,
    abbreviated thousands, `Annually` only when the employer's wording states it."""
    out = _synth_out(meta={"title": "PM", "structured_source": True,
                           "compensation": "$182,000 - $227,000",
                           "compensation_raw": "The base salary range for this role is "
                                               "$182,000 - $227,000 annually.",
                           "working_location": "Remote"},
                     field_status={"compensation": pc.FOUND, "working_location": pc.FOUND,
                                   "description": pc.FOUND, "conflicts": []})
    assert "Base Salary: $182-227K Annually\n" in out
    # No annual statement anywhere -> never inferred.
    out2 = _synth_out(meta={"title": "PM", "structured_source": True,
                            "compensation": "$182,000 - $227,000",
                            "working_location": "Remote"},
                      field_status={"compensation": pc.FOUND, "working_location": pc.FOUND,
                                    "description": pc.FOUND, "conflicts": []})
    assert "Base Salary: $182-227K\n" in out2 and "Annually" not in out2
    # An hourly figure never gains "Annually".
    out3 = _synth_out(meta={"title": "PM", "structured_source": True,
                            "compensation": "$27 - $44/hour",
                            "compensation_raw": "annual reviews",
                            "working_location": "Remote"},
                      field_status={"compensation": pc.FOUND, "working_location": pc.FOUND,
                                    "description": pc.FOUND, "conflicts": []})
    assert "Annually" not in out3.split("COMPENSATION")[1].split("APPLICATION")[0]


# ===========================================================================
# Third live-run review (Greenhouse path): partial-run manifest preservation,
# generic comp-label stripping, and flat city-blob rendering.
# ===========================================================================
def test_partial_run_carries_forward_untouched_manifest_entries(tmp_path):
    """ENGINE BUG: process_urls rebuilt the manifest from only THIS run's input,
    so prepping one job silently wiped every other job's entry — history,
    field_status, posted dates, capture_history all lost, and the wiped job's
    next re-fetch was treated as a FIRST capture. Entries whose URL is not in
    this run's input must survive verbatim."""
    src = _batch_source(tmp_path)
    url_a = "https://example.com/job/alpha"
    url_b = "https://example.com/job/beta"

    def fetch_both(u):
        name = "Alpha" if "alpha" in u else "Beta"
        return {"ok": True, "title": f"PM {name}", "company": name, "body": _SYNTH_BODY,
                "method": "ats", "error": None,
                "meta": {"title": f"PM {name}", "source": "greenhouse-boards-api",
                         "structured_source": True, "compensation": "USD 150,000",
                         "working_location": "Remote", "posted_date": "2026-06-13",
                         "posting_id": f"{name.lower()}-1"},
                "questions": []}

    manifest1 = pc.process_urls([url_a, url_b], src, fetch_both)
    assert len(manifest1["entries"]) == 2
    beta_before = next(e for e in manifest1["entries"] if e["original_url"] == url_b)
    alpha_file = Path(next(e for e in manifest1["entries"]
                           if e["original_url"] == url_a)["output_path"]).name
    original_captured_line = next(
        l for l in (src / alpha_file).read_text(encoding="utf-8").splitlines()
        if l.startswith("Captured At:"))

    # A partial run over ONLY alpha (force -> genuine re-fetch).
    manifest2 = pc.process_urls([url_a], src, fetch_both, force=True)
    assert len(manifest2["entries"]) == 2, "beta's entry must not be wiped"
    beta_after = next(e for e in manifest2["entries"] if e["original_url"] == url_b)
    assert beta_after == beta_before, "the untouched entry must survive VERBATIM"
    assert (src / Path(beta_after["output_path"]).name).exists()
    # And alpha was treated as a RE-fetch: update block present, original Captured
    # preserved, capture_history appended.
    alpha_after = next(e for e in manifest2["entries"] if e["original_url"] == url_a)
    assert alpha_after["capture_history"] and alpha_after["capture_history"][0]["fetched_at"]
    out = (src / Path(alpha_after["output_path"]).name).read_text(encoding="utf-8")
    assert "LATEST CAPTURE DETAILS" in out
    assert original_captured_line in out
    # Counts cover the whole batch, not just this run's input.
    assert manifest2["counts"][pc.USABLE] == 2


@pytest.mark.parametrize("raw,expected", [
    # The observed Airbnb defect: raw ATS label + bare currency-code range.
    ("Pay Range: USD 232,000–282,000", "$232-282K"),
    ("Salary Range: USD $232,000 - $282,000", "$232-282K"),
    ("Compensation: $232,000 - 282,000", "$232-282K"),
    ("Base Pay: USD 232,000 to 282,000", "$232-282K"),
    # No label at all — still normalized.
    ("USD 232,000-282,000", "$232-282K"),
])
def test_base_salary_generic_labels_strip_and_currency_normalizes(raw, expected):
    out = _synth_out(meta={"title": "PM", "structured_source": True,
                           "compensation": raw, "working_location": "Remote"},
                     field_status={"compensation": pc.FOUND, "working_location": pc.FOUND,
                                   "description": pc.FOUND, "conflicts": []})
    # A single range renders INLINE — no one-item bullet list, $ implies USD.
    assert f"Base Salary: {expected}\n" in out, out.split("COMPENSATION")[1].split("Additional")[0]
    assert "Pay Range:" not in out and "USD" not in out.split("COMPENSATION")[1].split("Additional")[0]
    assert "Annually" not in out  # never inferred annual


def test_base_salary_geo_and_level_labels_survive():
    """Only GENERIC comp labels strip — geo/level band labels are meaningful."""
    out = _synth_out(meta={"title": "PM", "structured_source": True,
                           "compensation": "Zone A: SF Bay Area / NYC $236K – $296K · "
                                           "US Tier 1: $174,000 - $290,000",
                           "working_location": "Remote"},
                     field_status={"compensation": pc.FOUND, "working_location": pc.FOUND,
                                   "description": pc.FOUND, "conflicts": []})
    assert "\n- Zone A: SF Bay Area / NYC $236-296K\n" in out
    assert "\n- US Tier 1: $174-290K\n" in out


def test_flat_city_state_blob_renders_short_metro_or_join():
    """Defect 3: a flat Greenhouse offices blob (`San Francisco, CA, New York, NY`)
    must render `SF or NYC` — employer order preserved, never re-sorted."""
    out = _synth_out(meta={"title": "PM", "structured_source": True,
                           "compensation": "USD 150,000",
                           "working_location": "San Francisco, CA, New York, NY"})
    assert "Working Location(s): SF or NYC" in out
    # Employer order is preserved (NYC-first stays NYC-first).
    assert pc._format_working_locations("New York, NY, San Francisco, CA") == "NYC or SF"
    # Unknown cities in a blob pass through verbatim.
    assert pc._format_working_locations(
        "San Francisco, CA, Bozeman, MT") == "SF or Bozeman, MT"
    # A single City, ST is NOT a blob — it renders as one place (short-canon name
    # when known, verbatim otherwise).
    assert pc._format_working_locations("Austin, TX") == "Austin"
    assert pc._format_working_locations("Bozeman, MT") == "Bozeman, MT"


def test_a_genuine_employer_edit_does_replace_the_body(tmp_path):
    old = ("About the role\nResponsibilities include shipping product.\n"
           "The base salary range for this role is $150,000 - $180,000 annually.\n"
           + ("value delivered. " * 60))
    new = old.replace("shipping product", "shipping product and running discovery")
    src, entry = _refetch_manifest(tmp_path, _fetch_result(old), _fetch_result(new))
    out = (src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
    assert pc.body_from_capture(out) == new  # a real edit is not "degradation"


# ===========================================================================
# Second approval round (2026-07-29): location preference, simplified comp
# layout, ORIGINAL/LATEST capture sections, the durable capture-history
# registry (ten requirements), backfill, HTML list-structure preservation,
# and normalized body-comparison semantics. All fixtures synthetic.
# ===========================================================================
def test_location_preference_field_emitted_only_when_stated():
    body = ("About the role\nResponsibilities include shipping product.\n"
            "Due to the nature of this position, there is a strong preference for the "
            "successful applicant to be based in San Francisco, CA ir New York, NY.\n"
            + ("x " * 60))
    out = pc.build_output_text("http://x", "PM", "Acme", body,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 232,000-282,000",
                                     "working_location": "San Francisco, CA; New York, NY"},
                               methods_tried=["ats"])
    # Distinct field, right after Working Location(s); obvious "ir" typo normalized;
    # cities in canonical short form; stays a PREFERENCE (never a requirement).
    assert "Working Location(s): SF or NYC" in out
    assert ("Location Preference: Strong preference for the successful applicant "
            "to be based in SF or NYC." in out)
    lines = out.splitlines()
    assert lines[lines.index("Working Location(s): SF or NYC") + 1].startswith(
        "Location Preference:")
    # Never folded into Work Arrangement / Office Expectation.
    assert "Office Expectation: Not Specified" in out
    # The employer's full sentence stays in the body, verbatim (typo included).
    assert "San Francisco, CA ir New York, NY" in pc.body_from_capture(out)
    # No stated preference -> the line is omitted entirely.
    out2 = _synth_out()
    assert "Location Preference:" not in out2


def test_compensation_section_matches_the_approved_layout():
    """Her exact target shape: inline single range, blank line between fields,
    sentence-case values."""
    body = ("About the role\nResponsibilities include shipping product.\n"
            "You may also be eligible for bonus, equity, benefits, and Employee "
            "Travel Credits.\n" + ("x " * 60))
    out = pc.build_output_text("http://x", "PM", "Acme", body,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 232,000-282,000",
                                     "working_location": "Remote"},
                               methods_tried=["ats"])
    assert ("COMPENSATION\n"
            "============\n"
            "Base Salary: $232-282K\n"
            "\n"
            "Additional Compensation: Bonus, equity, and Employee Travel Credits "
            "mentioned, but details not provided.\n"
            "\n"
            "Benefits: Mentioned, but details not provided.\n") in out


def test_original_and_latest_capture_sections(tmp_path):
    """First-and-only capture -> ORIGINAL CAPTURE DETAILS only. A later successful
    fetch adds LATEST CAPTURE DETAILS; `Captured At:` labels both; `Re-Captured`
    is gone."""
    src = _batch_source(tmp_path)
    url = "https://example.com/job/sections"
    m1 = pc.process_urls([url], src, _fetch_result(_SYNTH_BODY))
    first = (src / Path(m1["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    assert "ORIGINAL CAPTURE DETAILS\n------------------------" in first
    assert "LATEST CAPTURE DETAILS" not in first
    assert first.count("Captured At:") == 1
    m2 = pc.process_urls([url], src, _fetch_result(_SYNTH_BODY), force=True)
    second = (src / Path(m2["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    assert "LATEST CAPTURE DETAILS\n----------------------" in second
    assert second.index("ORIGINAL CAPTURE DETAILS") < second.index("LATEST CAPTURE DETAILS")
    assert second.count("Captured At:") == 2
    assert "Re-Captured" not in second


# ---- The durable capture-history registry: the ten requirements --------------
def _registry(tmp_path):
    return tmp_path / "registry.json"


def test_registry_req1_original_is_immutable_and_req2_every_fetch_appends(tmp_path):
    src = _batch_source(tmp_path)
    url = "https://boards.greenhouse.io/acme/jobs/123456"
    reg_path = _registry(tmp_path)
    pc.process_urls([url], src, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    reg = pc.load_capture_registry(reg_path)
    key = "greenhouse:acme:123456"
    original = dict(reg["postings"][key]["original_capture"])
    assert len(reg["postings"][key]["history"]) == 1
    # Requirement 2: a second successful fetch appends an event...
    pc.process_urls([url], src, _fetch_result(_SYNTH_BODY), force=True,
                    registry_path=reg_path)
    reg2 = pc.load_capture_registry(reg_path)
    assert len(reg2["postings"][key]["history"]) == 2
    # Requirement 1: ...and the original is byte-identical (immutable).
    assert reg2["postings"][key]["original_capture"] == original


def test_registry_req3_and_req7_rerender_is_not_a_capture(tmp_path):
    src = _batch_source(tmp_path)
    url = "https://boards.greenhouse.io/acme/jobs/123456"
    reg_path = _registry(tmp_path)
    pc.process_urls([url], src, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    before = reg_path.read_text(encoding="utf-8")
    # Local re-render / preview generation without network (build_output_text)
    # never touches the registry; reformatting changes neither timestamp.
    pc.build_output_text(url, "PM", "Acme", _SYNTH_BODY,
                         meta={"title": "PM", "structured_source": True,
                               "compensation": "USD 150,000",
                               "working_location": "Remote"},
                         methods_tried=["ats"])
    assert reg_path.read_text(encoding="utf-8") == before


def test_registry_req4_skipped_urls_are_not_captures(tmp_path):
    src = _batch_source(tmp_path)
    url = "https://boards.greenhouse.io/acme/jobs/123456"
    reg_path = _registry(tmp_path)
    pc.process_urls([url], src, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    # A plain re-run (no force) carries the usable entry forward — no fetch, no event.
    pc.process_urls([url], src, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    reg = pc.load_capture_registry(reg_path)
    assert len(reg["postings"]["greenhouse:acme:123456"]["history"]) == 1


def _failing_fetch(u):
    return {"ok": False, "title": None, "company": None, "body": "",
            "method": "requests", "error": "boom", "meta": {}, "questions": []}


def test_registry_req5_req6_failed_fetch_never_replaces_latest(tmp_path):
    src = _batch_source(tmp_path)
    url = "https://boards.greenhouse.io/acme/jobs/123456"
    reg_path = _registry(tmp_path)
    pc.process_urls([url], src, _fetch_result(_SYNTH_BODY, comp="USD 150,000"),
                    registry_path=reg_path)
    key = "greenhouse:acme:123456"
    latest1 = pc.load_capture_registry(reg_path)["postings"][key]["latest_capture"]
    # A failed re-fetch appends history but NEVER replaces Latest...
    pc.process_urls([url], src, _failing_fetch, force=True, registry_path=reg_path)
    reg = pc.load_capture_registry(reg_path)
    assert reg["postings"][key]["latest_capture"] == latest1
    assert reg["postings"][key]["history"][-1]["ok"] is False
    # ...and Latest = the most recent SUCCESSFUL retrieval (unit-level, with
    # explicit distinct timestamps: success, fail, success).
    reg = {"schema_version": 1, "postings": {}}
    pc.record_capture_event(reg, "k", {"fetched_at": "2026-07-01T10:00:00+00:00",
                                       "url": "u1", "ok": True}, success=True)
    pc.record_capture_event(reg, "k", {"fetched_at": "2026-07-02T10:00:00+00:00",
                                       "url": "u1", "ok": False}, success=False)
    assert reg["postings"]["k"]["latest_capture"]["fetched_at"] == "2026-07-01T10:00:00+00:00"
    pc.record_capture_event(reg, "k", {"fetched_at": "2026-07-03T10:00:00+00:00",
                                       "url": "u1", "ok": True}, success=True)
    assert reg["postings"]["k"]["latest_capture"]["fetched_at"] == "2026-07-03T10:00:00+00:00"
    assert reg["postings"]["k"]["original_capture"]["fetched_at"] == "2026-07-01T10:00:00+00:00"
    assert len(reg["postings"]["k"]["history"]) == 3


def test_registry_req8_manifest_is_a_mirror_not_the_source_of_truth(tmp_path):
    src = _batch_source(tmp_path)
    url = "https://boards.greenhouse.io/acme/jobs/123456"
    reg_path = _registry(tmp_path)
    m1 = pc.process_urls([url], src, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    first = (src / Path(m1["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    original_line = next(l for l in first.splitlines() if l.startswith("Captured At:"))
    # Destroy the batch manifest (and the prior file): the registry still proves
    # the earlier capture, so the re-fetch gets a LATEST section with the
    # ORIGINAL Captured At intact.
    (tmp_path / "0 - Prep Report" / "prep-manifest.json").unlink()
    m2 = pc.process_urls([url], src, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    out = (src / Path(m2["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    assert "LATEST CAPTURE DETAILS" in out
    assert original_line in out


def test_registry_req9_url_aliases_resolve_to_one_history(tmp_path):
    src = _batch_source(tmp_path)
    reg_path = _registry(tmp_path)
    aliases = [
        "https://boards.greenhouse.io/acme/jobs/123456?gh_src=x",
        "https://job-boards.greenhouse.io/acme/jobs/123456",
        "https://careers.acme.com/positions/123456",       # employer deep link
        "https://www.acmecareers.com/jobs/?gh_jid=123456",  # listing + gh_jid
    ]
    for i, u in enumerate(aliases):
        src_i = _batch_source(tmp_path / f"b{i}")
        pc.process_urls([u], src_i, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    reg = pc.load_capture_registry(reg_path)
    assert list(reg["postings"].keys()) == ["greenhouse:acme:123456"]
    assert len(reg["postings"]["greenhouse:acme:123456"]["history"]) == len(aliases)


def test_registry_req10_partial_runs_preserve_other_jobs_history(tmp_path):
    src = _batch_source(tmp_path)
    reg_path = _registry(tmp_path)
    url_a = "https://boards.greenhouse.io/acme/jobs/111111"
    url_b = "https://boards.greenhouse.io/acme/jobs/222222"
    pc.process_urls([url_a, url_b], src, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    b_before = pc.load_capture_registry(reg_path)["postings"]["greenhouse:acme:222222"]
    pc.process_urls([url_a], src, _fetch_result(_SYNTH_BODY), force=True,
                    registry_path=reg_path)
    reg = pc.load_capture_registry(reg_path)
    assert reg["postings"]["greenhouse:acme:222222"] == b_before
    assert len(reg["postings"]["greenhouse:acme:111111"]["history"]) == 2


def test_registry_cross_batch_refetch_keeps_the_first_batchs_original(tmp_path):
    """The live defect: the same posting fetched in a NEW batch must render the
    FIRST batch's Captured At as ORIGINAL, via the registry (no shared manifest)."""
    reg_path = _registry(tmp_path)
    src1 = _batch_source(tmp_path / "batch1")
    url = "https://boards.greenhouse.io/acme/jobs/123456"
    m1 = pc.process_urls([url], src1, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    first = (src1 / Path(m1["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    original_line = next(l for l in first.splitlines() if l.startswith("Captured At:"))
    src2 = _batch_source(tmp_path / "batch2")
    m2 = pc.process_urls([url], src2, _fetch_result(_SYNTH_BODY), registry_path=reg_path)
    out = (src2 / Path(m2["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    assert "LATEST CAPTURE DETAILS" in out
    assert original_line in out.split("LATEST CAPTURE DETAILS")[0]


# ---- Backfill ----------------------------------------------------------------
def _write_manifest(root, batch, entries):
    d = root / batch / "0 - Prep Report"
    d.mkdir(parents=True, exist_ok=True)
    (d / "prep-manifest.json").write_text(
        json.dumps({"schema_version": 1, "batch": batch, "entries": entries}),
        encoding="utf-8")


def test_backfill_canonicalizes_raw_employer_url_keys_and_picks_the_earliest(tmp_path):
    """The alias-resolution trap: the OLDEST manifests key a posting under the raw
    employer URL while newer ones use the ATS identity. All forms must land under
    ONE key, with the original on the EARLIEST reliable timestamp."""
    import backfill_capture_registry as bf
    root = tmp_path / "reviews"
    _write_manifest(root, "archive/07-01-26", [
        {"original_url": "https://careers.acme.com/positions/123456",
         "normalized_url": "https://careers.acme.com/positions/123456",  # raw-URL key
         "status": "usable", "method": "requests",
         "fetched_at": "2026-07-01T17:46:53+00:00"}])
    _write_manifest(root, "07-02-26", [
        {"original_url": "https://boards.greenhouse.io/acme/jobs/123456",
         "normalized_url": "greenhouse:acme:123456",  # already-canonical key
         "status": "usable", "method": "ats",
         "fetched_at": "2026-07-02T22:43:43+00:00"}])
    reg_path = tmp_path / "registry.json"
    registry = bf.backfill(root, reg_path, out=lambda *_: None)
    postings = registry["postings"]
    assert list(postings.keys()) == ["greenhouse:acme:123456"]
    posting = postings["greenhouse:acme:123456"]
    assert posting["original_capture"]["fetched_at"] == "2026-07-01T17:46:53+00:00"
    assert posting["original_source"] == "backfill-earliest-known"
    assert posting["latest_capture"]["fetched_at"] == "2026-07-02T22:43:43+00:00"
    assert len(posting["history"]) == 2


def test_backfill_dedupes_mirrored_batch_folders_and_skips_non_captures(tmp_path):
    import backfill_capture_registry as bf
    root = tmp_path / "reviews"
    entry = {"original_url": "https://boards.greenhouse.io/acme/jobs/123456",
             "normalized_url": "greenhouse:acme:123456", "status": "usable",
             "method": "ats", "fetched_at": "2026-07-01T17:46:53+00:00"}
    _write_manifest(root, "07-01-26", [
        entry,
        # A skipped duplicate is not a capture; an entry with no timestamp neither.
        {"original_url": "https://boards.greenhouse.io/acme/jobs/123456?x=1",
         "normalized_url": "greenhouse:acme:123456", "status": "duplicate",
         "fetched_at": "2026-07-01T17:46:53+00:00"},
        {"original_url": "https://boards.greenhouse.io/acme/jobs/999999",
         "normalized_url": "greenhouse:acme:999999", "status": "usable",
         "fetched_at": None},
    ])
    _write_manifest(root, "07-01-26/_rescore", [dict(entry)])  # mirrored copy
    reg_path = tmp_path / "registry.json"
    registry = bf.backfill(root, reg_path, out=lambda *_: None)
    posting = registry["postings"]["greenhouse:acme:123456"]
    assert len(posting["history"]) == 1  # mirror deduped
    assert "greenhouse:acme:999999" not in registry["postings"]
    # A failed legacy fetch backfills as history, never as original/latest.
    _write_manifest(root, "07-03-26", [
        {"original_url": "https://boards.greenhouse.io/acme/jobs/123456",
         "normalized_url": "greenhouse:acme:123456", "status": "failed",
         "fetched_at": "2026-07-03T10:00:00+00:00"}])
    registry = bf.backfill(root, reg_path, out=lambda *_: None)
    posting = registry["postings"]["greenhouse:acme:123456"]
    assert posting["latest_capture"]["fetched_at"] == "2026-07-01T17:46:53+00:00"
    assert posting["original_capture"]["fetched_at"] == "2026-07-01T17:46:53+00:00"


# ---- HTML list-structure preservation ------------------------------------------
def test_html_unordered_and_ordered_lists_become_marked_lines():
    html = ("<h2>What you'll do</h2><ul><li>Ship product</li><li>Talk to "
            "<a href='http://x'>customers</a> weekly</li></ul>"
            "<h2>Process</h2><ol><li>Apply online</li><li>Interview</li></ol>")
    text = af._html_to_text(html)
    assert "What you'll do\n\n- Ship product\n- Talk to customers weekly" in text
    assert "Process\n\n1. Apply online\n2. Interview" in text


def test_html_nested_lists_indent_two_spaces_per_level():
    html = ("<ul><li>Benefits<ul><li>Medical</li><li>Dental<ul><li>Ortho rider</li>"
            "</ul></li></ul></li><li>Equity</li></ul>")
    text = af._html_to_text(html)
    assert ("- Benefits\n"
            "  - Medical\n"
            "  - Dental\n"
            "    - Ortho rider\n"
            "- Equity") in text


def test_html_paragraphs_are_never_bulleted():
    html = ("<p>We are a mission-driven company. We ship weekly.</p>"
            "<p>Our team is distributed. Everyone writes.</p>")
    text = af._html_to_text(html)
    assert not any(l.startswith(("-", "1.")) for l in text.splitlines())
    assert text == ("We are a mission-driven company. We ship weekly.\n\n"
                    "Our team is distributed. Everyone writes.")


def test_html_conversion_loses_no_text_and_invents_none():
    html = ("<h1>Role</h1><p>Intro paragraph here.</p>"
            "<ul><li>First <strong>bullet</strong> item</li><li>Second item</li></ul>"
            "<p>Closing paragraph.</p>")
    text = af._html_to_text(html)
    expected_words = ("Role Intro paragraph here. First bullet item Second item "
                      "Closing paragraph.")
    normalized = re.sub(r"\s+", " ", re.sub(r"^[ \t]*(?:[-•*·]|\d+\.)\s*", "", text,
                                            flags=re.M)).strip()
    assert normalized == expected_words  # no loss, no duplication, no invention
    assert text.count("First bullet item") == 1
    assert "- First bullet item" in text


def test_li_wrapped_paragraphs_render_as_single_items():
    # The Ashby shape: <li><p>text</p></li>.
    html = "<ul><li><p>Own the roadmap end-to-end.</p></li><li><p>Ship weekly.</p></li></ul>"
    text = af._html_to_text(html)
    assert text == "- Own the roadmap end-to-end.\n- Ship weekly."


# ---- Body-comparison semantics ---------------------------------------------------
def test_formatting_only_change_is_named_as_restoration_never_job_text_unchanged(tmp_path):
    flattened = ("About the role\nResponsibilities include shipping product.\n"
                 "Ship product\nTalk to customers\n"
                 "The base salary range for this role is $150,000 - $180,000 annually.\n"
                 + ("value delivered. " * 60))
    structured = flattened.replace("Ship product\nTalk to customers",
                                   "- Ship product\n- Talk to customers")
    assert pc.material_change_notes(flattened, structured) == \
        "Employer content unchanged; source list formatting restored."
    src, entry = _refetch_manifest(tmp_path, _fetch_result(flattened),
                                   _fetch_result(structured))
    out = (src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
    notes = next(l for l in out.splitlines() if l.startswith("Additional Notes:"))
    assert "Employer content unchanged; source list formatting restored." in notes
    assert "Job text unchanged" not in notes


def test_material_update_uses_the_new_vocabulary(tmp_path):
    old = ("About the role\nResponsibilities include shipping product.\n"
           "The base salary range for this role is $150,000 - $180,000 annually.\n"
           + ("x " * 60))
    edited = old.replace("$150,000 - $180,000", "$160,000 - $190,000")
    assert pc.material_change_notes(old, edited) == "Employer materially updated the posting."
    assert pc.material_change_notes(old, old) == "No material changes detected."


# ===========================================================================
# Fourth live-run review: block-element fusion in the HTML converter, the
# `, Exempt` regression it caused, and false "materially updated" notes.
# ===========================================================================
# The exact observed Ashby shape: a Role Details heading + employment + cadence
# paragraphs following (or jammed into) the final list item.
_ROLE_DETAILS_TAIL_HTML = (
    "<p>What we're looking for:</p>"
    "<ul><li><p>Experience with early-stage or ambiguous problem spaces where you "
    "had to build the roadmap from scratch rather than inherit one.</p></li></ul>"
    "<p>Role Details:</p>"
    "<p>Employment Type: Full Time, Exempt</p>"
    "<p>This is hybrid (onsite from our NYC or San Francisco hub location three "
    "days per week: Tuesday, Wednesday, Thursday)</p>")


def _assert_no_boundary_fusion(text):
    """Block boundaries must never fuse at the character level. The `:X`/`aA`
    artifacts only ever appear when two blocks are glued with no separator."""
    assert not re.search(r"[a-z]:[A-Z]", text), text
    for a, b in re.findall(r"([a-z])([A-Z])", text):
        # camelCase can occur inside legitimate words/brands; the observed bug
        # produced 'ExemptThis' — assert the specific fused shapes never appear.
        pass
    for fused in ("Role Details:Employment", "ExemptThis", "one. Role Details"):
        assert fused not in text, fused


@pytest.mark.parametrize("html", [
    _ROLE_DETAILS_TAIL_HTML,
    # The same three blocks jammed INSIDE the final <li> (the fused live shape).
    ("<p>What we're looking for:</p>"
     "<ul><li><p>Experience with early-stage or ambiguous problem spaces where you "
     "had to build the roadmap from scratch rather than inherit one.</p>"
     "<p>Role Details:</p>"
     "<p>Employment Type: Full Time, Exempt</p>"
     "<p>This is hybrid (onsite from our NYC or San Francisco hub location three "
     "days per week: Tuesday, Wednesday, Thursday)</p></li></ul>"),
])
def test_block_siblings_never_fuse_onto_a_list_item(html):
    text = af._html_to_text(html)
    _assert_no_boundary_fusion(text)
    lines = text.splitlines()
    # The list item ends at its own text — NOT extended by the following blocks.
    item = next(l for l in lines if l.startswith("- "))
    assert item == ("- Experience with early-stage or ambiguous problem spaces where "
                    "you had to build the roadmap from scratch rather than inherit one.")
    # Each block is its own line; the heading is blank-line separated.
    assert "Role Details:" in lines
    assert "Employment Type: Full Time, Exempt" in lines
    assert any(l.startswith("This is hybrid (onsite from our NYC or San Francisco")
               for l in lines)
    i = lines.index("Role Details:")
    assert lines[i - 1] == "" and lines[i + 1] == ""


def test_employment_exempt_survives_the_html_converted_body():
    """The `, Exempt` regression: the fused text broke the prose miner. Over the
    CONVERTED body, `Employment Type: Full Time, Exempt` sits on its own line and
    the miner (and the structured-field `, Exempt` append) both see it again."""
    body = af._html_to_text(_ROLE_DETAILS_TAIL_HTML)
    assert pc._mine_employment(body) == "Full Time, Exempt"
    # Structured field bare -> mined from the converted body.
    out = pc.build_output_text("http://x", "PM", "Acme",
                               body + "\n" + ("x " * 60),
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 150,000",
                                     "working_location": "NYC; San Francisco"},
                               methods_tried=["ats"])
    assert "Employment: Full Time, Exempt" in out
    # Structured "FullTime" + exempt statement in the converted body -> appended.
    out2 = pc.build_output_text("http://x", "PM", "Acme",
                                body + "\n" + ("x " * 60),
                                meta={"title": "PM", "structured_source": True,
                                      "employment_type": "FullTime",
                                      "compensation": "USD 150,000",
                                      "working_location": "NYC; San Francisco"},
                                methods_tried=["ats"])
    assert "Employment: Full Time, Exempt" in out2
    # And the cadence paragraph mines cleanly too (bonus of the un-fused body).
    assert "Office Expectation: 3 Days Per Week, Tuesday–Thursday" in out


def test_reflattening_differences_never_read_as_an_employer_edit(tmp_path):
    """(a) heading case + element reorder + URL-rendering differences -> content
    unchanged; the note names formatting restoration, plus the field-corrections
    clause when fields changed."""
    old = ("ABOUT THE ROLE\n"
           "We are hiring a product manager to own the roadmap.\n"
           "Learn more at https://example.com/about ( https://example.com/about )\n"
           "REQUIREMENTS\n"
           "5+ years of product experience required.\n"
           "The base salary range for this role is $150,000 - $180,000 annually.\n"
           + ("filler value delivered. " * 20))
    new = ("About the role\n\n"
           "We are hiring a product manager to own the roadmap.\n\n"
           "The base salary range for this role is $150,000 - $180,000 annually.\n\n"
           "Requirements\n\n"                     # heading case + sentence relocated
           "- 5+ years of product experience required.\n"  # now a bullet
           "Learn more at\n"                       # link rendered as text, URL gone
           + ("filler value delivered. " * 20))
    assert pc.material_change_notes(old, new) == \
        "Employer content unchanged; source list formatting restored."
    # (b) one genuinely ADDED sentence -> materially updated.
    added = new + "\nWe now also require experience with clinical workflows.\n"
    assert pc.material_change_notes(new, added) == "Employer materially updated the posting."
    # (c) one REWORDED sentence -> materially updated.
    reworded = new.replace("5+ years of product experience required.",
                           "8+ years of product experience required.")
    assert pc.material_change_notes(new, reworded) == "Employer materially updated the posting."
    # End-to-end: field correction + formatting restoration compose in the note.
    def first(u):
        return {"ok": True, "title": "PM", "company": "Acme", "body": old,
                "method": "requests", "error": None,
                "meta": {"title": "PM", "source": "requests/html",
                         "structured_source": True, "employment_type": "FullTime",
                         "compensation": "USD 150,000", "working_location": "Remote"},
                "questions": []}

    def second(u):
        return {"ok": True, "title": "PM", "company": "Acme",
                "body": new + "\nFull Time, Exempt\n",
                "method": "ats", "error": None,
                "meta": {"title": "PM", "source": "greenhouse-boards-api",
                         "structured_source": True, "employment_type": "FullTime",
                         "compensation": "USD 150,000", "working_location": "Remote"},
                "questions": []}

    src = _batch_source(tmp_path)
    url = "https://example.com/job/reflatten"
    pc.process_urls([url], src, first)
    manifest = pc.process_urls([url], src, second, force=True)
    out = (src / Path(manifest["entries"][0]["output_path"]).name).read_text(encoding="utf-8")
    notes = next(l for l in out.splitlines() if l.startswith("Additional Notes:"))
    assert "Corrected the employment type from the original capture." in notes
    assert "Job text unchanged" not in notes


# ===========================================================================
# Fifth live-run review: <br /> semantics in the HTML converter.
# ===========================================================================
# The employer's REAL markup shape (synthetic text): the follow-on paragraphs
# and the nested comp <ul> are all INSIDE the last <li>, and the `Role Details:`
# heading is separated from the item text only by a <br /><br /> run.
_BR_NESTED_LI_HTML = (
    "<p>What we're looking for:</p>"
    "<ul><li><p>Experience with early-stage or ambiguous problem spaces where you "
    "had to build the roadmap from scratch rather than inherit one.<br /><br />"
    "<strong>Role Details:</strong></p>"
    "<p>Employment Type: Full Time, Exempt</p>"
    "<ul><li><p><strong>Base Compensation:</strong> The base compensation range "
    "for this position is<br />$182,000–$227,000 USD Annually </p></li></ul>"
    "<p><strong>This is hybrid (onsite from our NYC or San Francisco hub location "
    "three days per week: Tuesday, Wednesday, Thursday)</strong></p></li></ul>")


def test_double_br_ends_the_item_and_headings_get_their_own_line():
    text = af._html_to_text(_BR_NESTED_LI_HTML)
    _assert_no_boundary_fusion(text)
    lines = text.splitlines()
    # The bullet ends at its own sentence — the <br /><br /> heading never glues on.
    assert ("- Experience with early-stage or ambiguous problem spaces where you "
            "had to build the roadmap from scratch rather than inherit one.") in lines
    assert not any("inherit one. Role Details" in l for l in lines)
    # The heading and the employment paragraph are their own blank-line-separated blocks.
    i = lines.index("Role Details:")
    assert lines[i - 1] == "" and lines[i + 1] == ""
    assert "Employment Type: Full Time, Exempt" in lines
    # The nested comp bullet keeps its single-<br> LINE BREAK as an indented
    # continuation line — never a new bullet.
    j = next(k for k, l in enumerate(lines)
             if l.strip().startswith("- Base Compensation:"))
    assert lines[j].endswith("range for this position is")
    assert lines[j + 1].strip() == "$182,000–$227,000 USD Annually"
    assert not lines[j + 1].strip().startswith("-")
    # The hybrid paragraph is separate; document order is preserved; no text lost.
    k = next(k for k, l in enumerate(lines) if l.startswith("This is hybrid (onsite"))
    assert lines.index("Role Details:") < lines.index("Employment Type: Full Time, Exempt") < j < k
    # And the downstream miners see the un-fused shape.
    assert pc._mine_employment(text) == "Full Time, Exempt"
    assert pc._mine_office_expectation(text) == "3 Days Per Week, Tuesday–Thursday"


def test_single_br_mid_paragraph_is_a_line_break_not_a_new_block():
    text = af._html_to_text("<p>The range is<br />$182,000 annually and generous.</p>")
    assert text == "The range is\n$182,000 annually and generous."
    # A <br /><br /> run IS a paragraph break.
    text2 = af._html_to_text("<p>First thought.<br /><br />Second thought.</p>")
    assert text2 == "First thought.\n\nSecond thought."
    # Inside a plain (non-nested) list item: continuation line, never a new bullet.
    text3 = af._html_to_text("<ul><li>Line one<br />line two</li><li>Item two</li></ul>")
    assert text3 == "- Line one\n  line two\n- Item two"


# ===========================================================================
# Phase A7: atomicity, advisory locking, and ISOLATED registry shards.
# ===========================================================================
def test_atomic_write_leaves_no_partial_file_and_no_tmp_litter(tmp_path):
    target = tmp_path / "sub" / "registry.json"
    pc.atomic_write_text(target, '{"a": 1}\n')
    assert target.read_text(encoding="utf-8") == '{"a": 1}\n'
    # A failing write must leave the ORIGINAL intact and no tmp files behind.
    class Boom(Exception):
        pass
    try:
        with pytest.raises(Boom):
            original = pc.atomic_write_text

            def failing(path, text):
                original(path, text[: len(text) // 2])
                raise Boom()
            failing(target, '{"b": 2}\n')
    finally:
        pass
    leftovers = [p.name for p in target.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_file_lock_is_exclusive_and_times_out_with_a_clear_error(tmp_path):
    target = tmp_path / "registry.json"
    with pc.file_lock(target):
        with pytest.raises(pc.LockTimeout) as e:
            with pc.file_lock(target, timeout=0.1):
                pass
    assert "could not acquire the lock" in str(e.value)
    assert "another prep worker" in str(e.value)
    # Released afterwards — the next writer proceeds immediately.
    with pc.file_lock(target, timeout=0.1):
        pass


def test_interleaved_lock_guarded_writers_lose_no_events(tmp_path):
    """Two workers read-modify-write the same registry. Because each does so under ONE lock,
    neither loses the other's events (the pre-fix shape — read, then write later — dropped
    whichever worker wrote first)."""
    import threading
    reg_path = tmp_path / "registry.json"
    pc.save_capture_registry(reg_path, {"schema_version": 1, "postings": {}})
    barrier = threading.Barrier(2)

    def worker(n):
        barrier.wait()
        for i in range(10):
            def _apply(reg, n=n, i=i):
                pc.record_capture_event(reg, "greenhouse:acme:1", {
                    "fetched_at": f"2026-07-{10 + n:02d}T00:00:{i:02d}+00:00",
                    "url": f"u{n}-{i}", "ok": True}, success=True)
            pc.update_capture_registry(reg_path, _apply)

    threads = [threading.Thread(target=worker, args=(n,)) for n in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    reg = pc.load_capture_registry(reg_path)
    history = reg["postings"]["greenhouse:acme:1"]["history"]
    assert len(history) == 20, "every event from both writers must survive"
    assert len({h["url"] for h in history}) == 20
    # Whichever worker won the race owns the original — and it is IMMUTABLE from then on
    # (which worker got there first is a race; that the original never moves is not).
    original = dict(reg["postings"]["greenhouse:acme:1"]["original_capture"])
    pc.update_capture_registry(reg_path, lambda r: pc.record_capture_event(
        r, "greenhouse:acme:1", _ev(28, "later"), success=True))
    after = pc.load_capture_registry(reg_path)["postings"]["greenhouse:acme:1"]
    assert after["original_capture"] == original
    assert len(after["history"]) == 21


def test_shard_mode_leaves_the_global_registry_byte_identical(tmp_path, monkeypatch):
    """Her amendment #3: a staging/canary fetch must NOT touch the global registry."""
    global_path = tmp_path / "global.json"
    pc.save_capture_registry(global_path, {"schema_version": 1, "postings": {}})
    before = global_path.read_bytes()
    monkeypatch.setattr(pc, "DEFAULT_REGISTRY_PATH", global_path)
    shard = tmp_path / "shard-canary.json"
    src = _batch_source(tmp_path / "staging")
    # (a) explicit registry_path
    pc.process_urls(["https://boards.greenhouse.io/acme/jobs/123456"], src,
                    _fetch_result(_SYNTH_BODY), registry_path=shard)
    assert global_path.read_bytes() == before
    assert "greenhouse:acme:123456" in pc.load_capture_registry(shard)["postings"]
    # (b) the JAIL_CAPTURE_REGISTRY env switch
    shard2 = tmp_path / "shard-env.json"
    monkeypatch.setenv("JAIL_CAPTURE_REGISTRY", str(shard2))
    src2 = _batch_source(tmp_path / "staging2")
    pc.process_urls(["https://boards.greenhouse.io/acme/jobs/777777"], src2,
                    _fetch_result(_SYNTH_BODY))
    assert global_path.read_bytes() == before
    assert "greenhouse:acme:777777" in pc.load_capture_registry(shard2)["postings"]
    assert pc.resolve_registry_path() == shard2
    assert pc.resolve_registry_path(shard) == shard   # explicit arg wins over the env


def _ev(day, url="u", ok=True):
    return {"fetched_at": f"2026-07-{day:02d}T12:00:00+00:00", "url": url, "ok": ok}


def _shard_with(path, key, events, original=None, latest=None):
    reg = {"schema_version": 1, "postings": {key: {"history": [dict(e) for e in events]}}}
    posting = reg["postings"][key]
    if original:
        posting["original_capture"] = dict(original)
        posting["original_source"] = "staging"
    if latest:
        posting["latest_capture"] = dict(latest)
    pc.save_capture_registry(path, reg)
    return path


def test_merge_excludes_a_rejected_key_entirely(tmp_path):
    """A rejected/defective staging capture must never reach the global registry — not its
    events, and above all not as the permanent original."""
    global_path = tmp_path / "global.json"
    pc.save_capture_registry(global_path, {"schema_version": 1, "postings": {}})
    shard = _shard_with(tmp_path / "s.json", "greenhouse:acme:1", [_ev(5)],
                        original=_ev(5), latest=_ev(5))
    bad = _shard_with(tmp_path / "s2.json", "greenhouse:acme:999", [_ev(5)],
                      original=_ev(5), latest=_ev(5))
    merged = pc.merge_registry_shards(global_path, [shard, bad],
                                      accepted_keys={"greenhouse:acme:1"})
    assert set(merged["postings"]) == {"greenhouse:acme:1"}
    assert "greenhouse:acme:999" not in pc.load_capture_registry(global_path)["postings"]


def test_merge_keeps_the_earlier_global_original_over_a_later_shard_event(tmp_path):
    global_path = tmp_path / "global.json"
    pc.save_capture_registry(global_path, {"schema_version": 1, "postings": {
        "greenhouse:acme:1": {"history": [_ev(1, "old")],
                              "original_capture": _ev(1, "old"),
                              "original_source": "live",
                              "latest_capture": _ev(1, "old")}}})
    shard = _shard_with(tmp_path / "s.json", "greenhouse:acme:1", [_ev(9, "new")],
                        original=_ev(9, "new"), latest=_ev(9, "new"))
    merged = pc.merge_registry_shards(global_path, [shard], {"greenhouse:acme:1"})
    posting = merged["postings"]["greenhouse:acme:1"]
    assert posting["original_capture"]["url"] == "old"      # immutable, earliest wins
    assert posting["latest_capture"]["url"] == "new"        # latest advances
    assert [h["url"] for h in posting["history"]] == ["old", "new"]
    # An EARLIER shard original does replace a later global one (earliest-known wins).
    earlier = _shard_with(tmp_path / "s3.json", "greenhouse:acme:1", [_ev(1, "earliest")],
                          original={"fetched_at": "2026-06-01T12:00:00+00:00",
                                    "url": "earliest", "ok": True})
    merged2 = pc.merge_registry_shards(global_path, [earlier], {"greenhouse:acme:1"})
    assert merged2["postings"]["greenhouse:acme:1"]["original_capture"]["url"] == "earliest"


def test_merge_never_advances_latest_on_a_failed_event_and_is_idempotent(tmp_path):
    global_path = tmp_path / "global.json"
    pc.save_capture_registry(global_path, {"schema_version": 1, "postings": {
        "greenhouse:acme:1": {"history": [_ev(1, "ok1")],
                              "original_capture": _ev(1, "ok1"),
                              "latest_capture": _ev(1, "ok1")}}})
    shard = _shard_with(tmp_path / "s.json", "greenhouse:acme:1", [_ev(9, "boom", ok=False)],
                        latest=_ev(9, "boom", ok=False))
    merged = pc.merge_registry_shards(global_path, [shard], {"greenhouse:acme:1"})
    assert merged["postings"]["greenhouse:acme:1"]["latest_capture"]["url"] == "ok1"
    assert any(h["url"] == "boom" for h in merged["postings"]["greenhouse:acme:1"]["history"])
    # Idempotent: merging the same shard again changes nothing at all.
    snapshot = global_path.read_text(encoding="utf-8")
    pc.merge_registry_shards(global_path, [shard], {"greenhouse:acme:1"})
    assert global_path.read_text(encoding="utf-8") == snapshot
    pc.merge_registry_shards(global_path, [shard], {"greenhouse:acme:1"})
    assert global_path.read_text(encoding="utf-8") == snapshot


def test_manifest_writes_are_atomic_and_locked(tmp_path):
    """A manifest write must be atomic too — a reader never sees a truncated JSON file."""
    src = _batch_source(tmp_path)
    manifest = pc.process_urls(["https://example.com/job/atomic"], src,
                               _fetch_result(_SYNTH_BODY),
                               registry_path=tmp_path / "reg.json")
    mpath = tmp_path / "0 - Prep Report" / "prep-manifest.json"
    assert json.loads(mpath.read_text(encoding="utf-8"))["entries"]
    assert not [p for p in mpath.parent.iterdir() if p.name.endswith(".tmp")]
    # The sidecar lock exists and is not holding the file open exclusively afterwards.
    with pc.file_lock(mpath, timeout=1):
        pass
    assert manifest["counts"][pc.USABLE] == 1


# ===========================================================================
# Canary-run extraction defects (2026-07-30). Live SHAPES, synthetic text.
# ===========================================================================
# The live Ashby comp shape: a non-salary component glued onto the tier summary.
_ASHBY_COMP_WITH_EQUITY = {
    "compensationTierSummary": "$172K – $248K • Offers Equity",
    "compensationTiers": [{
        "title": "", "tierSummary": "$172K – $248K • Offers Equity",
        "components": [
            {"summary": "Offers Equity", "compensationType": "EquityPercentage",
             "minValue": None, "maxValue": None},
            {"summary": "$172K – $248K", "compensationType": "Salary", "interval": "1 YEAR",
             "currencyCode": "USD", "minValue": 172000, "maxValue": 248000},
        ]}]}


def test_base_salary_filters_on_compensation_type_and_renders_inline():
    """Defect 1: `Offers Equity` was rendered as a Base Salary band (and its presence
    made a single-band posting render as a bullet list). Only `Salary`-type components
    belong in Base Salary; the rest route to Additional Compensation."""
    comp, _raw = af._ashby_compensation(_ASHBY_COMP_WITH_EQUITY)
    assert comp == "$172K – $248K"
    assert "Equity" not in comp
    assert af._ashby_additional_components(_ASHBY_COMP_WITH_EQUITY) == ["Equity"]
    out = pc.build_output_text("http://x", "PM", "Help Scout", _SYNTH_BODY,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": comp,
                                     "additional_compensation_components": ["Equity"],
                                     "working_location": "Remote"},
                               field_status={"compensation": pc.FOUND,
                                             "working_location": pc.FOUND,
                                             "description": pc.FOUND, "conflicts": []},
                               methods_tried=["ats"])
    # ONE band -> inline, not a one-item bullet list.
    assert "Base Salary: $172-248K\n" in out
    assert "- $172-248K" not in out
    assert "Offers Equity" not in out
    assert "Additional Compensation: Equity mentioned, but details not provided." in out


def test_a_tier_summary_is_never_split_into_pseudo_bands():
    """The ` • `-joined summary is the employer's DISPLAY wording, not a band list."""
    comp, _raw = af._ashby_compensation({
        "compensationTiers": [{"title": "", "tierSummary": "$150K – $180K • Offers Equity • Bonus",
                               "components": []}]})
    assert comp == "$150K – $180K"


def test_multi_zone_salary_summaries_still_render_per_band():
    """The filter must not flatten a genuine multi-zone posting (the BetterUp shape)."""
    comp, _raw = af._ashby_compensation({
        "compensationTiers": [
            {"title": "Zone A: SF / NYC", "tierSummary": "$236K – $296K", "components": []},
            {"title": "Zone B: Austin", "tierSummary": "$213K – $266K", "components": []}]})
    assert comp == "Zone A: SF / NYC: $236K – $296K · Zone B: Austin: $213K – $266K"


_BASE_RANGE_SENTENCE = (
    "About the role\nResponsibilities include shipping product.\n"
    "The anticipated new hire base salary range for this full-time position is "
    "$122,400-$170,000 + equity + benefits.\n" + ("x " * 60))


def test_additional_compensation_never_restates_the_base_range():
    """Defect 2: the whole base-salary sentence was surfaced as Additional
    Compensation. Only its non-base components belong there."""
    out = pc.build_output_text("http://x", "PM", "Acme", _BASE_RANGE_SENTENCE,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "$122,400 - $170,000",
                                     "working_location": "Remote"},
                               field_status={"compensation": pc.FOUND,
                                             "working_location": pc.FOUND,
                                             "description": pc.FOUND, "conflicts": []},
                               methods_tried=["ats"])
    line = next(l for l in out.splitlines() if l.startswith("Additional Compensation:"))
    assert line == "Additional Compensation: Equity and benefits mentioned, but details not provided."
    assert "122,400" not in line and "170,000" not in line and "base salary" not in line.lower()
    # Base Salary still carries the range (abbreviated, one decimal — $122,400 is not round).
    assert "Base Salary: $122.4-170K" in out


def test_a_benefits_mention_inside_a_comp_sentence_is_never_did_not_mention():
    """Defect 3: `Benefits: Employer did not mention benefits.` while the posting's own
    comp sentence said `+ benefits` — a capture contradicting its source."""
    benefits, _e = af.mine_benefits_equity(_BASE_RANGE_SENTENCE)
    assert benefits == af.MENTIONED_NO_DETAILS
    out = pc.build_output_text("http://x", "PM", "Acme", _BASE_RANGE_SENTENCE,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "$122,400 - $170,000",
                                     "working_location": "Remote"},
                               methods_tried=["ats"])
    assert "Benefits: Mentioned, but details not provided." in out
    assert "did not mention benefits" not in out
    # Other component-style mentions count too...
    for phrase in ("plus benefits", "and comprehensive benefits", "benefits package",
                   "+ full benefits", "offers competitive benefits"):
        body = f"About the role\nResponsibilities include shipping. Salary {phrase}.\n"
        assert af.mine_benefits_equity(body)[0] == af.MENTIONED_NO_DETAILS, phrase
    # ...but a posting that genuinely says nothing about benefits still reports that.
    assert af.mine_benefits_equity(
        "About the role\nResponsibilities include shipping product every quarter.")[0] is None


@pytest.mark.parametrize("structured,prose,conflict", [
    # Defect 4: alias spellings of ONE metro are agreement, not a conflict.
    ("San Francisco, CA; Remote, US", ["Bay Area, CA"], False),
    ("Bay Area, CA", ["San Francisco, CA"], False),
    ("New York, NY", ["Brooklyn, NY"], False),
    ("Washington, DC", ["Arlington, VA"], False),
    # A subset relationship is agreement too.
    ("San Francisco, CA; New York, NY", ["San Francisco, CA"], False),
    # A genuinely disjoint geography STILL conflicts (don't defeat the feature).
    ("Austin, TX; New York, NY", ["Denver, CO"], True),
    ("Seattle, WA", ["Austin, TX"], True),
])
def test_metro_aliases_do_not_create_a_false_location_conflict(structured, prose, conflict):
    assert pc._location_materially_disagrees(structured, prose) is conflict


def test_maven_shaped_capture_reports_no_conflict(tmp_path):
    """End-to-end on the observed shape: SF + Remote structurally, "Bay Area" in the
    prose preference sentence — one metro, so no conflict and no lost preference line."""
    body = ("About the role\nResponsibilities include shipping product.\n"
            "Strong preference for those based in San Francisco.\n" + ("x " * 60))
    meta = {"title": "PM", "source": "greenhouse-boards-api", "structured_source": True,
            "compensation": "USD 200,000-250,000",
            "working_location": "San Francisco, CA; Remote, US"}
    fs = pc.assess_completeness(meta, body, [])
    assert fs["working_location"] == pc.FOUND
    assert "conflicts" in fs and not fs["conflicts"]
    out = pc.build_output_text("http://x", "PM", "Acme", body, meta=meta,
                               field_status=fs, methods_tried=["ats"])
    assert "Conflicting employer information" not in out
    assert "Location Preference: Strong preference for those based in SF." in out


# ---- Defect 5: the employer page's declared name beats a board-token guess ----
_HELPSCOUT_HTML = ('<html><head><meta property="og:site_name" content="Help Scout">'
                   '<title>Careers</title></head><body>x</body></html>')


def test_employer_declared_name_beats_a_board_token_guess():
    assert af.employer_declared_name(_HELPSCOUT_HTML) == "Help Scout"
    co, ro = pc.normalize_capture_identity(
        "Helpscout", "Senior Product Manager",
        url="https://www.helpscout.com/company/careers/?ashby_jid=abc",
        html=_HELPSCOUT_HTML)
    assert (co, ro) == ("Help Scout", "Senior Product Manager")
    assert pc.base_filename(co, ro) == "help-scout__senior-product-manager.txt"
    # JSON-LD hiringOrganization outranks og:site_name.
    assert af.employer_declared_name(_HELPSCOUT_HTML,
                                     {"hiring_organization": "Help Scout Inc."}) == "Help Scout Inc."


def test_without_an_employer_signal_the_board_token_fallback_still_applies():
    plain = "<html><head><title>Careers</title></head><body>x</body></html>"
    assert af.employer_declared_name(plain) is None
    co, _ro = pc.normalize_capture_identity(
        "Helpscout", "Senior Product Manager",
        url="https://www.helpscout.com/company/careers/?ashby_jid=abc", html=plain)
    assert co == "Helpscout"
    # An ATS-hosted URL never adopts a page name (the host names the platform).
    co2, _ = pc.normalize_capture_identity(
        "Betterup", "Principal PM", url="https://jobs.ashbyhq.com/betterup/abc",
        html='<meta property="og:site_name" content="Ashby">')
    assert co2 == "Betterup"


def test_the_employer_name_lookup_only_fires_for_a_token_shaped_guess():
    """The gate lives in ats_fetchers (shared), NOT in either CLI's fetch_one."""
    # Fires: employer domain + single run-together word matching the domain label.
    assert af.should_check_employer_name(
        "https://www.helpscout.com/company/careers/?ashby_jid=abc", "Helpscout") is True
    # Does not fire: already multi-word, an ATS host, or a name unrelated to the domain.
    assert af.should_check_employer_name(
        "https://www.helpscout.com/careers", "Help Scout") is False
    assert af.should_check_employer_name(
        "https://jobs.ashbyhq.com/helpscout/abc", "Helpscout") is False
    assert af.should_check_employer_name(
        "https://www.example.com/careers", "Acme") is False
    # Neither CLI may keep its own copy — that divergence is what shipped the bug.
    pju = pytest.importorskip("prep_job_urls")
    assert not hasattr(pju, "_should_check_employer_name")


# ---- Defect 6: the Remote-/-Hybrid office-naming convention ----
def test_greenhouse_office_naming_convention_collapses_readably():
    raw = ("Remote - New York City, NY; Remote - Seattle, WA; Remote - United States; "
           "San Francisco - Hybrid")
    assert pc._format_working_locations(raw) == "Remote (US; NYC or Seattle) or IRL SF"
    # Onsite naming, and a plain list with no convention, still behave.
    assert pc._format_working_locations("Austin - Onsite; Remote - United States") == \
        "Remote (US) or IRL Austin"
    assert pc._format_working_locations("New York City; San Francisco") == "NYC or SF"
    assert pc._format_working_locations("Remote") == "Remote"


def test_office_expectation_is_never_inferred_from_the_word_hybrid():
    """Defect 6, second half: `Hybrid` alone must NOT produce a day count. A cadence
    appears only when the employer states one (`N days per week`)."""
    body = ("About the role\nResponsibilities include shipping product.\n"
            "This is a hybrid role based in our San Francisco office.\n" + ("x " * 60))
    assert pc._mine_office_expectation(body) is None
    out = pc.build_output_text("http://x", "PM", "Acme", body,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 200,000",
                                     "workplace": "Hybrid",
                                     "working_location": "Remote - United States; "
                                                         "San Francisco - Hybrid"},
                               methods_tried=["ats"])
    assert "Office Expectation: Not Specified" in out
    assert "Days Per Week" not in out
    assert "Working Location(s): Remote (US) or IRL SF" in out
    # A STATED cadence in the same shape does come through.
    body2 = body.replace("This is a hybrid role based in our San Francisco office.",
                         "Hybrid: employees work from the San Francisco office 3 days per week.")
    assert pc._mine_office_expectation(body2) == "3 Days Per Week"


# ===========================================================================
# Second canary pass (2026-07-30): the page-<title> company source, sentence-case
# component values, and remote-first location consistency.
# ===========================================================================
_HELPSCOUT_TITLE_HTML = (
    "<html><head><title>Lead/Principal Product Manager, Resolve – Careers at Help Scout"
    "</title></head><body>x</body></html>")
_HELPSCOUT_URL = "https://www.helpscout.com/company/careers/?ashby_jid=abc"
_HELPSCOUT_ROLE = "Lead/Principal Product Manager, Resolve"


def test_page_title_wrapper_supplies_the_correctly_spaced_company():
    """The page declares NO og:site_name and NO JSON-LD hiringOrganization — the only
    correctly-spaced company name is in the <title>'s "– Careers at X" wrapper, the very
    suffix the title normalizer discards."""
    assert af.company_from_page_title(_HELPSCOUT_TITLE_HTML) == "Help Scout"
    assert af.employer_declared_name(_HELPSCOUT_TITLE_HTML) == "Help Scout"
    co, ro = pc.normalize_capture_identity(
        "Helpscout", f"{_HELPSCOUT_ROLE} – Careers at Help Scout",
        url=_HELPSCOUT_URL, html=_HELPSCOUT_TITLE_HTML)
    assert co == "Help Scout"
    # The identity choke point must not regress: the ROLE keeps its own text, wrapper gone.
    assert ro == _HELPSCOUT_ROLE
    assert pc.base_filename(co, ro) == "help-scout__lead-principal-product-manager-resolve.txt"


@pytest.mark.parametrize("title", [
    "Senior PM – Careers at Help Scout",
    "Senior PM - Careers at Help Scout",
    "Senior PM — Jobs at Help Scout",
    "Senior PM | Help Scout Careers",
    "Careers at Help Scout",
])
def test_every_title_wrapper_separator_and_shape_is_read(title):
    assert af.company_from_page_title(f"<title>{title}</title>") == "Help Scout"


def test_a_title_wrapper_naming_a_different_company_is_rejected_by_the_guard():
    """The same-company-modulo-spacing guard means a wrapper can only re-space or
    re-punctuate the name — never swap in a different employer."""
    html = "<title>Senior PM – Careers at Acme Corporation</title>"
    assert af.employer_declared_name(html) == "Acme Corporation"
    co, _ro = pc.normalize_capture_identity(
        "Helpscout", "Senior PM", url=_HELPSCOUT_URL, html=html)
    assert co == "Helpscout"          # guard rejected it; the token is retained


def test_a_title_with_no_wrapper_falls_back_to_the_board_token():
    for html in ("<title>Senior Product Manager</title>",
                 "<title>Careers</title>",
                 "<html><head></head><body>no title at all</body></html>"):
        assert af.company_from_page_title(html) in (None, "")
        co, _ro = pc.normalize_capture_identity(
            "Helpscout", "Senior PM", url=_HELPSCOUT_URL, html=html)
        assert co == "Helpscout"


def test_the_two_title_wrapper_implementations_agree():
    """`ats_fetchers.company_from_page_title` mirrors the wrapper family that
    `prep_common._strip_title_branding` removes from titles. Pin that they agree, so the
    deliberate mirroring can't drift."""
    for title in ("Senior PM – Careers at Help Scout", "Senior PM | Help Scout Careers",
                  "Senior PM - Jobs at Acme", "Senior PM — Acme Jobs"):
        page = af.company_from_page_title(f"<title>{title}</title>")
        _clean, wrapper_co = pc._strip_title_branding(title)
        assert page == wrapper_co, title


def test_component_values_are_sentence_case_not_title_case():
    """Title Case is for LABELS only: a mid-sentence generic component word is lowercase,
    while an employer's own phrase keeps the capitalization they wrote."""
    assert pc._sentence_case_components(["Equity", "Benefits"]) == ["Equity", "benefits"]
    assert pc._sentence_case_components(["Bonus", "Equity", "Employee Travel Credits"]) == \
        ["Bonus", "equity", "Employee Travel Credits"]
    assert pc._sentence_case_components(["Benefits"]) == ["Benefits"]
    out = pc.build_output_text("http://x", "PM", "Acme", _BASE_RANGE_SENTENCE,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "$122,400 - $170,000",
                                     "working_location": "Remote"},
                               field_status={"compensation": pc.FOUND,
                                             "working_location": pc.FOUND,
                                             "description": pc.FOUND, "conflicts": []},
                               methods_tried=["ats"])
    assert ("Additional Compensation: Equity and benefits mentioned, but details "
            "not provided.") in out
    assert "and Benefits mentioned" not in out


def test_remote_plus_metro_renders_remote_first_consistently():
    """Defect 3: `SF or Remote, US` and `Remote (US; …) or IRL SF` described the same
    shape two ways. Remote leads, the country folds into the parenthetical."""
    assert pc._format_working_locations("San Francisco, CA; Remote, US") == \
        "Remote (US) or IRL SF"
    assert pc._format_working_locations("Remote, US; San Francisco, CA") == \
        "Remote (US) or IRL SF"
    assert pc._format_working_locations("Remote (US); New York City") == \
        "Remote (US) or IRL NYC"
    # The office-naming convention still renders as before...
    assert pc._format_working_locations(
        "Remote - New York City, NY; Remote - Seattle, WA; Remote - United States; "
        "San Francisco - Hybrid") == "Remote (US; NYC or Seattle) or IRL SF"
    # ...and lists with no remote entry, or a bare Remote, are untouched.
    assert pc._format_working_locations("New York City; San Francisco") == "NYC or SF"
    assert pc._format_working_locations("Remote") == "Remote"
    assert pc._format_working_locations("Remote, US") == "Remote (US)"


def test_maven_shaped_location_reads_remote_first_end_to_end():
    body = ("About the role\nResponsibilities include shipping product.\n"
            "Strong preference for those based in San Francisco.\n" + ("x " * 60))
    meta = {"title": "PM", "source": "greenhouse-boards-api", "structured_source": True,
            "compensation": "USD 200,000-250,000",
            "working_location": "San Francisco, CA; Remote, US"}
    fs = pc.assess_completeness(meta, body, [])
    out = pc.build_output_text("http://x", "PM", "Acme", body, meta=meta,
                               field_status=fs, methods_tried=["ats"])
    assert "Working Location(s): Remote (US) or IRL SF" in out
    assert "Conflicting employer information" not in out
    assert "Location Preference: Strong preference for those based in SF." in out


# ===========================================================================
# CLI DIVERGENCE (2026-07-30): the two prep CLIs have separately-evolved
# `fetch_one` implementations, and an identity enrichment that landed in only
# one of them shipped a mis-spelled company while its unit tests passed. The
# enrichment now lives on the shared path; these tests keep it that way.
# ===========================================================================
_ASHBY_EMPLOYER_DOMAIN_URL = "https://www.helpscout.com/company/careers/?ashby_jid=abc"


def _ashby_on_employer_domain_result():
    """A synthetic Ashby posting-API result served from the EMPLOYER's own domain: the
    company is only a board-token guess and no employer HTML is in hand (the API route
    downloads none), which is exactly the shape that needs the shared lookup."""
    return {
        "title": _HELPSCOUT_ROLE, "company": "Helpscout",
        "text": _SYNTH_BODY, "source": "ashby-posting-api (custom-domain jid)",
        "apply_url": "https://jobs.ashbyhq.com/helpscout/abc/application",
        "posting_id": "abc", "working_location": "Remote, US",
        "compensation": "$172K – $248K", "employment_type": "FullTime",
        "structured_source": True, "questions": [],
    }


def _fake_employer_name_fetcher(calls):
    def fetch(url, **_kw):
        calls.append(url)
        return af.employer_declared_name(_HELPSCOUT_TITLE_HTML)
    return fetch


def test_both_prep_clis_produce_identical_identity_for_one_fixture(monkeypatch):
    """BEHAVIORAL divergence guard: the SAME fixture through BOTH CLIs' `fetch_one`
    must yield the same company / role / filename. This fails if a future identity or
    metadata enrichment lands in one path only."""
    pju = pytest.importorskip("prep_job_urls")
    pjp = pytest.importorskip("prep_job_urls_playwright")
    ats_res = _ashby_on_employer_domain_result()
    monkeypatch.setattr(pju, "fetch_via_ats", lambda u, **k: dict(ats_res))
    monkeypatch.setattr(pjp, "fetch_via_ats", lambda u, **k: dict(ats_res))

    class DummyBrowser:  # the ATS branch never touches it when questions are present
        pass

    results = {
        "requests": pju.fetch_one(_ASHBY_EMPLOYER_DOMAIN_URL,
                                  question_renderer=lambda *a, **k: []),
        "playwright": pjp.make_fetch_one(DummyBrowser())(_ASHBY_EMPLOYER_DOMAIN_URL),
    }
    identities = {}
    for name, res in results.items():
        assert res["ok"] is True, name
        # Neither fetch_one resolves identity itself — process_urls does, from the same
        # inputs. Assert the INPUTS match, then the resolved identity.
        meta = res["meta"]
        declared = pc.enrich_employer_identity(
            _ASHBY_EMPLOYER_DOMAIN_URL, res["company"], meta,
            fetcher=_fake_employer_name_fetcher([]))
        co, ro = pc.normalize_capture_identity(
            res["company"], res["title"], url=_ASHBY_EMPLOYER_DOMAIN_URL,
            jsonld=meta.get("jsonld_identity"), html=meta.get("raw_html"),
            body=res["body"], declared_name=declared)
        identities[name] = (co, ro, pc.base_filename(co, ro))
    assert identities["requests"] == identities["playwright"]
    assert identities["requests"] == (
        "Help Scout", _HELPSCOUT_ROLE,
        "help-scout__lead-principal-product-manager-resolve.txt")


def test_neither_cli_fetch_one_carries_its_own_identity_enrichment():
    """Structural companion to the behavioral test above: the enrichment helpers must be
    reachable from the SHARED modules, and absent from both CLI modules."""
    pju = pytest.importorskip("prep_job_urls")
    pjp = pytest.importorskip("prep_job_urls_playwright")
    assert callable(pc.enrich_employer_identity)
    assert callable(af.should_check_employer_name)
    assert callable(af.fetch_employer_declared_name)
    for mod in (pju, pjp):
        for attr in ("_should_check_employer_name", "employer_declared_name",
                     "enrich_employer_identity"):
            assert not hasattr(mod, attr), f"{mod.__name__} re-declared {attr}"


def test_process_urls_resolves_the_employer_name_for_an_ats_only_capture(tmp_path):
    """END-TO-END through the shared path, with NO employer HTML in meta (the Ashby API
    route downloads none): the single best-effort lookup supplies the declared name."""
    src = _batch_source(tmp_path)
    ats_res = _ashby_on_employer_domain_result()
    calls: list = []

    def fetch(u):
        meta = dict(ats_res)
        meta["method"] = "ats"
        return {"ok": True, "title": ats_res["title"], "company": ats_res["company"],
                "body": ats_res["text"], "method": "ats", "error": None,
                "meta": meta, "questions": []}

    manifest = pc.process_urls([_ASHBY_EMPLOYER_DOMAIN_URL], src, fetch,
                               registry_path=tmp_path / "reg.json",
                               employer_name_fetcher=_fake_employer_name_fetcher(calls))
    entry = manifest["entries"][0]
    assert entry["company"] == "Help Scout"
    assert entry["title"] == _HELPSCOUT_ROLE
    assert Path(entry["output_path"]).name == \
        "help-scout__lead-principal-product-manager-resolve.txt"
    written = (src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
    assert "Company: Help Scout" in written
    assert f"Role: {_HELPSCOUT_ROLE}" in written
    assert calls == [_ASHBY_EMPLOYER_DOMAIN_URL], "exactly ONE extra request"


def test_the_shared_lookup_makes_at_most_one_request_and_never_for_ats_hosts(tmp_path):
    calls: list = []
    # Already-spaced name: no request.
    assert pc.enrich_employer_identity(
        "https://www.helpscout.com/careers", "Help Scout", {},
        fetcher=_fake_employer_name_fetcher(calls)) is None
    # ATS-hosted URL: no request (the host names the platform, not the employer).
    assert pc.enrich_employer_identity(
        "https://jobs.ashbyhq.com/helpscout/abc", "Helpscout", {},
        fetcher=_fake_employer_name_fetcher(calls)) is None
    assert calls == []
    # HTML already in hand: resolved for FREE, still no request.
    assert pc.enrich_employer_identity(
        _ASHBY_EMPLOYER_DOMAIN_URL, "Helpscout",
        {"raw_html": _HELPSCOUT_TITLE_HTML},
        fetcher=_fake_employer_name_fetcher(calls)) == "Help Scout"
    assert calls == []
    # Nothing in hand + gate fires: exactly one request.
    assert pc.enrich_employer_identity(
        _ASHBY_EMPLOYER_DOMAIN_URL, "Helpscout", {},
        fetcher=_fake_employer_name_fetcher(calls)) == "Help Scout"
    assert len(calls) == 1
    # A pre-resolved name short-circuits entirely.
    assert pc.enrich_employer_identity(
        _ASHBY_EMPLOYER_DOMAIN_URL, "Helpscout",
        {"employer_declared_name": "Help Scout"},
        fetcher=_fake_employer_name_fetcher(calls)) == "Help Scout"
    assert len(calls) == 1


def test_a_failing_employer_name_lookup_never_fails_the_capture(tmp_path):
    src = _batch_source(tmp_path)
    ats_res = _ashby_on_employer_domain_result()

    def fetch(u):
        meta = dict(ats_res)
        meta["method"] = "ats"
        return {"ok": True, "title": ats_res["title"], "company": ats_res["company"],
                "body": ats_res["text"], "method": "ats", "error": None,
                "meta": meta, "questions": []}

    def boom(url, **_kw):
        raise RuntimeError("network down")

    manifest = pc.process_urls([_ASHBY_EMPLOYER_DOMAIN_URL], src, fetch,
                               registry_path=tmp_path / "reg.json",
                               employer_name_fetcher=boom)
    entry = manifest["entries"][0]
    assert entry["status"] == pc.USABLE
    assert entry["company"] == "Helpscout"   # honest token fallback, capture intact


# ===========================================================================
# Registry-authoritative re-render (2026-07-30). A staging worker writes into an
# ISOLATED (empty) shard, so its captures render their OWN fetch as ORIGINAL with
# no LATEST — the artifact claims today's fetch is the original and drops the true
# history even though the global registry is correct. The re-render fixes the
# artifact WITHOUT being a capture event.
# ===========================================================================
_STAGED_URL = "https://boards.greenhouse.io/asana/jobs/7392230"
_STAGED_KEY = "greenhouse:asana:7392230"


def _staged_capture(tmp_path, url=_STAGED_URL, captured="2026-07-30T14:24:00+00:00"):
    """A capture as a staging worker writes it: its own fetch as ORIGINAL, no LATEST."""
    src = _batch_source(tmp_path)
    body = _SYNTH_BODY
    text = pc.build_output_text(
        url, "Senior Product Manager", "Asana", body,
        meta={"title": "Senior Product Manager", "source": "greenhouse-boards-api",
              "structured_source": True, "compensation": "USD 200,000-250,000",
              "working_location": "Remote", "posting_id": "7392230",
              "apply_url": "https://boards.greenhouse.io/asana/jobs/7392230"},
        methods_tried=["ats"], captured=captured)
    path = src / "asana__senior-product-manager.txt"
    path.write_text(text, encoding="utf-8")
    return path


def _registry_with_history(tmp_path, key=_STAGED_KEY,
                           original="2026-07-29T18:56:12+00:00",
                           latest="2026-07-30T14:24:00+00:00"):
    reg_path = tmp_path / "global-registry.json"
    posting = {
        "history": [
            {"fetched_at": original, "url": _STAGED_URL, "method": "ats",
             "source": "greenhouse-boards-api", "posting_id": "7392230", "ok": True},
            {"fetched_at": "2026-07-29T22:43:43+00:00", "url": _STAGED_URL, "method": "ats",
             "source": "greenhouse-boards-api", "posting_id": "7392230", "ok": True},
        ],
        "original_capture": {"fetched_at": original, "url": _STAGED_URL, "method": "ats",
                             "source": "greenhouse-boards-api", "posting_id": "7392230",
                             "ok": True},
        "original_source": "backfill-earliest-known",
    }
    if latest:
        posting["latest_capture"] = {"fetched_at": latest, "url": _STAGED_URL,
                                     "method": "ats", "source": "greenhouse-boards-api",
                                     "posting_id": "7392230", "ok": True}
        posting["history"].append(dict(posting["latest_capture"]))
    pc.save_capture_registry(reg_path, {"schema_version": 1, "postings": {key: posting}})
    return reg_path


def test_rerender_restores_the_true_original_from_the_registry(tmp_path):
    path = _staged_capture(tmp_path)
    before = path.read_text(encoding="utf-8")
    assert "Captured At: July 30, 2026 at 10:24 AM ET" in before
    assert "LATEST CAPTURE DETAILS" not in before      # the staged (wrong) shape
    reg_path = _registry_with_history(tmp_path)
    assert pc.apply_registry_history(path, reg_path) is True
    after = path.read_text(encoding="utf-8")
    # ORIGINAL now comes from the REGISTRY, not from the file's own fetch.
    original_block = after.split("ORIGINAL CAPTURE DETAILS")[1].split("LATEST")[0]
    assert "Captured At: July 29, 2026 at 2:56 PM ET" in original_block
    # ...and the file's own fetch became LATEST.
    latest_block = after.split("LATEST CAPTURE DETAILS")[1]
    assert "Captured At: July 30, 2026 at 10:24 AM ET" in latest_block
    assert after.index("ORIGINAL CAPTURE DETAILS") < after.index("LATEST CAPTURE DETAILS")


def test_rerender_leaves_the_registry_byte_identical(tmp_path):
    """A re-render is NOT a capture event: no history appended, no timestamp moved,
    no write to the registry at all."""
    path = _staged_capture(tmp_path)
    reg_path = _registry_with_history(tmp_path)
    before_bytes = reg_path.read_bytes()
    before_reg = pc.load_capture_registry(reg_path)
    assert pc.apply_registry_history(path, reg_path) is True
    assert reg_path.read_bytes() == before_bytes
    after_reg = pc.load_capture_registry(reg_path)
    assert after_reg == before_reg
    assert len(after_reg["postings"][_STAGED_KEY]["history"]) == 3
    assert after_reg["postings"][_STAGED_KEY]["original_capture"]["fetched_at"] == \
        "2026-07-29T18:56:12+00:00"
    assert after_reg["postings"][_STAGED_KEY]["latest_capture"]["fetched_at"] == \
        "2026-07-30T14:24:00+00:00"


def test_rerender_preserves_everything_above_the_end_marker_byte_for_byte(tmp_path):
    path = _staged_capture(tmp_path)
    before = path.read_text(encoding="utf-8")
    reg_path = _registry_with_history(tmp_path)
    pc.apply_registry_history(path, reg_path)
    after = path.read_text(encoding="utf-8")
    marker = "--- JOB TEXT END ---"
    assert before.split(marker)[0] == after.split(marker)[0]
    assert pc.body_from_capture(after) == pc.body_from_capture(before) == _SYNTH_BODY
    # Snapshot / work details / compensation / questions all untouched.
    for section in ("JOB SNAPSHOT", "WORK DETAILS", "COMPENSATION",
                    "APPLICATION QUESTIONS WORTH PREPARING"):
        assert section in after


def test_rerender_of_a_genuine_first_capture_emits_no_latest_section(tmp_path):
    path = _staged_capture(tmp_path, captured="2026-07-29T18:56:12+00:00")
    reg_path = _registry_with_history(tmp_path, original="2026-07-29T18:56:12+00:00",
                                      latest="2026-07-29T18:56:12+00:00")
    pc.apply_registry_history(path, reg_path)
    after = path.read_text(encoding="utf-8")
    assert "ORIGINAL CAPTURE DETAILS" in after
    assert "LATEST CAPTURE DETAILS" not in after
    assert "Captured At: July 29, 2026 at 2:56 PM ET" in after


@pytest.mark.parametrize("url", [
    "https://boards.greenhouse.io/asana/jobs/7392230",
    "https://job-boards.greenhouse.io/asana/jobs/7392230?gh_src=x",
    "https://asana.com/jobs/apply/7392230/senior-product-manager",
    "https://www.asanacareers.com/jobs/?gh_jid=7392230",
])
def test_alias_url_forms_resolve_to_the_same_registry_key(tmp_path, url):
    path = _staged_capture(tmp_path / url[-12:].replace("/", "_"), url=url)
    text = path.read_text(encoding="utf-8")
    key = pc.capture_identity_from_file(text)
    assert key == _STAGED_KEY, url
    reg_path = _registry_with_history(tmp_path)
    assert pc.apply_registry_history(path, reg_path) is True
    assert "Captured At: July 29, 2026 at 2:56 PM ET" in path.read_text(encoding="utf-8")


def test_rerender_is_idempotent(tmp_path):
    path = _staged_capture(tmp_path)
    reg_path = _registry_with_history(tmp_path)
    assert pc.apply_registry_history(path, reg_path) is True
    once = path.read_text(encoding="utf-8")
    assert pc.apply_registry_history(path, reg_path) is False   # nothing left to do
    assert path.read_text(encoding="utf-8") == once
    assert pc.apply_registry_history(path, reg_path) is False


def test_a_capture_absent_from_the_registry_is_left_untouched(tmp_path):
    path = _staged_capture(tmp_path)
    before = path.read_text(encoding="utf-8")
    empty = tmp_path / "empty-registry.json"
    pc.save_capture_registry(empty, {"schema_version": 1, "postings": {}})
    assert pc.apply_registry_history(path, empty) is False
    assert path.read_text(encoding="utf-8") == before
    # And the CLI reports it rather than failing.
    import apply_registry_history as arh
    msgs: list = []
    counts = arh.run([path.parent], registry_path=empty, out=msgs.append)
    assert counts["not_in_registry"] == 1 and counts["changed"] == 0
    assert any("no registry record" in m for m in msgs)


def test_rerender_preserves_an_existing_additional_notes_line(tmp_path):
    """A comparison the capture already made is real information — keep it. A
    re-render can't produce one (it reads no prior body), so it never invents one."""
    path = _staged_capture(tmp_path)
    text = path.read_text(encoding="utf-8")
    reg_path = _registry_with_history(tmp_path)
    pc.apply_registry_history(path, reg_path)
    # Promoted a first-capture render: honest phrasing, never "no material changes".
    after = path.read_text(encoding="utf-8")
    assert "Additional Notes: Previous capture was not available for comparison." in after
    assert "No material changes detected." not in after
    # Now give the file a real notes line and re-render again: it survives.
    edited = after.replace(
        "Additional Notes: Previous capture was not available for comparison.",
        "Additional Notes: Employer materially updated the posting.")
    path.write_text(edited, encoding="utf-8")
    reg2 = _registry_with_history(tmp_path, original="2026-07-28T17:46:53+00:00")
    assert pc.apply_registry_history(path, reg2) is True
    final = path.read_text(encoding="utf-8")
    assert "Additional Notes: Employer materially updated the posting." in final
    assert "Captured At: July 28, 2026 at 1:46 PM ET" in final


def test_the_cli_runs_over_a_folder_and_reports(tmp_path):
    import apply_registry_history as arh
    path = _staged_capture(tmp_path)
    reg_path = _registry_with_history(tmp_path)
    msgs: list = []
    # A dry run changes nothing on disk...
    counts = arh.run([path.parent], registry_path=reg_path, dry_run=True, out=msgs.append)
    assert counts["changed"] == 1
    assert "LATEST CAPTURE DETAILS" not in path.read_text(encoding="utf-8")
    assert any("dry run" in m for m in msgs)
    # ...then the real run rewrites it, and a second run is a no-op.
    counts = arh.run([path.parent], registry_path=reg_path, out=msgs.append)
    assert counts == {"changed": 1, "unchanged": 0, "not_in_registry": 0, "unreadable": 0}
    assert "LATEST CAPTURE DETAILS" in path.read_text(encoding="utf-8")
    counts = arh.run([path.parent], registry_path=reg_path, out=msgs.append)
    assert counts["changed"] == 0 and counts["unchanged"] == 1


# ===========================================================================
# LinkedIn-shaped block fusion (2026-07-30). The LinkedIn guest fragment leans on
# <strong>/<span>/<br> rather than clean <p>/<h3>, and the converter flattened an
# inline element's subtree with get_text() — losing any separator nested inside it
# and fusing adjacent inline elements ("You will:Growth Systems & Product…").
# It already routed through the SHARED converter, so the fix is there, not in a
# second implementation.
# ===========================================================================
_LINKEDIN_FUSION_SHAPES = {
    # Adjacent inline elements relying on the elements themselves for separation.
    "adjacent-strong":
        "<strong>You will:</strong><strong>Growth Systems &amp; Product Ownership</strong>"
        "<ul><li>Own the roadmap for the Growth pod end-to-end</li></ul>",
    # A <br> NESTED inside an inline wrapper — invisible to a get_text() flatten.
    "nested-br":
        "<strong>You will:<br><br>Growth Systems &amp; Product Ownership</strong>"
        "<ul><li>Own the roadmap for the Growth pod end-to-end</li></ul>",
    # Nested spans, LinkedIn's other common shape.
    "nested-span":
        "<span><span>You will:</span><span>Growth Systems &amp; Product Ownership</span></span>"
        "<ul><li>Own the roadmap for the Growth pod end-to-end</li></ul>",
}


@pytest.mark.parametrize("shape", sorted(_LINKEDIN_FUSION_SHAPES))
def test_linkedin_style_inline_markup_never_fuses_blocks(shape):
    text = af._html_to_text(_LINKEDIN_FUSION_SHAPES[shape])
    # The reported signature: a label glued to the next heading.
    assert "You will:Growth" not in text
    assert not re.search(r"[a-z]:[A-Z]", text), text
    lines = [l for l in text.splitlines() if l.strip()]
    assert "You will:" in lines
    assert "Growth Systems & Product Ownership" in lines
    assert lines.index("You will:") + 1 <= lines.index("Growth Systems & Product Ownership")
    # The list still renders, and no text was lost.
    assert "- Own the roadmap for the Growth pod end-to-end" in lines


def test_the_linkedin_body_routes_through_the_shared_converter():
    """The fix belongs in ONE converter (the 43aab1e divergence lesson): the LinkedIn
    body is produced by `_html_to_text`, not a private flattener."""
    src = Path(af.__file__).read_text(encoding="utf-8")
    linkedin_src = src[src.index("def _fetch_linkedin"):src.index("# Greenhouse")]
    assert "_html_to_text(" in linkedin_src
    assert "get_text(\"\\n\"" not in linkedin_src   # no private flattening


def test_the_boundary_guard_does_not_break_ordinary_prose():
    """Re-run of the fusion guard across the converter's other fixtures: a separator is
    inserted only at an ELEMENT boundary, never inside ordinary prose."""
    # One text node: a mid-sentence colon clause stays inline.
    assert af._html_to_text("<p>Health Coverage: Full medical. Note: details vary by state.</p>") \
        == "Health Coverage: Full medical. Note: details vary by state."
    # Mid-sentence markup must not gain a break (or a space).
    assert af._html_to_text("<p>This is <strong>bold</strong>face text.</p>") == \
        "This is boldface text."
    assert af._html_to_text("<p>See <a href='http://x'>our site</a> for more.</p>") == \
        "See our site for more."
    # A lowercase continuation after an element boundary is not a new block.
    assert af._html_to_text("<p><strong>Note:</strong> details vary by state.</p>") == \
        "Note: details vary by state."
    # Every earlier converter fixture stays fusion-free.
    for html in (_ROLE_DETAILS_TAIL_HTML, _BR_NESTED_LI_HTML):
        _assert_no_boundary_fusion(af._html_to_text(html))


def test_previously_pinned_converter_shapes_are_unchanged():
    """The nested-list, ordered-list, heading and paragraph fixtures must render
    exactly as before the inline-recursion change."""
    assert af._html_to_text(
        "<ul><li>Benefits<ul><li>Medical</li><li>Dental<ul><li>Ortho rider</li></ul>"
        "</li></ul></li><li>Equity</li></ul>") == (
        "- Benefits\n  - Medical\n  - Dental\n    - Ortho rider\n- Equity")
    assert af._html_to_text(
        "<h2>Process</h2><ol><li>Apply online</li><li>Interview</li></ol>") == (
        "Process\n\n1. Apply online\n2. Interview")
    assert af._html_to_text(
        "<p>We are a mission-driven company. We ship weekly.</p>"
        "<p>Our team is distributed. Everyone writes.</p>") == (
        "We are a mission-driven company. We ship weekly.\n\n"
        "Our team is distributed. Everyone writes.")
    assert af._html_to_text(
        "<ul><li><p>Own the roadmap end-to-end.</p></li><li><p>Ship weekly.</p></li></ul>") == (
        "- Own the roadmap end-to-end.\n- Ship weekly.")


# ---- LinkedIn posting date --------------------------------------------------
def test_linkedin_posted_date_uses_a_real_date_when_the_fragment_exposes_one():
    jsonld = ('<script type="application/ld+json">{"@type":"JobPosting","title":"PM",'
              '"datePosted":"2026-07-15T00:00:00Z","hiringOrganization":{"name":"Foodsmart"},'
              '"jobLocation":{"address":{"addressLocality":"Remote"}},'
              '"employmentType":"FULL_TIME"}</script>')
    assert af.linkedin_posted_date(jsonld) == "2026-07-15"
    # A <time datetime> attribute is a real date too.
    assert af.linkedin_posted_date('<time datetime="2026-07-15">2 weeks ago</time>') == "2026-07-15"


def test_linkedin_relative_posted_wording_is_never_converted_to_a_date():
    """"2 weeks ago" is relative to OUR fetch, not the employer's publication date —
    converting it would fabricate a date. Those captures stay an honest Unknown."""
    for frag in ('<span class="posted-time-ago__text">2 weeks ago</span>',
                 '<span class="posted-time-ago__text">Posted 30 days ago</span>',
                 "<div>no date information at all</div>", ""):
        assert af.linkedin_posted_date(frag) is None
    # And the writer renders that honestly.
    out = pc.build_output_text("https://www.linkedin.com/jobs/view/staff-pm-4417244583/",
                               "Staff PM", "Foodsmart", _SYNTH_BODY,
                               meta={"title": "Staff PM", "source": "linkedin-guest-api",
                                     "structured_source": True, "posted_date": None,
                                     "compensation": "USD 200,000", "working_location": "Remote"},
                               methods_tried=["ats"])
    assert "Job Posted At: Unknown" in out


# ===========================================================================
# B5 — canonical ATS identity + alias mechanism. The live defect: a raw
# `lark.com/careers/open-positions?ashby_jid=<id>` key coexisted with
# `ashby:lark:<id>`, splitting the history and mislabeling ORIGINAL as the later
# fetch until hand-merged.
# ===========================================================================
_LARK_UUID = "4ccf1e87-0317-4dca-949d-f7cb4f76fad7"
_LARK_RAW_URL = f"https://lark.com/careers/open-positions?ashby_jid={_LARK_UUID}"
_LARK_KEY = f"ashby:lark:{_LARK_UUID}"


def test_every_entry_form_of_one_posting_canonicalizes_to_one_key():
    forms = [
        _LARK_RAW_URL,                                             # raw employer URL
        _LARK_RAW_URL + "&utm_source=x&src=LinkedIn",              # tracking variant
        f"https://jobs.ashbyhq.com/lark/{_LARK_UUID}",             # ATS job URL
        f"https://jobs.ashbyhq.com/lark/{_LARK_UUID}/application", # ATS application URL
    ]
    keys = {pc.canonical_capture_key(u) for u in forms}
    assert keys == {_LARK_KEY}, keys
    # And the already-canonical form is a fixed point (via normalized_url storage).
    assert pc.normalize_url(f"https://jobs.ashbyhq.com/lark/{_LARK_UUID}") == _LARK_KEY


def test_registry_writes_resolve_recorded_aliases_to_the_canonical_posting():
    reg = {"schema_version": 1, "postings": {
        _LARK_KEY: {"history": [_ev(1, "u1")], "original_capture": _ev(1, "u1"),
                    "latest_capture": _ev(1, "u1"),
                    "aliases": ["https://lark.com/careers/open-positions"]}}}
    # A write under the recorded alias lands on the canonical posting.
    pc.record_capture_event(reg, "https://lark.com/careers/open-positions",
                            _ev(2, "u2"), success=True)
    assert set(reg["postings"]) == {_LARK_KEY}
    assert len(reg["postings"][_LARK_KEY]["history"]) == 2
    assert reg["postings"][_LARK_KEY]["original_capture"]["url"] == "u1"  # immutable


def test_the_lark_duplicate_shape_is_repaired_with_the_earliest_original(tmp_path):
    """The exact live shape: the raw-URL posting holds the EARLIER capture, the ATS
    posting the later one — pre-repair the ATS posting mislabeled ORIGINAL."""
    reg_path = tmp_path / "registry.json"
    raw_key = pc.normalize_url(_LARK_RAW_URL)
    assert raw_key == _LARK_KEY or raw_key.startswith("https://")  # legacy raw form
    legacy_raw_key = "https://lark.com/careers/open-positions?ashby_jid=" + _LARK_UUID
    pc.save_capture_registry(reg_path, {"schema_version": 1, "postings": {
        legacy_raw_key: {"history": [_ev(1, _LARK_RAW_URL)],
                         "original_capture": _ev(1, _LARK_RAW_URL),
                         "latest_capture": _ev(1, _LARK_RAW_URL)},
        _LARK_KEY: {"history": [_ev(9, "https://jobs.ashbyhq.com/lark/" + _LARK_UUID)],
                    "original_capture": _ev(9, "https://jobs.ashbyhq.com/lark/" + _LARK_UUID),
                    "latest_capture": _ev(9, "https://jobs.ashbyhq.com/lark/" + _LARK_UUID)},
    }})
    import repair_capture_registry as rcr
    msgs: list = []
    counts = rcr.run(registry_path=reg_path, out=msgs.append)
    assert counts["aliases_discovered"] == 1
    assert counts["identities_merged"] == 1
    assert counts["unresolved_conflicts"] == 0
    reg = pc.load_capture_registry(reg_path)
    assert set(reg["postings"]) == {_LARK_KEY}
    posting = reg["postings"][_LARK_KEY]
    # The TRUE earliest capture is the original again.
    assert posting["original_capture"]["fetched_at"] == _ev(1)["fetched_at"]
    assert posting["latest_capture"]["fetched_at"] == _ev(9)["fetched_at"]
    assert len(posting["history"]) == 2
    assert legacy_raw_key in posting["aliases"]
    # A backup was written before mutation.
    assert any(p.name.startswith("registry.json.backup-") for p in tmp_path.iterdir())
    # Idempotent: a second run reports zeros and writes nothing new.
    backups_before = sorted(p.name for p in tmp_path.iterdir() if "backup" in p.name)
    counts2 = rcr.run(registry_path=reg_path, out=msgs.append)
    assert counts2["aliases_discovered"] == 0 and counts2["identities_merged"] == 0
    assert sorted(p.name for p in tmp_path.iterdir() if "backup" in p.name) == backups_before


def test_dry_run_reports_without_touching_the_file(tmp_path):
    reg_path = tmp_path / "registry.json"
    legacy_raw_key = _LARK_RAW_URL
    pc.save_capture_registry(reg_path, {"schema_version": 1, "postings": {
        legacy_raw_key: {"history": [_ev(1, _LARK_RAW_URL)],
                         "original_capture": _ev(1, _LARK_RAW_URL)}}})
    before = reg_path.read_bytes()
    import repair_capture_registry as rcr
    counts = rcr.run(registry_path=reg_path, dry_run=True, out=lambda _m: None)
    assert counts["aliases_discovered"] == 1
    assert reg_path.read_bytes() == before
    assert not any("backup" in p.name for p in tmp_path.iterdir())


def test_conflicting_identities_are_reported_and_left_untouched(tmp_path):
    """One posting whose events canonicalize to TWO different ATS identities is a
    data problem a machine must not guess about."""
    reg_path = tmp_path / "registry.json"
    posting = {"history": [
        _ev(1, "https://boards.greenhouse.io/acme/jobs/111111"),
        _ev(2, "https://boards.greenhouse.io/acme/jobs/222222"),
    ], "original_capture": _ev(1, "https://boards.greenhouse.io/acme/jobs/111111")}
    pc.save_capture_registry(reg_path, {"schema_version": 1,
                                        "postings": {"https://example.com/x": posting}})
    import repair_capture_registry as rcr
    msgs: list = []
    counts = rcr.run(registry_path=reg_path, out=msgs.append)
    assert counts["unresolved_conflicts"] == 1
    assert counts["identities_merged"] == 0
    reg = pc.load_capture_registry(reg_path)
    assert "https://example.com/x" in reg["postings"]        # untouched
    assert any("CONFLICT" in m and "resolve by hand" in m for m in msgs)


def test_a_new_fetch_of_the_raw_lark_form_lands_on_the_ats_key(tmp_path):
    """End-to-end through process_urls: fetching the RAW employer form produces the
    canonical ATS key directly — the duplicate class cannot form again."""
    src = _batch_source(tmp_path)
    reg_path = tmp_path / "reg.json"

    def fetch(u):
        return {"ok": True, "title": "PM", "company": "Lark", "body": _SYNTH_BODY,
                "method": "ats", "error": None,
                "meta": {"title": "PM", "source": "ashby-posting-api (custom-domain jid)",
                         "structured_source": True, "compensation": "USD 200,000",
                         "working_location": "Remote"}, "questions": []}

    pc.process_urls([_LARK_RAW_URL], src, fetch, registry_path=reg_path)
    reg = pc.load_capture_registry(reg_path)
    assert list(reg["postings"]) == [_LARK_KEY]


# ===========================================================================
# B6 — true ORIGINAL/LATEST across history: discovery by CANONICAL IDENTITY,
# never by current filename or directory. A renamed, moved, or legacy-formatted
# capture still contributes its earliest genuine timestamp.
# ===========================================================================
_B6_URL = "https://boards.greenhouse.io/acme/jobs/654321"
_B6_KEY = "greenhouse:acme:654321"


def _manifest_entry(fetched_at, url=_B6_URL, filename="acme__pm.txt", **kw):
    e = {"original_url": url, "normalized_url": pc.normalize_url(url),
         "status": "usable", "method": "ats", "fetched_at": fetched_at,
         "output_path": f"3 - Source Material/All Job Posts (full text)/{filename}"}
    e.update(kw)
    return e


def test_history_folds_across_filenames_directories_and_url_forms(tmp_path):
    """One posting recorded across three batches under (1) an older FILENAME,
    (2) an older DIRECTORY, (3) a raw-URL identity later converted to the ATS
    identity — the registry holds ONE posting with the true earliest original."""
    import backfill_capture_registry as bf
    root = tmp_path / "reviews"
    # Oldest: raw employer URL form, old filename, archive directory.
    _write_manifest(root, "archive/07-01-26", [_manifest_entry(
        "2026-07-01T10:00:00+00:00",
        url="https://acme.com/positions/654321",
        filename="acme__product-manager-old-name.txt")])
    # Middle: ATS URL, renamed file, different directory.
    _write_manifest(root, "07-10-26", [_manifest_entry(
        "2026-07-10T10:00:00+00:00", filename="acme__pm-renamed.txt")])
    # Newest: current filename.
    _write_manifest(root, "07-20-26", [_manifest_entry("2026-07-20T10:00:00+00:00")])
    reg_path = tmp_path / "registry.json"
    registry = bf.backfill(root, reg_path, out=lambda *_: None)
    assert set(registry["postings"]) == {_B6_KEY}
    posting = registry["postings"][_B6_KEY]
    assert posting["original_capture"]["fetched_at"] == "2026-07-01T10:00:00+00:00"
    assert posting["latest_capture"]["fetched_at"] == "2026-07-20T10:00:00+00:00"
    assert len(posting["history"]) == 3


def test_missing_historical_metadata_still_contributes_its_timestamp(tmp_path):
    import backfill_capture_registry as bf
    root = tmp_path / "reviews"
    sparse = {"original_url": _B6_URL, "normalized_url": pc.normalize_url(_B6_URL),
              "status": "usable", "fetched_at": "2026-07-01T10:00:00+00:00"}
    _write_manifest(root, "07-01-26", [sparse])   # no method, no posting_id, no path
    registry = bf.backfill(root, tmp_path / "registry.json", out=lambda *_: None)
    posting = registry["postings"][_B6_KEY]
    assert posting["original_capture"]["fetched_at"] == "2026-07-01T10:00:00+00:00"


def test_original_stays_stable_across_future_refetches_and_latest_advances():
    reg = {"schema_version": 1, "postings": {}}
    pc.record_capture_event(reg, _B6_KEY, _ev(1, "first"), success=True)
    original = dict(reg["postings"][_B6_KEY]["original_capture"])
    # Multiple re-fetches, incl. an idempotent one with no substantive change and a
    # failed attempt: ORIGINAL never moves; LATEST = latest genuine SUCCESS.
    pc.record_capture_event(reg, _B6_KEY, _ev(5, "refetch-1"), success=True)
    pc.record_capture_event(reg, _B6_KEY, _ev(9, "refetch-2-no-change"), success=True)
    pc.record_capture_event(reg, _B6_KEY, _ev(12, "failed-attempt", ok=False), success=False)
    posting = reg["postings"][_B6_KEY]
    assert posting["original_capture"] == original
    assert posting["latest_capture"]["url"] == "refetch-2-no-change"
    assert len(posting["history"]) == 4


def test_a_renamed_legacy_format_capture_rerenders_the_true_original(tmp_path):
    """A LEGACY-format capture (old `URL:` line) under a NEW filename still resolves
    its canonical identity from its own content and re-renders the true earliest
    ORIGINAL from the registry."""
    legacy = (
        f"URL: {_B6_URL}\n"
        "Application URL: https://boards.greenhouse.io/acme/jobs/654321\n"
        "Company: Acme\nRole: Senior PM\n"
        "Source: greenhouse-boards-api · Posting ID: 654321 · Captured: 2026-07-20 · "
        "Methods tried: ats\n\n"
        "== NORMALIZED (for vetting) ==\n"
        "Working Location: Remote   [found]\n\n"
        "--- JOB TEXT START ---\nAbout the role\nResponsibilities include shipping.\n"
        "--- JOB TEXT END ---\n")
    path = tmp_path / "acme__senior-pm-totally-renamed.txt"
    path.write_text(legacy, encoding="utf-8")
    assert pc.capture_identity_from_file(legacy) == _B6_KEY
    reg_path = tmp_path / "registry.json"
    pc.save_capture_registry(reg_path, {"schema_version": 1, "postings": {
        _B6_KEY: {"history": [_ev(1, "first"), _ev(20, "later")],
                  "original_capture": _ev(1, "first"),
                  "latest_capture": _ev(20, "later")}}})
    assert pc.apply_registry_history(path, reg_path) is True
    out = path.read_text(encoding="utf-8")
    assert "ORIGINAL CAPTURE DETAILS" in out
    assert "Captured At: July 1, 2026" in out          # the TRUE earliest, from _ev(1)
    assert "LATEST CAPTURE DETAILS" in out
    # Everything above the END marker (the legacy head + body) is untouched.
    assert out.split("--- JOB TEXT END ---")[0] == legacy.split("--- JOB TEXT END ---")[0]


def test_backfill_replay_is_idempotent_for_a_no_change_refetch(tmp_path):
    import backfill_capture_registry as bf
    root = tmp_path / "reviews"
    _write_manifest(root, "07-01-26", [_manifest_entry("2026-07-01T10:00:00+00:00")])
    _write_manifest(root, "07-02-26", [_manifest_entry("2026-07-02T10:00:00+00:00")])
    reg_path = tmp_path / "registry.json"
    bf.backfill(root, reg_path, out=lambda *_: None)
    snapshot = reg_path.read_text(encoding="utf-8")
    bf.backfill(root, reg_path, out=lambda *_: None)
    assert reg_path.read_text(encoding="utf-8") == snapshot


# ===========================================================================
# B7 — question-filter hardening: three mechanically separated concepts
# (standard / logistical / substantive), and the Yes/No-into-location leak
# killed at the WRITER, not just caught by the gate.
# ===========================================================================
def _q(label, qtype="input_text", options=(), required=False, name="qx"):
    return {"label": label, "type": qtype, "required": required,
            "name": name, "names": [name], "options": list(options)}


@pytest.mark.parametrize("label,qtype", [
    # identity / contact / uploads / socials / pronunciation
    ("Upload your portfolio (optional)", "file"),
    ("Attach a writing sample", "file"),
    ("X profile", "input_text"),
    ("Dribbble", "input_text"),
    ("Name pronunciation", "input_text"),
    ("Mailing address", "input_text"),
    ("City, state, zip", "input_text"),
    # authorization / sponsorship / demographics (already covered; re-pinned)
    ("Are you legally authorized to work in the United States?", "select"),
    ("Will you require sponsorship?", "select"),
    ("Veteran status", "select"),
    # bare catch-alls
    ("Additional information", "textarea"),
    ("Anything else you'd like us to know?", "textarea"),
    ("Comments", "textarea"),
])
def test_standard_fields_are_always_excluded(label, qtype):
    q = _q(label, qtype)
    assert af.classify_question(q) == af.QUESTION_STANDARD, label
    assert af.filter_questions([q]) == [], label


def test_a_substantive_catch_all_is_kept():
    """The exception the rule states: catch-all WORDING that clearly asks a
    substantive custom question is not a standard field."""
    q = _q("Anything else you'd like us to know about how you would approach "
           "your first 90 days?", "textarea")
    assert af.classify_question(q) == af.QUESTION_SUBSTANTIVE
    assert len(af.filter_questions([q])) == 1


@pytest.mark.parametrize("label,qtype,options,expected_class", [
    # BetterUp/Bloomerang-style thoughtful questions -> substantive.
    ("How does our mission resonate with you, and what draws you to this role?",
     "textarea", (), af.QUESTION_SUBSTANTIVE),
    ("Describe the most impactful product decision you have made.",
     "textarea", (), af.QUESTION_SUBSTANTIVE),
    # Office-attendance / location-choice selects -> logistical.
    ("I understand this role requires attending an office at least 2 days per week. "
     "Which office are you closest to?", "select",
     ("San Francisco Bay Area", "New York City"), af.QUESTION_LOGISTICAL),
    ("Which location are you applying for?", "select",
     ("US Remote", "San Francisco"), af.QUESTION_LOGISTICAL),
])
def test_logistical_vs_substantive_classification(label, qtype, options, expected_class):
    q = _q(label, qtype, options)
    assert af.classify_question(q) == expected_class
    kept = af.filter_questions([q])
    if kept:
        assert kept[0]["question_class"] == expected_class


def test_kept_questions_carry_their_class_annotation():
    res, kept = _ashby_result_with_questions()
    classes = {q["label"][:20]: q["question_class"] for q in kept}
    assert af.QUESTION_SUBSTANTIVE in classes.values()
    assert af.QUESTION_LOGISTICAL in classes.values()


# ---- The Spring/Knit leak class, killed at the writer -------------------------
def test_yes_no_options_can_never_become_metros():
    """An office-attendance question whose options are acknowledgements: the
    cadence still informs Office Expectation, but the options NEVER reach
    Working Location(s)."""
    q = _q("This role requires working onsite 5 days a week from our office. "
           "Are you able to do so?", "select", ("Yes", "No"), required=True)
    parsed = af.parse_office_cadence(q)
    assert parsed is not None
    assert parsed["metros"] == []                  # structurally impossible to leak
    assert parsed["cadence"] == "5 days a week"
    out = pc.build_output_text("http://x", "PM", "Acme", _SYNTH_BODY,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 200,000",
                                     "working_location": "San Francisco, CA"},
                               questions=[dict(q, question_class="logistical")],
                               methods_tried=["ats"])
    wl_line = next(l for l in out.splitlines() if l.startswith("Working Location(s):"))
    assert "Yes" not in wl_line and "No" not in wl_line
    assert wl_line == "Working Location(s): SF"
    assert "Office Expectation: 5 Days Per Week" in out
    # The QA gate agrees (defense in depth, but the writer is the fix).
    import qa_captures
    assert not any("application-choice" in p
                   for p in qa_captures.validate_capture(out, filename="acme__pm.txt"))


@pytest.mark.parametrize("options,expected_metros", [
    (("Yes", "No"), []),                                        # Spring/Knit
    (("I understand and can commit to this", "No"), []),        # acknowledgement
    (("Prefer not to say",), []),
    (("San Francisco Bay Area", "New York City", "Yes"),        # mixed: places kept
     ["San Francisco Bay Area", "New York City"]),
    (("Austin, TX", "Washington, D.C."), ["Austin, TX", "Washington, D.C."]),
])
def test_metroish_option_filtering(options, expected_metros):
    q = _q("Which office are you closest to? This role requires 2 days per week "
           "in office.", "select", options)
    parsed = af.parse_office_cadence(q)
    assert parsed is not None
    assert parsed["metros"] == expected_metros


def test_the_betterup_office_question_still_supplies_its_metros():
    """Recall preserved: real place options still flow into Working Location(s)."""
    _res, kept = _ashby_result_with_questions()
    office = _office_question(kept)
    parsed = af.parse_office_cadence(office)
    assert parsed["metros"] == ["San Francisco Bay Area", "New York City",
                                "Austin, TX", "Washington, D.C."]


# ===========================================================================
# B10 — comp-label cleanup. The four live shapes that were hand-fixed:
# geo-prefixed presentation labels ("New York Pay Range:"), repeated-punctuation
# generic labels ("Annual Base Salary Range::"), and raw ATS label fragments.
# ===========================================================================
@pytest.mark.parametrize("raw,expected", [
    # Geo kept, label noise dropped.
    ("New York Pay Range: $160,000 - $230,000", "New York: $160-230K"),
    ("Los Angeles Base Salary Range: $140,000 - $190,000", "Los Angeles: $140-190K"),
    ("San Francisco Annual Base Salary Range: $170,000 - $210,000",
     "San Francisco: $170-210K Annually"),
    # Repeated punctuation + generic label -> stripped ("Annual" in the employer's own
    # label honestly earns the Annually suffix).
    ("Annual Base Salary Range:: $150,000 - $180,000", "$150-180K Annually"),
    # Raw ATS fragments (already covered; re-pinned beside the new shapes).
    ("Pay Range: USD 232,000–282,000", "$232-282K"),
    ("Salary Range:: $120,000 - $150,000", "$120-150K"),
])
def test_presentation_labels_clean_up(raw, expected):
    assert pc._base_salary_bands(raw, {"compensation_prose_all": []}, {}) == [expected]


def test_meaningful_geo_and_level_labels_are_never_rewritten():
    """Only labels carrying the range-noise wording are touched: a bare geo/level
    label is meaningful and survives verbatim."""
    for raw, expected in [
        ("Zone A: SF Bay Area / NYC $236K – $296K", "Zone A: SF Bay Area / NYC $236-296K"),
        ("US Tier 1: $174,000 - $290,000", "US Tier 1: $174-290K"),
    ]:
        assert pc._base_salary_bands(raw, {"compensation_prose_all": []}, {}) == [expected]


def test_geo_labels_render_in_multi_band_bullets(tmp_path):
    """End-to-end through the writer: a two-geo posting with presentation labels
    renders clean geo-labeled bullets."""
    out = pc.build_output_text(
        "http://x", "PM", "Acme", _SYNTH_BODY,
        meta={"title": "PM", "structured_source": True,
              "compensation": "New York Pay Range: $160,000 - $230,000 · "
                              "Los Angeles Base Salary Range: $140,000 - $190,000",
              "working_location": "NYC; LA"},
        field_status={"compensation": pc.FOUND, "working_location": pc.FOUND,
                      "description": pc.FOUND, "conflicts": []},
        methods_tried=["ats"])
    assert "\n- New York: $160-230K\n" in out
    assert "\n- Los Angeles: $140-190K\n" in out
    assert "Pay Range" not in out.split("COMPENSATION")[1].split("APPLICATION")[0]


# ===========================================================================
# B4 — the single prep CLI. One entry point (prep.py), engine modes composing
# the SAME downstream path. The old filenames remain as engine modules with
# deprecated forwarding entry points.
# ===========================================================================
def _prep_module():
    import prep
    return prep


def test_every_engine_mode_reaches_the_same_capture_and_qa_gate(tmp_path, monkeypatch):
    """The behavioral divergence guard, now across ENGINE MODES: the same posting
    through the requests engine, the playwright engine, and the auto composition
    must produce byte-identical captures (identity, sections, QA gate all shared,
    because every mode flows through the one process_urls)."""
    prep = _prep_module()
    import prep_job_urls as pju
    import prep_job_urls_playwright as pjp
    ats_res = _ashby_on_employer_domain_result()
    monkeypatch.setattr(pju, "fetch_via_ats", lambda u, **k: dict(ats_res))
    monkeypatch.setattr(pjp, "fetch_via_ats", lambda u, **k: dict(ats_res))

    class DummyBrowser:   # the ATS branch never touches it
        pass

    captures = {}
    for engine in ("requests", "playwright", "auto"):
        browser = None if engine == "requests" else DummyBrowser()
        fetch_one, fallback, label, _banner = prep.build_fetchers(engine, browser)
        src = _batch_source(tmp_path / engine)
        manifest = pc.process_urls(
            [_ASHBY_EMPLOYER_DOMAIN_URL], src, fetch_one,
            fetch_fallback=fallback, fallback_label=label,
            registry_path=tmp_path / engine / "reg.json",
            employer_name_fetcher=_fake_employer_name_fetcher([]))
        entry = manifest["entries"][0]
        assert entry["status"] == pc.USABLE, (engine, entry["notes"])
        text = (src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
        # Strip only the capture timestamps (each run has its own clock reading).
        text = re.sub(r"^Captured At: .*$", "Captured At: <ts>", text, flags=re.M)
        captures[engine] = (Path(entry["output_path"]).name, text)
    assert captures["requests"] == captures["playwright"] == captures["auto"]
    assert captures["requests"][0] == \
        "help-scout__lead-principal-product-manager-resolve.txt"


def test_the_auto_engine_composes_requests_first_with_playwright_fallback():
    prep = _prep_module()

    class DummyBrowser:
        pass

    fetch_one, fallback, label, banner = prep.build_fetchers("auto", DummyBrowser())
    assert callable(fetch_one) and callable(fallback)
    assert label == "playwright"
    assert "auto-retry" in banner.lower() or "playwright" in banner.lower()
    # requests: no browser, no fallback.
    f2, fb2, lb2, banner2 = prep.build_fetchers("requests")
    assert fb2 is None and lb2 is None
    assert "no browser" in banner2


def test_the_old_entry_points_forward_with_a_deprecation_note(tmp_path):
    """Compatibility wrappers: the old filenames still work, loudly, via prep.py."""
    import subprocess
    src = tmp_path / "3 - Source Material" / "All Job Posts (full text)"
    src.mkdir(parents=True)
    # No URL file -> prep.py exits with its own clear error AFTER the forward,
    # which proves the wrapper delegated rather than running its old body.
    for old, engine in (("prep_job_urls.py", "auto"),
                        ("prep_job_urls_playwright.py", "playwright")):
        res = subprocess.run(
            [sys.executable,
             str(Path(pc.__file__).parent / old), str(src), "--input", "missing.txt"],
            capture_output=True, text=True)
        assert res.returncode != 0
        assert "deprecated entry point" in res.stdout
        assert f"--engine {engine}" in res.stdout
        assert "URL input file not found" in (res.stdout + res.stderr)


def test_the_canonical_cli_validates_its_arguments(tmp_path):
    import subprocess
    res = subprocess.run(
        [sys.executable, str(Path(pc.__file__).parent / "prep.py"),
         str(tmp_path / "nope"), "--engine", "auto"],
        capture_output=True, text=True)
    assert res.returncode != 0
    assert "Source folder does not exist" in (res.stdout + res.stderr)
    res2 = subprocess.run(
        [sys.executable, str(Path(pc.__file__).parent / "prep.py"),
         str(tmp_path), "--engine", "carrier-pigeon"],
        capture_output=True, text=True)
    assert res2.returncode != 0
    assert "invalid choice" in res2.stderr


# ===========================================================================
# B9 — ATS-hosted brand-casing recovery. The live class: board token
# `openloophealth` title-cased into `Openloophealth` while the body plainly
# says "OpenLoop". Priority: structured name > body evidence > alias map >
# capitalize-first (which STANDS when no casing evidence exists — camel brands
# are never guessed).
# ===========================================================================
_OPENLOOP_BODY = ("About the role\nResponsibilities include shipping product.\n"
                  "About OpenLoop\nOpenLoop was founded to bring healing anywhere. "
                  "Our telehealth support solutions are thoughtfully designed.\n"
                  "© 2026 OpenLoop. All rights reserved.\n" + ("value delivered. " * 60))


def test_the_openloophealth_class_recovers_its_casing_from_the_body():
    assert af.brand_casing_from_body("openloophealth", _OPENLOOP_BODY) == "OpenLoop"
    assert af.recover_brand_casing("Openloophealth", _OPENLOOP_BODY) == "OpenLoop"


def test_body_recovery_end_to_end_through_process_urls(tmp_path):
    src = _batch_source(tmp_path)

    def fetch(u):
        return {"ok": True, "title": "Product Manager", "company": "Openloophealth",
                "body": _OPENLOOP_BODY, "method": "ats", "error": None,
                "meta": {"title": "Product Manager", "source": "ashby-posting-api",
                         "structured_source": True, "compensation": "USD 150,000",
                         "working_location": "Remote"}, "questions": []}

    manifest = pc.process_urls(["https://jobs.ashbyhq.com/openloophealth/"
                                "4ccf1e87-0317-4dca-949d-f7cb4f76fad7"],
                               src, fetch, registry_path=tmp_path / "reg.json")
    entry = manifest["entries"][0]
    assert entry["company"] == "OpenLoop"
    assert Path(entry["output_path"]).name == "openloop__product-manager.txt"
    written = (src / Path(entry["output_path"]).name).read_text(encoding="utf-8")
    assert "Company: OpenLoop" in written


@pytest.mark.parametrize("token,camel", [
    ("betterup", "BetterUp"), ("openai", "OpenAI"), ("youtube", "YouTube"),
    ("classdojo", "ClassDojo"), ("iheartmedia", "iHeartMedia"),
])
def test_camel_brands_recover_only_with_body_evidence(token, camel):
    """With body evidence the employer's own camel casing wins; with NO evidence
    the capitalize-first token stands — never a guess."""
    body = (f"About the role\nResponsibilities include shipping product.\n"
            f"About {camel}\n{camel} builds tools people love.\n"
            + ("value delivered. " * 60))
    assert af.recover_brand_casing(token.capitalize(), body) == camel
    silent = ("About the role\nResponsibilities include shipping product.\n"
              + ("value delivered. " * 60))
    assert af.recover_brand_casing(token.capitalize(), silent) is None


def test_short_words_can_never_claim_a_longer_token():
    """'Better' must never rename 'betterup': suffix stripping is limited to the
    generic descriptor list, never arbitrary prefixes."""
    body = ("About the role\nBetter products ship faster. Responsibilities include "
            "shipping product.\n" + ("value delivered. " * 60))
    assert af.brand_casing_from_body("betterup", body) is None
    assert af.recover_brand_casing("Betterup", body) is None


def test_already_cased_or_multiword_names_are_left_alone():
    assert af.recover_brand_casing("BetterUp", "BetterUp everywhere") is None
    assert af.recover_brand_casing("Help Scout", "Help Scout everywhere") is None
    assert af.recover_brand_casing("", "anything") is None


def test_the_alias_map_is_the_layer_between_body_evidence_and_the_token():
    aliases = {"acmeco": "AcmeCo"}
    silent = "About the role\nResponsibilities include shipping.\n" + ("x " * 60)
    # Body evidence missing -> alias map answers.
    assert af.recover_brand_casing("Acmeco", silent, alias_map=aliases) == "AcmeCo"
    # Body evidence WINS over the alias map.
    body = "About AcmeCO\nAcmeCO ships.\nResponsibilities include shipping.\n" + ("x " * 60)
    assert af.recover_brand_casing("Acmeco", body, alias_map={"acmeco": "WrongName"}) == "AcmeCO"
    # The shipped map is generic infrastructure: no real seeds beyond the README.
    shipped = af.load_brand_aliases()
    assert shipped == {}


def test_all_caps_body_styling_is_layout_not_brand_casing():
    body = ("ABOUT OPENLOOPHEALTH\nOPENLOOPHEALTH IS HIRING.\n"
            "Responsibilities include shipping product.\n" + ("x " * 60))
    assert af.brand_casing_from_body("openloophealth", body) is None


# ===========================================================================
# Tranche-4 canary findings: sentence-shaped comp labels, no-colon conjunction
# fusion in ATS source text, and raw HTML in question context lines.
# ===========================================================================
def test_sentence_shaped_comp_label_extracts_the_geography_list():
    """The exact live Airtable shape: a full-sentence label, doubled colon, and a
    bare range with no dollar signs."""
    raw = ("For work locations in the San Francisco Bay Area, Seattle, New York City, "
           "and Los Angeles, the base salary range for this role is:: 195,000–260,000")
    assert pc._base_salary_bands(raw, {"compensation_prose_all": []}, {}) == \
        ["SF Bay Area, Seattle, NYC, and LA: $195-260K"]
    # Variants: single geo, no doubled colon, role/position wording.
    assert pc._base_salary_bands(
        "For employees based in New York City, the salary range for this position "
        "is: $150,000 - $180,000", {"compensation_prose_all": []}, {}) == \
        ["NYC: $150-180K"]
    # A non-sentence band is untouched by the sentence path.
    assert pc._base_salary_bands("Zone A: SF Bay Area / NYC $236K – $296K",
                                 {"compensation_prose_all": []}, {}) == \
        ["Zone A: SF Bay Area / NYC $236-296K"]


def test_bare_amounts_in_a_base_salary_band_gain_their_dollar_signs():
    assert pc._base_salary_bands("195,000–260,000", {"compensation_prose_all": []}, {}) == \
        ["$195-260K"]
    # Non-USD codes stay explicit and un-dollared.
    out = pc._base_salary_bands("CAD 120,000–150,000", {"compensation_prose_all": []}, {})
    assert "CAD" in out[0] and "$" not in out[0]


def test_no_colon_conjunction_fusion_repairs_at_the_element_boundary():
    """(2a): the converter inserts a SPACE when a bare connective ends one inline
    element and the next starts capitalized."""
    html = ("<p><span>Are you based in San Francisco Bay Area or</span>"
            "<span>New York City and willing to come in 2-3x per week?</span></p>")
    text = af._html_to_text(html)
    assert "orNew" not in text
    assert "Bay Area or New York City" in text
    # Intra-word capitals and camelCase in ONE text node are never "repaired"...
    assert af._html_to_text("<p>McDonald builds iPhone apps with ClassDojo.</p>") == \
        "McDonald builds iPhone apps with ClassDojo."
    # ...and mid-word inline markup still joins tightly.
    assert af._html_to_text("<p>This is <strong>bold</strong>face text.</p>") == \
        "This is boldface text."


def test_source_fused_question_labels_are_repaired_at_the_writer():
    """(2b): the fusion existed in the ATS's OWN rendered label text — the writer
    repairs it before it enters the capture."""
    assert af.repair_conjunction_fusion(
        "Are you currently based in San Francisco Bay Area orNew York City?") == \
        "Are you currently based in San Francisco Bay Area or New York City?"
    # Word-boundary anchored: no false repairs.
    for untouched in ("vendorManagement pipeline", "McDonald and iPhone",
                      "Sandbox andOr...", "iHeartMedia"):
        pass
    assert af.repair_conjunction_fusion("vendorManagement") == "vendorManagement"
    assert af.repair_conjunction_fusion("McDonald") == "McDonald"
    q = {"label": "Are you based in San Francisco Bay Area orNew York City and "
                  "willing to come into the office 2-3x per week?",
         "type": "select", "required": True, "name": "q", "names": ["q"],
         "options": ["Yes", "No"]}
    out = pc.build_output_text("http://x", "PM", "Acme", _SYNTH_BODY,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 200,000",
                                     "working_location": "Remote"},
                               questions=[q], methods_tried=["ats"])
    assert "orNew" not in out
    assert "Bay Area or New York City" in out
    # (2c): the gate catches the shape if a writer regression ever reintroduces it.
    import qa_captures
    fused_capture = out.replace("Bay Area or New York City", "Bay Area orNew York City")
    assert any("fused connective" in p
               for p in qa_captures.validate_capture(fused_capture, filename="acme__pm.txt"))
    # And camel brands in the head never trip the gate.
    branded = out.replace("Company: Acme", "Company: iHeartMedia")
    assert not any("fused connective" in p
                   for p in qa_captures.validate_capture(branded, filename="acme__pm.txt"))


def test_html_in_question_context_lines_is_stripped_and_unescaped():
    """(3): help/context text runs through HTML-to-text before entering the capture
    — nested tags gone, entities unescaped, single line."""
    q = {"label": "How are you using AI today in your current role?",
         "type": "textarea", "required": True, "name": "q", "names": ["q"],
         "options": [],
         "help": "<p><em>Share how you currently use AI &amp; automation in your "
                 "work. If you have a <strong>project</strong> to showcase, include "
                 "a link.</em></p>"}
    out = pc.build_output_text("http://x", "PM", "Acme", _SYNTH_BODY,
                               meta={"title": "PM", "structured_source": True,
                                     "compensation": "USD 200,000",
                                     "working_location": "Remote"},
                               questions=[q], methods_tried=["ats"])
    ctx = next(l for l in out.splitlines() if "[Context:" in l)
    assert ctx == ("   [Context: Share how you currently use AI & automation in your "
                   "work. If you have a project to showcase, include a link.]")
    assert "<p>" not in out and "<em>" not in out and "&amp;" not in out
    # An HTML-shaped LABEL cleans too.
    q2 = dict(q, label="<p>Describe your <em>favorite</em> launch.</p>", help=None)
    out2 = pc.build_output_text("http://x", "PM", "Acme", _SYNTH_BODY,
                                meta={"title": "PM", "structured_source": True,
                                      "compensation": "USD 200,000",
                                      "working_location": "Remote"},
                                questions=[q2], methods_tried=["ats"])
    assert "1. Describe your favorite launch. [Required]" in out2
