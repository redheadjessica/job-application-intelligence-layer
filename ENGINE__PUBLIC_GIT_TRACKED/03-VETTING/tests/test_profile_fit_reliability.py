"""Unit tests for the Profile Fit reliability core (deterministic machinery only — no LLM)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import profile_fit_reliability as R


def _central(grade, cls="thesis-defining", req="A central requirement of the role", ev="named evidence"):
    return {"requirement": req, "classification": cls, "grade": grade, "evidence": ev}


def _ledger(score=72, band=None, centrals=None, band_setter="C2 central graded transferable",
            compounding=False, **semantic):
    led = {
        "hiring_thesis": "A real hiring thesis sentence for this role", "narrative_coherence": "coherent",
        "misclassification_check": "applied", "compounding_applied": compounding,
        "band_setter": band_setter, "score": score, "band": band or R.band_of(score),
        "centrals": centrals if centrals is not None else [_central("transferable"), _central("direct")],
    }
    led.update(semantic)
    return led


# --- band_of / completeness -------------------------------------------------- #
def test_band_of():
    assert R.band_of(85) == "82-96"
    assert R.band_of(72) == "68-81"
    assert R.band_of(57) == "50-67"
    assert R.band_of(42) == "30-49"
    assert R.band_of(20) == "0-29"


def test_complete_ledger_has_no_errors():
    assert R.ledger_completeness_errors(_ledger()) == []


def test_incomplete_ledger_flags_missing_and_bad_grade():
    bad = _ledger()
    del bad["band_setter"]
    bad["centrals"][0]["grade"] = "kinda"
    errs = R.ledger_completeness_errors(bad)
    assert any("band_setter" in e for e in errs)
    assert any("grade" in e for e in errs)


def test_endash_band_is_not_an_inconsistency():
    # Scorers often emit the range with a Unicode en-dash ('50–67'); it is the same band as
    # '50-67' and must NOT be flagged as an incomplete/inconsistent ledger.
    led = _ledger(score=63, band="50–67")
    assert R.ledger_completeness_errors(led) == []
    assert R.normalize_band("82–96") == "82-96" and R.bands_adjacent("68–81", "82–96")


def test_band_score_inconsistency_is_caught():
    led = _ledger(score=72, band="82-96")   # 72 is 68-81, not 82-96
    assert any("inconsistent" in e for e in R.ledger_completeness_errors(led))


# --- deterministic flags ----------------------------------------------------- #
def test_absent_thesis_central_flagged():
    led = _ledger(score=42, centrals=[_central("absent"), _central("direct")])
    assert "absent_thesis_central" in R.deterministic_flags(led)


def test_sub68_despite_two_directs_flagged():
    led = _ledger(score=55, centrals=[_central("direct"), _central("direct"), _central("light")])
    assert "sub68_despite_directs" in R.deterministic_flags(led)


def test_big_move_vs_prior():
    led = _ledger(score=42)
    assert "big_move_vs_prior" in R.deterministic_flags(led, prior_score=82)
    assert "big_move_vs_prior" not in R.deterministic_flags(led, prior_score=45)


def test_positive_grade_without_evidence():
    led = _ledger(centrals=[_central("transferable", ev="cannot name"), _central("direct")])
    assert "positive_grade_without_evidence" in R.deterministic_flags(led)


def test_carried_replaced_by_fresh():
    assert "carried_replaced_by_fresh" in R.deterministic_flags(_ledger(), prior_status="carried")


def test_calibration_anchor_violation():
    anchor = {"accepted_range": [80, 90], "expected_band": "82-96"}
    led = _ledger(score=42, band="30-49")
    flags = R.deterministic_flags(led, anchor=anchor)
    assert "calibration_anchor_violation" in flags and "calibration_band_violation" in flags


# --- semantic flags ---------------------------------------------------------- #
def test_semantic_flags_read_only_from_booleans():
    led = _ledger(hiring_thesis_ambiguous=True, posting_requirement_conflict=True)
    assert set(R.semantic_flags(led)) == {"hiring_thesis_ambiguous", "posting_requirement_conflict"}
    assert R.semantic_flags(_ledger()) == []


# --- band-edge modifier ------------------------------------------------------ #
def test_band_edge_alone_does_not_trigger():
    # score 70 is within 3 of the 68 edge, but nothing else is wrong and no prior → no trigger
    led = _ledger(score=70)
    risk = R.assess_risk(led)
    assert not risk.any()


def test_band_edge_triggers_only_when_crossing_priority_boundary_vs_prior():
    # 70 vs prior 66 crosses the 68 boundary and is near the edge, no other flag except big-move?
    led = _ledger(score=70)
    # prior 66: |70-66|=4 (<10, no big_move), near 68 edge, crosses 68 → modifier fires
    risk = R.assess_risk(led, prior_score=66)
    assert risk.any()
    # prior 71: near edge but does NOT cross 68 and no other flag → no trigger
    risk2 = R.assess_risk(led, prior_score=71)
    assert not risk2.any()


# --- acceptance (retain-primary) --------------------------------------------- #
def test_accept_primary_when_two_passes_agree():
    p = _ledger(score=84)
    s = _ledger(score=86)
    cmp = R.compare(p, s, same_thesis=True, same_band_setter=True)
    assert R.acceptance_decision(p, s, cmp) == R.ACCEPT_PRIMARY


def test_fail_incomplete_never_substitutes_second():
    p = _ledger(score=84); del p["band_setter"]   # broken primary
    s = _ledger(score=85)
    cmp = R.compare(p, s, same_thesis=True, same_band_setter=True)
    assert R.acceptance_decision(p, s, cmp) == R.FAIL_INCOMPLETE


def test_require_adjudication_on_material_disagreement():
    p = _ledger(score=42, centrals=[_central("absent"), _central("direct")])
    s = _ledger(score=85, centrals=[_central("transferable"), _central("direct")])
    cmp = R.compare(p, s, same_thesis=True, same_band_setter=False)
    assert R.acceptance_decision(p, s, cmp) == R.REQUIRE_ADJUDICATION


def test_flag_adjudication_on_mild_disagreement():
    p = _ledger(score=70); s = _ledger(score=78)   # spread 8, same band 68-81, same reasoning
    cmp = R.compare(p, s, same_thesis=True, same_band_setter=True)
    assert R.acceptance_decision(p, s, cmp) == R.FLAG_ADJUDICATION


# --- adjacent-band exception (2026-07-31) ------------------------------------ #
def test_adjacent_band_accepts_when_reasoning_matches():
    # Straddle-shaped: 80 (68-81) vs 85 (82-96), spread 5, one-boundary straddle, reasoning agrees.
    p = _ledger(score=80); s = _ledger(score=85)
    cmp = R.compare(p, s, same_thesis=True, same_band_setter=True, same_narrative=True)
    assert cmp.adjacent_band and not cmp.same_band
    assert R.acceptance_decision(p, s, cmp) == R.ACCEPT_PRIMARY


def test_adjacent_band_rejected_when_reasoning_differs():
    p = _ledger(score=80); s = _ledger(score=85)
    cmp = R.compare(p, s, same_thesis=False, same_band_setter=True, same_narrative=True)
    assert R.acceptance_decision(p, s, cmp) == R.REQUIRE_ADJUDICATION


def test_adjacent_band_rejected_when_spread_over_5():
    p = _ledger(score=79); s = _ledger(score=85)   # spread 6
    cmp = R.compare(p, s, same_thesis=True, same_band_setter=True, same_narrative=True)
    assert R.acceptance_decision(p, s, cmp) != R.ACCEPT_PRIMARY


def test_two_band_gap_never_auto_accepts():
    p = _ledger(score=66); s = _ledger(score=70)   # 50-67 vs 68-81 adjacent, spread 4 — allowed IF reasoning matches
    cmp = R.compare(p, s, same_thesis=True, same_band_setter=True, same_narrative=True)
    assert R.acceptance_decision(p, s, cmp) == R.ACCEPT_PRIMARY
    p2 = _ledger(score=48); s2 = _ledger(score=70)  # 30-49 vs 68-81 = TWO bands apart
    cmp2 = R.compare(p2, s2, same_thesis=True, same_band_setter=True, same_narrative=True)
    assert R.acceptance_decision(p2, s2, cmp2) == R.REQUIRE_ADJUDICATION


# --- content-sanity guard (garbage ledger) ----------------------------------- #
def test_content_sanity_rejects_placeholder_ledger():
    garbage = _ledger(score=56, band_setter="test")
    garbage["hiring_thesis"] = "test"
    garbage["centrals"] = [_central("transferable", req="a")]
    errs = R.ledger_completeness_errors(garbage)
    assert any("placeholder" in e or "too short" in e for e in errs)


# --- stable carryover -------------------------------------------------------- #
_H = {"posting_sha256": "a", "profile_sha256": "b", "scoring_card_sha256": "c", "profile_fit_prompt_sha256": "d"}


def test_no_recompute_when_inputs_unchanged():
    stored = {"inputs": dict(_H)}
    recompute, why = R.should_recompute(stored, dict(_H))
    assert recompute is False, why


def test_recompute_when_posting_changes():
    stored = {"inputs": dict(_H)}
    changed = dict(_H); changed["posting_sha256"] = "ZZZ"
    recompute, why = R.should_recompute(stored, changed)
    assert recompute is True and "posting" in why


def test_recompute_on_user_request_integrity_migration():
    stored = {"inputs": dict(_H)}
    assert R.should_recompute(stored, dict(_H), user_requested=True)[0]
    assert R.should_recompute(stored, dict(_H), failed_integrity=True)[0]
    assert R.should_recompute(stored, dict(_H), model_migration=True)[0]


def test_comparable_requires_all_hashes_match():
    a = {"inputs": dict(_H)}
    b = {"inputs": dict(_H)}
    assert R.comparable(a, b)
    b["inputs"]["scoring_card_sha256"] = "different"
    assert not R.comparable(a, b)
