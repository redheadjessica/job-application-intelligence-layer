#!/usr/bin/env python3
"""Persistence + stable-carryover for Profile Fit scores.

Consumes the structured results from the isolated `score-profile-fit` workflow and:
  * writes a private provenance ledger (one record per job) — NOT a user-facing column;
  * enforces stable carryover: a stored score is reused unchanged unless a material input
    hash changed / the user asked / an integrity check failed / a model migration ran;
  * merges (re)scored Profile Fit values into the rankings CSV surgically — Profile Fit +
    its Profile Score Notes + the dependent FINAL, touching NOTHING else.

No LLM, no user career data. All reasoning defers to profile_fit_reliability.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import profile_fit_reliability as R

H_MARKET = "How They May See Your Profile"
H_FINAL = "FINAL Weighted Score"
H_NOTES = "Profile Score Notes"
H_JOBFILE = "Job File"
H_DESIRE = "Your Desire Score"
H_STYLE = "Culture Fit Score"
H_PRACT = "Comp + Lifestyle Fit Score"
WEIGHTS = {"desire": 0.35, "market": 0.30, "style": 0.20, "practicality": 0.15}


# --- provenance I/O ---------------------------------------------------------- #
def load_provenance(path) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return {r["job_key"]: r for r in data.get("records", [])}


def write_provenance(path, records_by_key: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {"schema": "profile-fit-provenance/v1",
               "records": list(records_by_key.values())}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def make_record(job_key, result, hashes, date_scored, model="unknown") -> dict:
    """Build a provenance record from an isolated-scorer result dict."""
    led = result.get("ledger", {})
    return R.Provenance(
        job_key=job_key,
        score=result["final_score"],
        band=result.get("band") or R.band_of(result["final_score"]),
        date_scored=date_scored,
        status=result.get("status", "fresh"),
        inputs={**hashes, "model": model},
        ledger={
            "hiring_thesis": led.get("hiring_thesis"),
            "thesis_defining_centrals": [c.get("requirement") for c in led.get("centrals", [])
                                         if c.get("classification") == "thesis-defining"],
            "pivotal_evidence_grades": {c.get("requirement"): c.get("grade") for c in led.get("centrals", [])},
            "narrative_coherence": led.get("narrative_coherence"),
            "compounding": led.get("compounding_applied"),
            "band_setter": result.get("profile_notes") or led.get("band_setter"),
        },
        risk_flags=result.get("risk_flags", []),
        validation=result.get("validation", {}),
    ).to_dict()


# --- stable carryover -------------------------------------------------------- #
def carryover_plan(job_keys, stored: dict, current_hashes: dict, *,
                   force_keys=None, model_migration=False) -> dict:
    """Decide, per job, whether to SCORE (fresh/rescore) or REUSE the stored value.
    Returns {key: {"action": "score"|"reuse", "reason": str}}."""
    force_keys = set(force_keys or [])
    plan = {}
    for k in job_keys:
        recompute, why = R.should_recompute(
            stored.get(k), current_hashes,
            user_requested=(k in force_keys), model_migration=model_migration)
        plan[k] = {"action": "score" if recompute else "reuse", "reason": why}
    return plan


# --- surgical CSV merge ------------------------------------------------------ #
def _col(headers, name):
    for i, h in enumerate(headers):
        if (h or "").strip().lower() == name.lower():
            return i
    for i, h in enumerate(headers):
        if name.lower() in (h or "").lower():
            return i
    return None


def merge_into_csv(csv_path, updates: dict) -> list[str]:
    """updates: {job_file_substring: {"score": int, "notes": str}}. Sets Profile Fit +
    Profile Score Notes and recomputes FINAL from the row's own other sub-scores. Touches
    no other row and no other column. Returns the list of job_files updated."""
    rows = list(csv.reader(open(csv_path, newline="", encoding="utf-8")))
    hdr = rows[0]
    cm, cf, cn, cjf = (_col(hdr, H_MARKET), _col(hdr, H_FINAL), _col(hdr, H_NOTES), _col(hdr, H_JOBFILE))
    cd, cs, cp = (_col(hdr, H_DESIRE), _col(hdr, H_STYLE), _col(hdr, H_PRACT))
    if None in (cm, cf, cjf):
        raise SystemExit(f"CSV missing required columns (market/final/jobfile): {cm},{cf},{cjf}")
    touched = []
    for r in rows[1:]:
        jf = r[cjf] if cjf < len(r) else ""
        for key, upd in updates.items():
            if key and key in jf:
                r[cm] = str(upd["score"])
                if cn is not None and upd.get("notes"):
                    r[cn] = upd["notes"]
                # recompute FINAL from the row's own sub-scores (Profile Fit changed only)
                try:
                    d = int(r[cd]); s = int(r[cs]); p = int(r[cp])
                    r[cf] = str(round(d * WEIGHTS["desire"] + upd["score"] * WEIGHTS["market"]
                                      + s * WEIGHTS["style"] + p * WEIGHTS["practicality"]))
                except (ValueError, TypeError):
                    pass  # unverified/blank row — leave FINAL as-is
                touched.append(jf)
    if touched:
        with open(csv_path, "w", newline="", encoding="utf-8") as fh:
            csv.writer(fh).writerows(rows)
    return touched


def main(argv):
    ap = argparse.ArgumentParser(description="Persist Profile Fit provenance + optionally merge scores into a rankings CSV.")
    ap.add_argument("--results", required=True, help="JSON file: {results:[{key, abs_path, final_score, band, status, ledger, risk_flags, validation, profile_notes}]}")
    ap.add_argument("--provenance", required=True, help="path to the provenance JSON to write/update")
    ap.add_argument("--csv", default=None, help="rankings CSV to merge into (optional; the vet path already merged in JS)")
    ap.add_argument("--hashes", default=None, help="JSON file with the four input hashes (optional if --card/--profile/--prompt given)")
    ap.add_argument("--card", default=None); ap.add_argument("--profile", default=None); ap.add_argument("--prompt", default=None)
    ap.add_argument("--date", required=True)
    ap.add_argument("--model", default="unknown")
    a = ap.parse_args(argv[1:])
    results = json.load(open(a.results))["results"]
    # Common hashes: from --hashes file, or computed from the card/profile/prompt paths (the workflow
    # sandbox has no crypto, so hashing happens here, in the production transaction, before any write).
    if a.hashes:
        common = json.load(open(a.hashes))
    else:
        common = {}
        if a.card and os.path.exists(a.card): common["scoring_card_sha256"] = R.sha256_file(a.card)
        if a.profile and os.path.exists(a.profile): common["profile_sha256"] = R.sha256_file(a.profile)
        if a.prompt and os.path.exists(a.prompt): common["profile_fit_prompt_sha256"] = R.sha256_file(a.prompt)
    prov = {r["job_key"]: r for r in
            json.load(open(a.provenance)).get("records", [])} if os.path.exists(a.provenance) else {}
    updates = {}
    for res in results:
        k = res["key"]
        # posting hash is per-job, from the result's own abs_path
        h = dict(common)
        ap_path = res.get("abs_path")
        if ap_path and os.path.exists(ap_path):
            h["posting_sha256"] = R.sha256_file(ap_path)
        prev = prov.get(k)
        rec = make_record(k, res, h, a.date, a.model)
        if prev:  # preserve prior score+ledger history for auditability
            rec["previous"] = {"score": prev.get("score"), "band": prev.get("band"),
                               "status": prev.get("status"), "date_scored": prev.get("date_scored"),
                               "band_setter": (prev.get("ledger") or {}).get("band_setter")}
        prov[k] = rec
        updates[k] = {"score": res["final_score"], "notes": res.get("profile_notes")}
    # A complete, writable provenance file is REQUIRED before user-facing artifacts may change.
    write_provenance(a.provenance, prov)
    if not os.path.exists(a.provenance):
        raise SystemExit("PROVENANCE WRITE FAILED — refusing to proceed (fail-closed)")
    if a.csv:
        touched = merge_into_csv(a.csv, updates)
        print(f"provenance: {len(prov)} records; CSV rows touched: {len(touched)}")
    else:
        print(f"provenance OK: {len(prov)} records at {a.provenance}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
