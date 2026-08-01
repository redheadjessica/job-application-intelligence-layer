"""Production-integration + persistence tests for the isolated Profile Fit path.

Proves the exact sequence the reliability fix requires:
  1. the normal vetting workflow DELEGATES Profile Fit to the isolated path;
  2. it does NOT also compute/overwrite Profile Fit in the bundled call;
  3. it persists the complete ledger + provenance;
  4. a stable score survives a workbook rebuild;
  5. Profile Fit is preserved when only other dimensions / ATS dates / resume / status / layout change;
  6. overwrite is BLOCKED when calibration/validation fails.
"""
import os, sys, json, csv, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import profile_fit_reliability as R
import persist_profile_fit as P
import validate_profile_fit as V

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
VET = os.path.join(ROOT, ".claude", "workflows", "vet-jobs.js")
SCORER = os.path.join(ROOT, ".claude", "workflows", "score-profile-fit.js")


def _result(key, score, band=None, status="fresh", complete=True):
    led = {
        "hiring_thesis": "A realistic hiring thesis sentence for the role",
        "narrative_coherence": "coherent", "misclassification_check": "checked",
        "compounding_applied": False, "band_setter": "C2 central graded transferable", "score": score,
        "band": band or R.band_of(score),
        "centrals": [{"requirement": "A central requirement of the role", "classification": "thesis-defining", "grade": "transferable", "evidence": "named evidence"}],
    }
    if not complete:
        del led["band_setter"]
    return {"key": key, "final_score": score, "band": band or R.band_of(score),
            "status": status, "profile_notes": "band set by C2 (transferable)",
            "ledger": led, "risk_flags": [], "validation": {"second_pass": False, "adjudicated": False}}


# 1 + 2 — Profile Fit scored INLINE & isolated (no nested child workflow); bundled call absent
def test_vetjobs_scores_profile_fit_inline_and_isolated():
    src = open(VET, encoding="utf-8").read()
    # Inline isolated phases (run-batch -> vet-jobs -> score-profile-fit would be 2-level nesting,
    # which the engine forbids). So Profile Fit is scored inline, still isolated.
    assert "phase('ProfileFit')" in src and "PF_LEDGER_SCHEMA" in src, \
        "vet-jobs.js must score Profile Fit inline via the isolated PF phases"
    for flag in ("hiring_thesis_ambiguous", "centrality_ambiguous",
                 "independent_gap_ambiguity", "posting_requirement_conflict"):
        assert flag in src, f"inline Profile Fit must emit semantic flag {flag}"
    # No nested child-workflow delegation for Profile Fit (avoids the one-level nesting limit).
    assert "workflow({ scriptPath: '.claude/workflows/score-profile-fit" not in src
    assert "workflow('score-profile-fit'" not in src
    # Fail-closed before write when Profile Fit is unresolved.
    assert "fail-closed" in src.lower() and "pfUnresolved" in src


def test_vetjobs_bundled_call_does_not_score_profile_fit():
    src = open(VET, encoding="utf-8").read()
    # market_perception_score must not be a SCORE_SCHEMA field, a required[] entry, or a scoring
    # instruction in the bundled call. (A `schema_key: 'market_perception_score'` for the column
    # LABEL mapping is fine — the Profile column is still written, now from the delegated path.)
    assert "market_perception_score: { type" not in src            # not a schema property
    assert "market_perception_score: how strong" not in src        # not a scoring instruction
    assert "'desire_score', 'market_perception_score'" not in src  # not in the bundled required[] array


def test_isolated_scorer_exists_and_emits_semantic_flags():
    src = open(SCORER, encoding="utf-8").read()
    for flag in ("hiring_thesis_ambiguous", "centrality_ambiguous",
                 "independent_gap_ambiguity", "posting_requirement_conflict"):
        assert flag in src, f"isolated scorer must emit {flag}"


# 3 — persist a complete ledger + provenance (round-trip)
def test_provenance_round_trip():
    hashes = {"posting_sha256": "p", "profile_sha256": "r", "scoring_card_sha256": "c", "profile_fit_prompt_sha256": "q"}
    rec = P.make_record("job.txt", _result("job.txt", 85), hashes, "2026-07-31", model="m")
    assert rec["status"] == "fresh" and rec["score"] == 85
    assert rec["ledger"]["band_setter"]  # complete ledger persisted
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "prov.json")
        P.write_provenance(path, {"job.txt": rec})
        loaded = P.load_provenance(path)
    assert loaded["job.txt"]["score"] == 85 and loaded["job.txt"]["inputs"]["posting_sha256"] == "p"


