#!/usr/bin/env python3
"""Validation runner + batch quality gate for Profile Fit.

Runs calibration checks over the isolated scorer's OUTPUT (the same structured results the
production path persists) and decides whether a batch may overwrite stored scores. The gate
HALTS rather than overwrites on any failure. No LLM, no user career data — anchors are
passed in (private) or synthetic (public).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile_fit_reliability as R


def _operating_range(anchor: dict):
    """Prefer the structured operating range; fall back to a legacy accepted_range."""
    lo = anchor.get("operating_range_min")
    hi = anchor.get("operating_range_max")
    if lo is not None and hi is not None:
        return [lo, hi]
    return anchor.get("accepted_range")


def check_anchor(result: dict, anchor: dict) -> dict:
    """Structured-tolerance anchor check for a SINGLE result. Prioritizes reasoning agreement
    over tiny integer agreement, but still detects meaningful drift. Classifies:
      pass                 — score in operating range AND band/pivotal/compounding match
      range_violation      — reasoning matches but score is outside the operating range
      reasoning_mismatch   — pivotal grade / compounding / band expectation differs (substantive)
    """
    led = result.get("ledger", {})
    score = result.get("final_score")
    reasoning = []
    got = R.weakest_thesis_defining_grade(led)
    # A pivotal grade may be pinned to one value (expected_pivotal_grade) OR — when the audit
    # deliberately accepts a one-level wobble on the weakest central (direct<->transferable) — to a
    # set (expected_pivotal_grade_allowed). The allowed-set wins when present.
    allowed_grades = anchor.get("expected_pivotal_grade_allowed")
    if allowed_grades:
        if got not in allowed_grades:
            reasoning.append(f"pivotal grade '{got}' not in allowed {allowed_grades}")
    else:
        exp_grade = anchor.get("expected_pivotal_grade") or anchor.get("pivotal_grade")
        if exp_grade and got != exp_grade:
            reasoning.append(f"pivotal grade '{got}' != expected '{exp_grade}'")
    # Optional floor: every thesis-defining central must be at least this mature (guards the
    # allowed-set case so a real specialization gap can't hide behind the accepted label wobble).
    min_grade = anchor.get("min_thesis_defining_grade")
    if min_grade:
        floor = R.GRADE_RANK.get(min_grade, 0)
        weak = [c.get("grade") for c in R.thesis_defining(led)
                if R.GRADE_RANK.get(c.get("grade"), 0) < floor]
        if weak:
            reasoning.append(f"thesis-defining grade(s) {weak} below floor '{min_grade}'")
    exp_comp = anchor.get("expected_compounding")
    if exp_comp is None:
        exp_comp = anchor.get("compounding")
    if exp_comp is not None and bool(led.get("compounding_applied")) != bool(exp_comp):
        reasoning.append(f"compounding {led.get('compounding_applied')} != expected {exp_comp}")
    exp_band = R.normalize_band(anchor["expected_band"]) if anchor.get("expected_band") else None
    band_ok = (not exp_band) or R.band_of(score) == exp_band or \
        (anchor.get("boundary_straddle_allowed") and R.bands_adjacent(R.band_of(score), exp_band))
    if not band_ok:
        reasoning.append(f"band {R.band_of(score)} not compatible with expected {exp_band}")
    rng = _operating_range(anchor)
    range_ok = (not rng) or (rng[0] <= score <= rng[1])
    if reasoning:
        status = "reasoning_mismatch"
    elif not range_ok:
        status = "range_violation"
    else:
        status = "pass"
    return {"job": anchor.get("job_key"), "status": status, "passed": status == "pass",
            "problems": reasoning + ([] if range_ok else [f"score {score} outside operating range {rng}"]),
            "score": score, "operating_range": rng}


def classify_duplicate(results: list[dict], anchor: dict | None = None, spread_max: int = 5) -> dict:
    """Classify duplicate-control reproducibility with the structured policy:
      pass       — reasoning agrees AND spread <= spread_max AND one band
      placement  — reasoning agrees, scores within the anchor's operating range, spread crosses
                   only ONE adjacent band boundary -> route to adjudication (NOT a batch failure)
      fail       — reasoning differs, score(s) outside operating range, or >1 band boundary crossed
    """
    scores = sorted(r.get("final_score") for r in results if isinstance(r.get("final_score"), int))
    if len(scores) < 2:
        return {"status": "fail", "reason": "need >=2 scorings", "scores": scores}
    spread = scores[-1] - scores[0]
    bands = [R.band_of(s) for s in scores]
    uniq_bands = sorted(set(bands))
    pivotals = {R.weakest_thesis_defining_grade(r.get("ledger", {})) for r in results}
    reasoning_agrees = len(pivotals) == 1
    rng = _operating_range(anchor) if anchor else None
    in_range = (not rng) or all(rng[0] <= s <= rng[1] for s in scores)
    # band boundaries crossed = index distance between the extreme bands (adjacent = 1)
    idxs = [R.BAND_ORDER.index(b) for b in uniq_bands if b in R.BAND_ORDER]
    crossings = (max(idxs) - min(idxs)) if idxs else 0
    out = {"scores": scores, "spread": spread, "bands": uniq_bands, "reasoning_agrees": reasoning_agrees,
           "in_operating_range": in_range, "band_crossings": crossings}
    if not reasoning_agrees or not in_range or crossings > 1:
        out["status"] = "fail"
    elif spread <= spread_max and crossings == 0:
        out["status"] = "pass"
    else:
        # reasoning agrees, within range, one-boundary straddle -> placement adjudication
        allowed = (anchor or {}).get("boundary_straddle_allowed", True)
        out["status"] = "placement" if allowed else "fail"
        out["requires_adjudication"] = (anchor or {}).get("boundary_straddle_requires_adjudication", True)
    return out


# backwards-compatible alias
def duplicate_control(results, spread_max: int = 5):
    r = classify_duplicate(results, None, spread_max)
    r["passed"] = r["status"] == "pass"
    r["same_band"] = r.get("band_crossings", 1) == 0
    r["spread_max"] = spread_max
    return r


def quality_gate(anchor_checks: list[dict], dup: dict | None,
                 results: list[dict], expected_hashes: dict | None = None) -> dict:
    """HALT the batch (do not overwrite stored scores) when any reliability condition fails."""
    failures = []
    placements = []   # legitimate placement-only cases -> route to adjudication, NOT a batch failure
    for ac in anchor_checks:
        st = ac.get("status", "pass" if ac.get("passed") else "reasoning_mismatch")
        if st in ("reasoning_mismatch", "range_violation"):
            failures.append(f"anchor {ac['job']} [{st}]: {'; '.join(ac['problems'])}")
    if dup is not None:
        st = dup.get("status", "pass" if dup.get("passed") else "fail")
        if st == "fail":
            failures.append(f"duplicate control failed: spread {dup.get('spread')} / bands {dup.get('bands')} / reasoning_agrees={dup.get('reasoning_agrees')}")
        elif st == "placement":
            placements.append(f"duplicate control placement-only (spread {dup.get('spread')}, one-boundary straddle, reasoning agrees) -> adjudicate placement")
    for res in results:
        led = res.get("ledger", {})
        errs = R.ledger_completeness_errors(led)
        if errs:
            failures.append(f"{res.get('key')}: incomplete ledger ({errs[0]})")
        if res.get("final_score") is None:
            failures.append(f"{res.get('key')}: missing score")
        # any fail-closed signal from the scorer (a failed pass, an unresolved disagreement)
        v = res.get("validation", {})
        if v.get("failure_reason"):
            failures.append(f"{res.get('key')}: {v['failure_reason']}")
        if v.get("second_pass") and not v.get("adjudicated") \
                and not v.get("adjacent_band_accepted") and v.get("unresolved"):
            failures.append(f"{res.get('key')}: unresolved second-pass disagreement")
    if expected_hashes is not None:
        for res in results:
            ih = res.get("inputs", {})
            for k, want in expected_hashes.items():
                if ih and ih.get(k) not in (None, want):
                    failures.append(f"{res.get('key')}: input hash {k} differs from expected")
    return {"passed": not failures, "failures": failures, "placements": placements}


def run(results_path, anchors_path, dup_keys=None):
    results = json.load(open(results_path))["results"]
    by_key = {r["key"]: r for r in results}
    anchors = json.load(open(anchors_path))["anchors"] if anchors_path and os.path.exists(anchors_path) else []
    anchor_checks = []
    for a in anchors:
        r = by_key.get(a.get("job_key"))
        if r:
            anchor_checks.append(check_anchor(r, a))
    dup = None
    if dup_keys:
        dup_results = [by_key[k] for k in dup_keys if k in by_key]
        if len(dup_results) >= 2:
            dup = duplicate_control(dup_results)
    gate = quality_gate(anchor_checks, dup, results)
    return {"anchor_checks": anchor_checks, "duplicate_control": dup, "gate": gate}


def main(argv):
    ap = argparse.ArgumentParser(description="Validate Profile Fit results against calibration anchors + quality gate.")
    ap.add_argument("--results", required=True)
    ap.add_argument("--anchors", default=None)
    ap.add_argument("--duplicate-keys", nargs="*", default=None)
    ap.add_argument("--report", default=None, help="write a markdown report here")
    a = ap.parse_args(argv[1:])
    out = run(a.results, a.anchors, a.duplicate_keys)
    print(json.dumps({"gate_passed": out["gate"]["passed"],
                      "failures": out["gate"]["failures"],
                      "duplicate": out["duplicate_control"],
                      "anchors_failed": [c["job"] for c in out["anchor_checks"] if not c["passed"]]}, indent=1))
    if a.report:
        lines = ["# Profile Fit — Calibration & Validation Report\n",
                 f"**Gate:** {'PASS ✅' if out['gate']['passed'] else 'HALT ⛔'}\n"]
        if out["duplicate_control"]:
            d = out["duplicate_control"]
            lines.append(f"**Duplicate control:** scores {d['scores']} · spread {d['spread']} "
                         f"(max {d['spread_max']}) · same band {d['same_band']} → {'pass' if d['passed'] else 'FAIL'}\n")
        lines.append("\n## Anchor checks\n")
        for c in out["anchor_checks"]:
            lines.append(f"- {'✅' if c['passed'] else '❌'} **{c['job']}** score {c['score']}"
                         + ("" if c["passed"] else f" — {'; '.join(c['problems'])}"))
        if out["gate"]["failures"]:
            lines.append("\n## Halt reasons\n")
            for f in out["gate"]["failures"]:
                lines.append(f"- {f}")
        open(a.report, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        print("report:", a.report)
    return 0 if out["gate"]["passed"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
