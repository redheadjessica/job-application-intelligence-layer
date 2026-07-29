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
# Voluntary diversity-statement prompts must be EXCLUDED (2026-07-29)
#
# These are free-text, so the compose-a-response keep-rule would otherwise retain
# them, but they are candidate SELF-IDENTIFICATION: they reveal nothing about the
# job and aren't a job-specific response. Real example that slipped through before
# this fix (a Greenhouse post's optional third question).
# --------------------------------------------------------------------------- #
_DIVERSITY_PROMPTS = [
    ("Blue-Rose-style optional diversity statement",
     "Blue Rose Research is invested in advancing the diversity of our teams by "
     "recruiting from underrepresented communities. If you believe you bring a "
     "diverse perspective based on your background, communities or experience, we "
     "invite you to share more here. This is completely optional."),
    ("underrepresented groups phrasing",
     "We recruit from underrepresented groups — tell us about your background."),
    ("diverse perspective phrasing",
     "Do you bring a diverse perspective you'd like to share?"),
]


@pytest.mark.parametrize("name,label", _DIVERSITY_PROMPTS)
def test_voluntary_diversity_statements_are_excluded(name, label):
    fields = [{"label": label, "type": "textarea", "required": False, "options": []}]
    assert af.filter_questions(fields) == [], f"{name} must be dropped"


def test_question_about_building_for_diverse_users_is_kept():
    # Guard against over-exclusion: a genuine job-material question that happens to
    # mention diverse USERS is a compose-a-response question and must SURVIVE.
    fields = [{
        "label": "How would you approach designing an onboarding flow that works for "
                 "a diverse set of users with very different needs?",
        "type": "textarea", "required": True, "options": [],
    }]
    kept = af.filter_questions(fields)
    assert len(kept) == 1