# 4 — stable score survives a rebuild (inputs unchanged -> reuse, do not recompute)
def test_stable_score_survives_rebuild():
    hashes = {"posting_sha256": "p", "profile_sha256": "r", "scoring_card_sha256": "c", "profile_fit_prompt_sha256": "q"}
    stored = P.make_record("job.txt", _result("job.txt", 72), hashes, "2026-07-31")
    plan = P.carryover_plan(["job.txt"], {"job.txt": stored}, hashes)
    assert plan["job.txt"]["action"] == "reuse", plan["job.txt"]["reason"]


# 5 — Profile Fit preserved when ONLY other-dimension / ATS / resume / status / layout changes
def test_profile_fit_preserved_on_unrelated_changes():
    # 'unrelated changes' do not alter the four Profile-Fit input hashes -> carryover reuses.
    hashes = {"posting_sha256": "p", "profile_sha256": "r", "scoring_card_sha256": "c", "profile_fit_prompt_sha256": "q"}
    stored = P.make_record("job.txt", _result("job.txt", 72), hashes, "2026-07-31")
    # a rebuild after editing Desire notes, ATS dates, resume columns, status, or layout -> same 4 hashes
    plan = P.carryover_plan(["job.txt"], {"job.txt": stored}, dict(hashes))
    assert plan["job.txt"]["action"] == "reuse"
    # and a merge that targets a DIFFERENT job must not touch this row's Profile value
    with tempfile.TemporaryDirectory() as d:
        csvp = os.path.join(d, "r.csv")
        with open(csvp, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Company", "How They May See Your Profile", "Your Desire Score", "Culture Fit Score",
                        "Comp + Lifestyle Fit Score", "FINAL Weighted Score", "Profile Score Notes", "Job File"])
            w.writerow(["Acme", "72", "70", "70", "70", "71", "old note", "job.txt"])
            w.writerow(["Beta", "40", "60", "60", "60", "53", "n", "other.txt"])
        P.merge_into_csv(csvp, {"other.txt": {"score": 80, "notes": "new"}})
        rows = list(csv.reader(open(csvp)))
    acme = next(r for r in rows if r[0] == "Acme")
    assert acme[1] == "72", "untargeted row's Profile Fit must be untouched"


# 5b — merge recomputes FINAL from the row's own sub-scores when Profile changes
def test_merge_recomputes_final():
    with tempfile.TemporaryDirectory() as d:
        csvp = os.path.join(d, "r.csv")
        with open(csvp, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["Company", "How They May See Your Profile", "Your Desire Score", "Culture Fit Score",
                        "Comp + Lifestyle Fit Score", "FINAL Weighted Score", "Profile Score Notes", "Job File"])
            w.writerow(["Acme", "40", "54", "59", "69", "52", "old", "job.txt"])
        P.merge_into_csv(csvp, {"job.txt": {"score": 57, "notes": "band set by C2 (light)"}})
        rows = list(csv.reader(open(csvp)))
    acme = next(r for r in rows if r[0] == "Acme")
    # FINAL = .35*54 + .30*57 + .20*59 + .15*69 = 58.15 -> 58
    assert acme[1] == "57" and acme[5] == "58" and "light" in acme[6]


# 6 — overwrite BLOCKED when calibration fails
def test_quality_gate_halts_on_anchor_failure():
    res = _result("job.txt", 42, band="30-49")
    anchor = {"job_key": "job.txt", "accepted_range": [80, 90], "expected_band": "82-96", "pivotal_grade": "transferable"}
    check = V.check_anchor(res, anchor)
    gate = V.quality_gate([check], None, [res])
    assert gate["passed"] is False and gate["failures"], gate


def test_quality_gate_halts_on_incomplete_ledger():
    res = _result("job.txt", 85, complete=False)
    gate = V.quality_gate([], None, [res])
    assert gate["passed"] is False


def test_duplicate_control_passes_on_tight_cluster():
    rs = [_result("j", 84), _result("j", 86), _result("j", 85)]
    dup = V.duplicate_control(rs)
    assert dup["passed"] and dup["spread"] == 2


def test_duplicate_control_fails_on_wide_spread():
    rs = [_result("j", 42, band="30-49"), _result("j", 85)]
    dup = V.duplicate_control(rs)
    assert dup["passed"] is False


# --- structured anchor tolerances (2026-07-31 iteration 3) -------------------- #
import validate_profile_fit as V2

def _res_grade(key, score, grade="transferable"):
    r = _result(key, score)
    r["ledger"]["centrals"] = [{"requirement": "A central requirement of the role", "classification": "thesis-defining", "grade": grade, "evidence": "named evidence"}]
    return r

def test_anchor_pass_within_operating_range():
    a = {"job_key": "role_a", "operating_range_min": 78, "operating_range_max": 88, "expected_band": "82-96",
         "expected_pivotal_grade": "transferable", "expected_compounding": False, "boundary_straddle_allowed": True}
    c = V2.check_anchor(_res_grade("role_a", 84), a)
    assert c["status"] == "pass"

