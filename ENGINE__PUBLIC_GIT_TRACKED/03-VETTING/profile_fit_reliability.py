#!/usr/bin/env python3
"""Profile Fit reliability core — the deterministic machinery around the LLM scorer.

WHY THIS EXISTS: the Profile Fit *rubric* reproduces well (a controlled 24-run blind
audit showed 1-6 point spreads with unanimous reasoning), but the 07-30 production run
produced 29-44 point low outliers because it scored Profile Fit in the same overloaded
call as three other dimensions with only a one-sentence prompt. This module is the
public, user-agnostic reliability layer: it never scores anything itself (no LLM, no
career data), it only decides — from STRUCTURED fields — when a single LLM pass may be
trusted, when a second blind pass is required, and whether a stored score may be reused.

DESIGN INVARIANTS (from the reviewed architecture):
  * Deterministic vs semantic split. Python only reasons over structured fields and
    score metadata. Fuzzy judgments ("loosely related specializations", "central-vs-bonus
    ambiguity") are NOT inferred by string heuristics here — the SCORER emits them as
    explicit booleans (see SEMANTIC_FLAG_FIELDS) and Python routes on those booleans.
  * Retain-primary acceptance. When two blind passes agree within threshold, the PRIMARY
    score is retained and the second is recorded as validation. The higher/lower/median is
    never chosen subjectively. An incomplete primary ledger FAILS rather than silently
    falling back to the second.
  * Band-edge is a MODIFIER, not a trigger. Proximity to a band boundary only forces a
    second pass when paired with another risk flag, or when it would move the job across a
    prioritization boundary relative to a pinned prior.

No user-specific data lives in this file. Calibration anchors are passed in by the caller.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional

# --- vocabulary -------------------------------------------------------------- #
GRADES = ("direct", "transferable", "light", "absent")
GRADE_RANK = {"absent": 0, "light": 1, "transferable": 2, "direct": 3}
STATUSES = ("fresh", "carried", "adjudicated", "migrated")

# The §2 Profile-Fit band edges. These are the boundaries at which the *meaning* of the
# score changes ("story doesn't tell it" < 50 <= "needs selling" < 68 <= "credible seam"
# < 82 <= "convincing"). Used only for the band-edge modifier and cross-boundary checks.
BAND_EDGES = (30, 50, 68, 82, 97)

# Semantic ambiguity flags the SCORER emits (booleans). Python must not try to infer these
# from prose — it may only read them. Any True → a second pass is warranted.
SEMANTIC_FLAG_FIELDS = (
    "hiring_thesis_ambiguous",       # thesis names 2+ loosely-related specializations
    "centrality_ambiguous",          # a central's thesis-defining-vs-supporting call is genuinely unclear
    "independent_gap_ambiguity",     # unclear whether 2 weak centrals are one gap or two (compounding risk)
    "posting_requirement_conflict",  # posting is unclear whether the band-setting item is central or bonus
)

BAND_ORDER = ("0-29", "30-49", "50-67", "68-81", "82-96", "97-100")


def normalize_band(b: str) -> str:
    """Canonicalize a band label to ASCII-hyphen form. Scorers frequently emit the range with a
    Unicode en-dash/em-dash/minus ('50–67'); it means exactly the same band as '50-67', so a raw
    string compare must not treat it as an inconsistency."""
    return str(b).translate({0x2012: 0x2d, 0x2013: 0x2d, 0x2014: 0x2d, 0x2212: 0x2d}).strip()


def bands_adjacent(a: str, b: str) -> bool:
    """True when two bands differ by exactly one step (e.g. 68-81 vs 82-96)."""
    a, b = normalize_band(a), normalize_band(b)
    if a not in BAND_ORDER or b not in BAND_ORDER:
        return False
    return abs(BAND_ORDER.index(a) - BAND_ORDER.index(b)) == 1


# The band an integer score falls in (matches the card's §2 anchors).
def band_of(score: int) -> str:
    s = int(score)
    if s >= 97: return "97-100"
    if s >= 82: return "82-96"
    if s >= 68: return "68-81"
    if s >= 50: return "50-67"
    if s >= 30: return "30-49"
    return "0-29"


def sha256_file(path) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def input_hashes(posting_path, profile_path, card_path, prompt_path) -> dict:
    """The four hashes that make two scores directly comparable. If any differ between a
    stored score and a fresh one, a numeric difference is NOT a 'movement' — it is a
    different measurement, and the tracker must not present it as drift."""
    return {
        "posting_sha256": sha256_file(posting_path),
        "profile_sha256": sha256_file(profile_path),
        "scoring_card_sha256": sha256_file(card_path),
        "profile_fit_prompt_sha256": sha256_file(prompt_path),
    }


# --- ledger -------------------------------------------------------------------- #
# A Profile-Fit ledger is a plain dict with these keys (the scorer's structured output).
LEDGER_REQUIRED = (
    "hiring_thesis", "centrals", "narrative_coherence", "misclassification_check",
    "compounding_applied", "band_setter", "band", "score",
)
CENTRAL_REQUIRED = ("requirement", "classification", "grade", "evidence")


def ledger_completeness_errors(led: dict) -> list[str]:
    """Return a list of reasons the ledger is incomplete. Empty list == complete.
    An incomplete PRIMARY ledger fails validation (retain-primary rule): we never
    silently substitute the second pass for a broken first pass."""
    errs = []
    if not isinstance(led, dict):
        return ["ledger is not an object"]
    for k in LEDGER_REQUIRED:
        if k not in led or led[k] in (None, ""):
            errs.append(f"missing field: {k}")
    cs = led.get("centrals")
    if not isinstance(cs, list) or not cs:
        errs.append("centrals missing or empty")
    else:
        for i, c in enumerate(cs):
            for k in CENTRAL_REQUIRED:
                if not isinstance(c, dict) or c.get(k) in (None, ""):
                    errs.append(f"central[{i}] missing {k}")
            if isinstance(c, dict) and c.get("grade") not in GRADES:
                errs.append(f"central[{i}] grade '{c.get('grade')}' not one of {GRADES}")
    if isinstance(led.get("band_setter"), str) and not led["band_setter"].strip():
        errs.append("band_setter is blank")
    # Content-sanity guard: a schema-valid but PLACEHOLDER ledger (the 2026-07-31 validation
    # caught one with hiring_thesis="test", central="a") must fail closed, not enter the pool.
    _PLACEHOLDER = {"", "test", "n/a", "na", "tbd", "todo", "none", "..."}
    for fld in ("hiring_thesis", "band_setter"):
        v = str(led.get(fld, "")).strip()
        if v.lower() in _PLACEHOLDER or len(v) < 12:
            errs.append(f"{fld} looks like placeholder/too-short content ({v!r})")
    for i, c in enumerate(led.get("centrals", []) or []):
        if isinstance(c, dict) and len(str(c.get("requirement", "")).strip()) < 4:
            errs.append(f"central[{i}] requirement too short to be real")
    # score/band internal consistency (a structured, deterministic check)
    if isinstance(led.get("score"), int) and led.get("band"):
        if band_of(led["score"]) != normalize_band(led["band"]):
            errs.append(f"band '{led['band']}' inconsistent with score {led['score']} (expected {band_of(led['score'])})")
    return errs


def thesis_defining(led: dict) -> list[dict]:
    return [c for c in led.get("centrals", []) if c.get("classification") == "thesis-defining"]


def weakest_thesis_defining_grade(led: dict) -> Optional[str]:
    td = thesis_defining(led)
    if not td:
        return None
    return min((c.get("grade") for c in td), key=lambda g: GRADE_RANK.get(g, 9))


# --- risk detection ------------------------------------------------------------ #
@dataclass
class RiskResult:
    deterministic: list[str] = field(default_factory=list)   # flag names Python derived
    semantic: list[str] = field(default_factory=list)        # scorer-emitted booleans that are True
    band_edge_modifier: bool = False                          # fired only per the paired/cross rule
    def any(self) -> bool:
        return bool(self.deterministic or self.semantic or self.band_edge_modifier)


def _crosses_priority_boundary(score: int, prior: Optional[int]) -> bool:
    if prior is None:
        return False
    lo, hi = sorted((int(score), int(prior)))
    return any(lo < e <= hi for e in BAND_EDGES)


def deterministic_flags(led: dict, prior_score: Optional[int] = None,
                        prior_status: Optional[str] = None,
                        anchor: Optional[dict] = None) -> list[str]:
    """Flags derivable from STRUCTURED fields only — no prose interpretation."""
    flags = []
    td = thesis_defining(led)
    if any(c.get("grade") == "absent" for c in td):
        flags.append("absent_thesis_central")
    band = str(led.get("band", ""))
    below68 = isinstance(led.get("score"), int) and led["score"] < 68
    if any(c.get("grade") == "light" for c in td) and below68:
        flags.append("light_thesis_central_sub68")
    if led.get("compounding_applied") is True:
        flags.append("compounding")
    directs = sum(1 for c in led.get("centrals", []) if c.get("grade") == "direct")
    if below68 and directs >= 2:
        flags.append("sub68_despite_directs")          # structured proxy for score-vs-evidence conflict
    if prior_score is not None and isinstance(led.get("score"), int) \
            and abs(led["score"] - int(prior_score)) >= 10:
        flags.append("big_move_vs_prior")
    for c in led.get("centrals", []):
        if c.get("grade") in ("direct", "transferable"):
            ev = (c.get("evidence") or "").strip().lower()
            if ev in ("", "cannot name", "n/a", "none"):
                flags.append("positive_grade_without_evidence")
                break
    if not str(led.get("band_setter", "")).strip():
        flags.append("missing_band_setter")
    if prior_status == "carried":
        flags.append("carried_replaced_by_fresh")
    if anchor is not None and isinstance(led.get("score"), int):
        rng = anchor.get("accepted_range")
        if rng and not (rng[0] <= led["score"] <= rng[1]):
            flags.append("calibration_anchor_violation")
        if anchor.get("expected_band") and str(led.get("band")) != anchor["expected_band"]:
            flags.append("calibration_band_violation")
    return flags


def semantic_flags(led: dict) -> list[str]:
    return [f for f in SEMANTIC_FLAG_FIELDS if led.get(f) is True]


def assess_risk(led: dict, prior_score: Optional[int] = None,
                prior_status: Optional[str] = None, anchor: Optional[dict] = None) -> RiskResult:
    det = deterministic_flags(led, prior_score, prior_status, anchor)
    sem = semantic_flags(led)
    # Band-edge is a MODIFIER: it only fires a second pass when (a) something else already
    # flagged — in which case the second pass fires anyway — OR (b) it would move the job
    # across a prioritization boundary relative to a pinned prior. Proximity alone never fires.
    # When det/sem already flagged, a second pass fires regardless — the modifier only
    # MATTERS as a standalone reason: near a band edge AND crossing a prioritization
    # boundary versus a pinned prior. Proximity alone never fires.
    edge = False
    if isinstance(led.get("score"), int) and not (det or sem):
        near_edge = any(abs(led["score"] - e) <= 3 for e in BAND_EDGES)
        edge = near_edge and _crosses_priority_boundary(led["score"], prior_score)
    return RiskResult(deterministic=det, semantic=sem, band_edge_modifier=edge)


def needs_second_pass(risk: RiskResult) -> bool:
    return risk.any()


# --- two-pass comparison & retain-primary acceptance --------------------------- #
@dataclass
class Comparison:
    spread: int
    same_band: bool
    adjacent_band: bool        # bands differ by exactly one step
    same_thesis: bool          # caller supplies the semantic thesis-match judgment
    same_pivotal_grade: bool
    same_band_setter: bool     # caller supplies the semantic band-setter-match judgment
    same_narrative: bool       # caller supplies the semantic narrative-coherence-match judgment
    grade_levels_apart: int    # how many grade levels the pivotal grades differ by
    compounding_differs: bool


def compare(primary: dict, second: dict, same_thesis: bool, same_band_setter: bool,
            same_narrative: bool = True) -> Comparison:
    """Numeric + structured comparison. `same_thesis` / `same_band_setter` / `same_narrative`
    are SEMANTIC equivalence judgments the caller (an adjudicator or a human) supplies —
    Python does not decide thesis identity by string match."""
    ps, ss = primary.get("score"), second.get("score")
    both_int = isinstance(ps, int) and isinstance(ss, int)
    spread = abs(int(ps) - int(ss)) if both_int else 999
    pg = weakest_thesis_defining_grade(primary)
    sg = weakest_thesis_defining_grade(second)
    lvl = abs(GRADE_RANK.get(pg, 0) - GRADE_RANK.get(sg, 0)) if pg and sg else 9
    return Comparison(
        spread=spread,
        same_band=band_of(ps) == band_of(ss) if both_int else False,
        adjacent_band=bands_adjacent(band_of(ps), band_of(ss)) if both_int else False,
        same_thesis=same_thesis,
        same_pivotal_grade=(pg == sg),
        same_band_setter=same_band_setter,
        same_narrative=same_narrative,
        grade_levels_apart=lvl,
        compounding_differs=bool(primary.get("compounding_applied")) != bool(second.get("compounding_applied")),
    )


# acceptance decisions
ACCEPT_PRIMARY = "accept_primary"          # two passes agree; retain PRIMARY, record 2nd as validation
FLAG_ADJUDICATION = "flag_adjudication"    # soft: mild disagreement, optional adjudication
REQUIRE_ADJUDICATION = "require_adjudication"  # hard: material disagreement, must adjudicate
FAIL_INCOMPLETE = "fail_incomplete"        # primary ledger broken; do not substitute the 2nd


def acceptance_decision(primary: dict, second: dict, cmp: Comparison,
                        spread_accept: int = 5, spread_soft: int = 10) -> str:
    """Retain-primary rule. Never picks the 'better' of two subjectively.

    Adjacent-band exception (added 2026-07-31): a spread of 0-5 with fully-matching
    substantive reasoning may ACCEPT even when the two scores straddle ONE adjacent band
    boundary — but ONLY when hiring thesis, pivotal grade, band-setter, compounding, AND
    narrative-coherence all match. It never applies when the reasoning differs or spread > 5.
    """
    if ledger_completeness_errors(primary):
        return FAIL_INCOMPLETE
    reasoning_matches = (cmp.same_thesis and cmp.same_pivotal_grade and cmp.same_band_setter
                         and cmp.same_narrative and not cmp.compounding_differs)
    # Straightforward accept: same band + reasoning + tight spread.
    if cmp.spread <= spread_accept and cmp.same_band and reasoning_matches:
        return ACCEPT_PRIMARY
    # Adjacent-band exception: one-boundary straddle, tight spread, reasoning fully matches.
    if cmp.spread <= spread_accept and cmp.adjacent_band and reasoning_matches:
        return ACCEPT_PRIMARY
    material = (cmp.spread > spread_soft or cmp.grade_levels_apart > 1 or cmp.compounding_differs
               or not cmp.same_thesis or not cmp.same_band_setter
               or (not cmp.same_band and not cmp.adjacent_band))
    if material:
        return REQUIRE_ADJUDICATION
    return FLAG_ADJUDICATION


# --- provenance & stable carryover -------------------------------------------- #
@dataclass
class Provenance:
    job_key: str
    score: int
    band: str
    date_scored: str
    status: str                      # fresh | carried | adjudicated | migrated
    inputs: dict                     # the four hashes + model/config
    ledger: dict                     # thesis, thesis-defining centrals, pivotal grades, coherence, compounding, band-setter
    risk_flags: list
    validation: dict                 # {second_pass: bool, adjudicated: bool, passes: [...]}
    def to_dict(self) -> dict:
        return asdict(self)


# The ONLY reasons a stored Profile Fit score may be recomputed. A workbook rebuild,
# pipeline refactor, added/removed job, re-sort, or a change to another dimension is NOT
# among them.
def should_recompute(stored: dict, current_hashes: dict, *, user_requested: bool = False,
                     failed_integrity: bool = False, model_migration: bool = False) -> tuple[bool, str]:
    if stored is None:
        return True, "no stored score"
    if user_requested:
        return True, "user requested rescore"
    if failed_integrity:
        return True, "failed integrity/reliability check"
    if model_migration:
        return True, "model migration requires recalibration"
    si = stored.get("inputs", {})
    for k in ("posting_sha256", "profile_sha256", "scoring_card_sha256", "profile_fit_prompt_sha256"):
        if si.get(k) != current_hashes.get(k):
            return True, f"material input changed: {k}"
    return False, "inputs+logic unchanged — reuse stored score (stable carryover)"


def comparable(a: dict, b: dict) -> bool:
    """Two provenance records describe directly-comparable measurements iff all four input
    hashes match. Otherwise a numeric difference is not a 'movement'."""
    ia, ib = a.get("inputs", {}), b.get("inputs", {})
    return all(ia.get(k) == ib.get(k) for k in
               ("posting_sha256", "profile_sha256", "scoring_card_sha256", "profile_fit_prompt_sha256"))
