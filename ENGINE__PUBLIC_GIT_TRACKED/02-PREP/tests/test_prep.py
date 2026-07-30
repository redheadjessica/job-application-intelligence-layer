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
    assert "[CONFLICT]" in out


# 9 --------------------------------------------------------------------------
def test_golden_output_is_stable():
    res, kept = _ashby_result_with_questions()
    fs = pc.assess_completeness(res, res["text"], kept)
    out = pc.build_output_text(
        "https://jobs.ashbyhq.com/betterup/fa0a5d05-39f9-47d5-9fc9-0a0540ff9018",
        res["title"], res["company"], res["text"], meta=res, questions=kept,
        field_status=fs, methods_tried=["ats", "playwright"], captured="2026-07-29")
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
    """POLISH: a verbatim label that already ends in a stray double-quote must not
    render a doubled trailing quote (the Bloomerang question-2 bug)."""
    q = {"label": 'How are you using modern AI tools for accelerating delivery?"',
         "type": "textarea", "source_type": "LongText", "required": True,
         "name": "q", "names": ["q"], "options": []}
    out = pc.build_output_text("http://x", "PM", "Acme", "Responsibilities...",
                               questions=[q], methods_tried=["ats"])
    assert 'delivery?""' not in out
    assert 'delivery?"' in out


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
    # And the normalized Compensation line shows the prose figure, marked as such.
    out = pc.build_output_text("http://x", "Staff Engineer", "Acme", body,
                               meta=meta, field_status=fs, methods_tried=["requests"])
    assert "174,000" in out and "(from description)" in out


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
    assert "Equity: Mentioned (no details)" in out
    assert "Benefits: Mentioned (no details)" in out
    assert "Equity: Not posted" not in out and "Benefits: Not posted" not in out


def test_a_posting_that_says_nothing_still_reports_not_posted():
    """The third state must not swallow the genuine "employer published nothing" case."""
    benefits, equity = af.mine_benefits_equity(
        "About the role\nResponsibilities include shipping product every quarter.")
    assert benefits is None and equity is None
    out = pc.build_output_text("http://x", "PM", "Acme", "Responsibilities...",
                               meta={"title": "PM"}, field_status={"conflicts": []})
    assert "Benefits: Not posted" in out and "Equity: Not posted" in out


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


def test_verbatim_source_fields_are_populated_from_prose_when_structured_is_absent():
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
    assert 'Compensation (verbatim): ""' not in out
    assert 'Locations/Addresses (verbatim): ""' not in out
    # The prose line carries a cadence ("3 days per week"), so cadence isn't blank either.
    assert 'Office cadence (verbatim): ""' not in out


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
    assert "[CONFLICT]" in out


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