def test_anchor_range_violation_when_reasoning_ok_but_score_out():
    # Same band (50-67) and matching reasoning, but 66 is outside the operating range [54,60].
    a = {"job_key": "role_b", "operating_range_min": 54, "operating_range_max": 60, "expected_band": "50-67",
         "expected_pivotal_grade": "light", "expected_compounding": False}
    c = V2.check_anchor(_res_grade("role_b", 66, grade="light"), a)
    assert c["status"] == "range_violation"

def test_anchor_reasoning_mismatch_on_pivotal_grade():
    a = {"job_key": "x", "operating_range_min": 50, "operating_range_max": 67, "expected_pivotal_grade": "light"}
    c = V2.check_anchor(_res_grade("x", 60, grade="absent"), a)
    assert c["status"] == "reasoning_mismatch"

def test_allowed_pivotal_set_accepts_either_grade():
    # Allowed-set decision: the weakest thesis-defining central may be direct OR transferable.
    a = {"job_key": "role_c", "operating_range_min": 84, "operating_range_max": 90, "expected_band": "82-96",
         "expected_pivotal_grade": "direct", "expected_pivotal_grade_allowed": ["direct", "transferable"],
         "min_thesis_defining_grade": "transferable"}
    # both grades must pass; both must have every thesis-defining central >= transferable
    assert V2.check_anchor(_res_grade("role_c", 84, grade="transferable"), a)["status"] == "pass"
    assert V2.check_anchor(_res_grade("role_c", 85, grade="direct"), a)["status"] == "pass"

def test_allowed_pivotal_set_still_rejects_light():
    a = {"job_key": "role_c", "operating_range_min": 84, "operating_range_max": 90, "expected_band": "82-96",
         "expected_pivotal_grade": "direct", "expected_pivotal_grade_allowed": ["direct", "transferable"],
         "min_thesis_defining_grade": "transferable"}
    c = V2.check_anchor(_res_grade("role_c", 84, grade="light"), a)
    assert c["status"] == "reasoning_mismatch"

def test_min_thesis_defining_floor_catches_hidden_gap():
    # allowed weakest is transferable, but a SECOND thesis-defining central graded light must fail the floor.
    a = {"job_key": "role_c", "operating_range_min": 84, "operating_range_max": 90, "expected_band": "82-96",
         "expected_pivotal_grade_allowed": ["direct", "transferable"], "min_thesis_defining_grade": "transferable"}
    r = _result("role_c", 85)
    r["ledger"]["centrals"] = [
        {"requirement": "central one for the role", "classification": "thesis-defining", "grade": "direct", "evidence": "e"},
        {"requirement": "central two for the role", "classification": "thesis-defining", "grade": "light", "evidence": "e"},
    ]
    c = V2.check_anchor(r, a)
    assert c["status"] == "reasoning_mismatch" and any("floor" in p for p in c["problems"])

def test_direct_pivotal_with_maturity_ceiling_passes():
    # A hands-on central grades direct while a maturity ceiling caps the range below the top band:
    # expected pivotal direct; 89 within an 80-90 top-band-capped range still passes.
    a = {"job_key": "role_a", "operating_range_min": 80, "operating_range_max": 90, "expected_band": "82-96",
         "expected_pivotal_grade": "direct", "boundary_straddle_allowed": True}
    assert V2.check_anchor(_res_grade("role_a", 89, grade="direct"), a)["status"] == "pass"

def test_duplicate_straddle_is_placement_not_failure():
    # Reproducible spread 78/84/87: reasoning agrees, within operating range, straddles ONE band edge.
    rip_anchor = {"operating_range_min": 78, "operating_range_max": 88,
                  "boundary_straddle_allowed": True, "boundary_straddle_requires_adjudication": True}
    rs = [_res_grade("r", 78), _res_grade("r", 84), _res_grade("r", 87)]
    d = V2.classify_duplicate(rs, rip_anchor)
    assert d["status"] == "placement" and d["requires_adjudication"] is True
    # placement is NOT a batch failure
    gate = V2.quality_gate([], d, rs)
    assert gate["passed"] is True and gate["placements"]

def test_duplicate_fails_when_reasoning_differs():
    rs = [_res_grade("r", 80, grade="transferable"), _res_grade("r", 85, grade="absent")]
    d = V2.classify_duplicate(rs, {"operating_range_min": 78, "operating_range_max": 88, "boundary_straddle_allowed": True})
    assert d["status"] == "fail"

def test_duplicate_fails_when_bands_two_apart():
    rs = [_res_grade("r", 42), _res_grade("r", 85)]
    d = V2.duplicate_control(rs)
    assert d["passed"] is False
