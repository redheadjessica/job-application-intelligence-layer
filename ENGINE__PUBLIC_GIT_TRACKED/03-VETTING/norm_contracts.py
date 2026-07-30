#!/usr/bin/env python3
"""
norm_contracts.py — the single home for JAIL's OUTPUT-CONTRACT normalizers.

Why this module exists: output formats used to be enforced by LLM prompt instructions
alone, and prompts are insufficient (a real batch produced "NYC/SF - 3 days" with the
mandatory "IRL " prefix missing). Every contract here gets ONE canonical normalizer,
applied after model output and before anything is written, and tested at the final
artifact (the actual spreadsheet cell). Callers:

  - `.claude/workflows/vet-jobs.js` shells out to the CLI (`--normalize-rankings-csv`)
    right after writing the rankings CSV, before the XLSX build.
  - `make_rankings_xlsx.py` imports this module and re-normalizes on read, so
    regenerating an OLD CSV also repairs its text and colors.

Repair-or-fail-loudly: an unparseable value becomes `Unknown` / `??` WITH a printed
warning, never silently.

== Working Location: canonical grammar (authoritative spec, 2026-07-29) ==

Allowed values (and nothing else):
    Remote
    Remote (<detail>)                      e.g. Remote (states: NY, CA)
    Remote or IRL <cities> - <cadence>     remote genuinely optional + office option
    IRL <cities> - <cadence>
    Unknown

  - Every known non-remote location carries the literal "IRL " prefix. Never bare
    "Hybrid" / "Onsite" / "NYC/SF - 3 days" / "New York hybrid".
  - <cities> is "/"-joined, ordered by the candidate's configured `city_priority`
    (priority cities first, others after in original order). Multi-office lists are
    preserved, never collapsed to one city.
  - <cadence> is "N days" (exact), "N-M days" (a range the employer stated — kept
    verbatim, never collapsed to an endpoint), "N+ days" (open-ended minimum —
    "3 days" and "3+ days" are DIFFERENT; open-endedness is preserved), or
    "unknown days" (city known, day count not). An optional parenthetical detail may
    follow any of them, e.g. "3 days (Mon/Wed/Thu)" or "unknown days (hub-office
    salary range; remote elsewhere possible)".
  - A stated range is COLORED by its maximum ("2-3 days" is inside the acceptable
    1-3 band; "4-5 days" is not) while the text keeps both endpoints. Display and
    color are separate everywhere in this module.
  - "Onsite <city>" means 5 days ONLY when full-time attendance is established;
    otherwise "IRL <city> - unknown days".
  - "Unknown" ONLY when there is no reliable location signal at all. A known city
    with an unknown cadence stays "IRL <city> - unknown days".
  - Remote is never inferred from "flexible" / "distributed" / "remote-friendly".

== Working Location colors (EXACT hex, black text, no others — no grey) ==

    42FF35  vivid green   remote genuinely available (incl. "Remote or IRL ...")
    FDFF43  yellow        no remote; acceptable home-metro office at EXACTLY 1, 2,
                          or 3 days (incl. multi-city lists where a home-metro city
                          is selectable)
    FA9C31  orange        Unknown; known city + unknown cadence; home-metro >3 days;
                          open-ended minimums ("3+", "at least 3"); full-time
                          home-metro
    F82C1F  vivid red     required in-person outside the acceptable home geography
                          with no remote/home-metro option

Precedence: remote -> green; else acceptable-home-metro (1-3 exact -> yellow; >3 /
open-ended / unknown cadence -> orange); else out-of-geo in-person -> red; else
(nothing established) -> orange. Home-metro detection uses `home_metro_aliases`
(+ `home_metro`) from jail.config.json — NOT `city_priority` (SF appearing in
city_priority does NOT make SF a home metro; an SF-only in-person job is red).
Display and color are separate: the cell keeps "IRL NYC/SF - 3 days"; the color
evaluates the acceptable home-metro option (yellow).
"""
import argparse
import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path

# ---- Working Location colors — EXACT hexes from the spec (uppercase for openpyxl). ----
WL_GREEN = "42FF35"   # remote genuinely available
WL_YELLOW = "FDFF43"  # acceptable home-metro office, exactly 1-3 days
WL_ORANGE = "FA9C31"  # unknown / unknown cadence / >3 days / open-ended minimum
WL_RED = "F82C1F"     # required in-person outside acceptable home geography


def _warn(msg):
    print(f"[norm_contracts] WARNING: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Working Location
# --------------------------------------------------------------------------- #
# A cadence is "N days" (exact), "N-M days" (a range the employer stated — preserved
# verbatim, never collapsed to one endpoint), "N+ days" (open-ended minimum), or
# "unknown days"; each may carry a trailing parenthetical detail.
_CADENCE_RE = (r"(?:\d+(?:\s*[-–—]\s*\d+)?\+? days?(?: \([^)]*\))?"
               r"|unknown days(?: \([^)]*\))?)")
_CANON_WL_RE = re.compile(
    rf"^(?:Remote|Remote \([^()]*(?:\([^()]*\))?[^()]*\)|(?:Remote or )?IRL .+ - {_CADENCE_RE})$"
)

# Values that mean "no reliable signal" (case-insensitive, punctuation-stripped).
_NO_SIGNAL = {
    "", "unknown", "unclear", "n/a", "na", "none", "not posted", "not specified",
    "not stated", "tbd", "could not verify", "?", "??",
}

# Common metro short forms (display canon). Only unambiguous majors; anything else
# keeps the posting's own city name.
_CITY_SHORT = {
    "nyc": "NYC", "new york": "NYC", "new york city": "NYC", "manhattan": "NYC",
    "brooklyn": "NYC", "nyc metro": "NYC",
    "sf": "SF", "san francisco": "SF", "san francisco bay area": "SF",
    "sf bay area": "SF", "bay area": "SF",
    "la": "LA", "los angeles": "LA",
    "dc": "DC", "d.c.": "DC", "washington dc": "DC", "washington d.c.": "DC",
    "washington, d.c.": "DC",
}

# Tokens that are location KEYWORDS, not cities.
_WL_STOPWORDS = {
    "remote", "hybrid", "onsite", "on-site", "on site", "in-office", "in office",
    "office", "irl", "required", "full-time", "full time", "days", "day", "week",
    "location", "working location", "workplace", "hq", "headquarters", "or", "and",
    "the", "in", "at", "attend", "must", "per",
    # Degree/scope adverbs and non-places. Without these, "Fully remote" minted a city
    # named "Fully" ("IRL Fully - unknown days") — a capitalized word is not a place.
    "fully", "mostly", "primarily", "largely", "partially", "partly", "entirely",
    "completely", "anywhere", "nationwide", "worldwide", "global", "globally",
    "optional", "preferred", "based", "home", "wfh", "offices", "onsite/hybrid",
    # Country/region scopes are not cities ("IRL US offices" is not an office in a city
    # called "US"). A genuine country restriction survives as `Remote (US)` detail instead.
    "us", "usa", "u.s.", "u.s.a.", "united states", "america", "north america",
}

_OPEN_ENDED_RES = [
    re.compile(r"\b(\d+)\s*\+\s*day(?:s)?\b", re.I),
    re.compile(r"\bat least\s+(\d+)\s+day(?:s)?\b", re.I),
    re.compile(r"\bminimum(?:\s+of)?\s+(\d+)\s+day(?:s)?\b", re.I),
    re.compile(r"\bmin\.?\s+(\d+)\s+day(?:s)?\b", re.I),
    re.compile(r"\b(\d+)\s+or more day(?:s)?\b", re.I),
]
_EXACT_DAYS_RE = re.compile(r"\b(\d+)\s*day(?:s)?\b(\s*\(([^)]*)\))?", re.I)
# An employer-stated RANGE ("2-3 days in office"). Must be tried before the exact-day
# pattern, which would otherwise match only the range's upper endpoint and silently
# rewrite "2-3 days" as "3 days" — information loss on a field the candidate reads
# (the same fidelity rule that keeps "3 days" distinct from "3+ days").
_RANGE_DAYS_RE = re.compile(r"\b(\d+)\s*[-–—]\s*(\d+)\s*day(?:s)?\b(\s*\(([^)]*)\))?", re.I)


def _cadence_str(n, open_ended, detail=None, hi=None):
    if hi is not None:
        base = f"{n}-{hi} days"
    elif open_ended:
        base = f"{n}+ days"
    else:
        base = f"{n} day" if n == 1 else f"{n} days"
    return f"{base} ({detail})" if detail else base


def _extract_cadence(raw):
    """Return (cadence_string_or_None, matched_day_phrases_found)."""
    m = _RANGE_DAYS_RE.search(raw)
    if m:
        detail = (m.group(4) or "").strip() or None
        return _cadence_str(int(m.group(1)), False, detail, hi=int(m.group(2))), True
    for rx in _OPEN_ENDED_RES:
        m = rx.search(raw)
        if m:
            return _cadence_str(int(m.group(1)), True), True
    m = _EXACT_DAYS_RE.search(raw)
    if m:
        detail = (m.group(3) or "").strip() or None
        # a parenthetical that is just schedule detail (weekday list etc.) is kept
        return _cadence_str(int(m.group(1)), False, detail), True
    return None, False


def _plausible_city(token, known):
    """Accept a token as a city only when it's a known name (built-in short forms,
    the candidate's aliases/city_priority) or LOOKS like a proper city name: 1-3
    words, each capitalized, letters only. Keeps prose like "see posting for
    details" from being minted into a fake city (repair-or-fail-loudly)."""
    if token.lower() in known:
        return True
    words = token.split(" ")
    if not 1 <= len(words) <= 3:
        return False
    return all(re.fullmatch(r"[A-Z][A-Za-z.'-]*", w) for w in words)


def _extract_cities(raw, cfg):
    """Pull city names out of a messy location string, mapped to display short
    forms, deduped, ordered by the candidate's city_priority."""
    loc_cfg = (cfg or {}).get("location") or {}
    known = set(_CITY_SHORT)
    for a in (loc_cfg.get("home_metro_aliases") or []) + (loc_cfg.get("city_priority") or []) \
            + [loc_cfg.get("home_metro") or ""]:
        if str(a).strip():
            known.add(str(a).strip().lower())
    work = raw
    # Drop parentheticals (detail, not city lists) and state suffixes (", NY").
    work = re.sub(r"\([^)]*\)", " ", work)
    work = re.sub(r",\s*[A-Z]{2}\b", " ", work)
    # Remote-ish adjectives never name a city ("remote-friendly", "distributed").
    work = re.sub(r"\bremote([- ]friendly)?\b|\bflexible\b|\bdistributed\b", " ", work, flags=re.I)
    # Drop cadence phrasing so day counts don't read as city tokens.
    for rx in _OPEN_ENDED_RES:
        work = rx.sub(" ", work)
    work = _RANGE_DAYS_RE.sub(" ", work)
    work = re.sub(r"\b\d+\s*\+?\s*day(?:s)?\b", " ", work, flags=re.I)
    # "unknown days" is cadence too — leaving it in used to swallow the city it followed
    # ("NYC/SF - unknown days" kept only NYC, because "SF - unknown days" no longer
    # looked like a city name).
    work = re.sub(r"\bunknown\s+days?\b", " ", work, flags=re.I)
    work = re.sub(r"\b(per|a|each)\s+week\b|\bweekly\b", " ", work, flags=re.I)
    tokens = re.split(r"[/;,•·|]+|\bor\b|\band\b|&", work, flags=re.I)
    cities, seen = [], set()
    for tok in tokens:
        t = tok.strip(" \t–—-—–:.")
        t = re.sub(r"\s+", " ", t)
        if not t or t.lower() in _WL_STOPWORDS:
            continue
        # strip keyword + pure-punctuation words ("Hybrid NYC", "— New York", "NYC office")
        words = [w for w in t.split(" ")
                 if w.lower() not in _WL_STOPWORDS and re.search(r"[A-Za-z]", w)]
        if not words:
            continue
        t = " ".join(words)
        if not _plausible_city(t, known):
            continue
        city = _CITY_SHORT.get(t.lower(), t)
        if city.lower() not in seen:
            seen.add(city.lower())
            cities.append(city)
    priority = [str(p) for p in ((cfg or {}).get("location") or {}).get("city_priority") or []]
    prio_lower = [p.lower() for p in priority]
    ordered = [c for p in prio_lower for c in cities if c.lower() == p]
    ordered += [c for c in cities if c.lower() not in prio_lower]
    return ordered


def normalize_working_location(text, cfg=None, warn=_warn):
    """Normalize any location string into the canonical Working Location grammar.
    Already-canonical values pass through unchanged; no-signal values become
    "Unknown"; anything unparseable becomes "Unknown" WITH a printed warning."""
    raw = re.sub(r"\s+", " ", str(text or "").strip())
    if raw.lower().strip(" .") in _NO_SIGNAL:
        return "Unknown"
    if _CANON_WL_RE.match(raw):
        return raw
    low = raw.lower()
    # Remote must be genuine — never inferred from remote-friendly/flexible/distributed.
    remote = bool(re.search(r"\bremote\b(?![\s-]*friendly)", low))
    cadence, had_days = _extract_cadence(raw)
    cities = _extract_cities(raw, cfg)
    # A trailing parenthetical carries employer detail worth keeping (e.g. "(hub-office
    # salary range; remote elsewhere in US possible at 80-100% of range)"). Preserve it
    # unless the cadence already absorbed a parenthetical of its own.
    # A parenthetical that merely RESTATES the cadence ("(at least 2 days per week)") is
    # already represented by the cadence itself and is not repeated.
    tail = re.search(r"\(([^()]*)\)\s*$", raw)
    tail_detail = None
    if tail and not (cadence and "(" in cadence):
        cand = tail.group(1).strip()
        if cand and not re.search(r"\bdays?\b", cand, re.I):
            tail_detail = cand
    if cities:
        if cadence is None:
            # "Onsite <city>" is 5 days ONLY when full-time attendance is established.
            if re.search(r"\bfull[- ]?time\b", low) and re.search(r"\b(on-?site|in[- ]office|office|irl)\b", low):
                cadence = "5 days"
            else:
                cadence = "unknown days"
        if tail_detail:
            cadence = f"{cadence} ({tail_detail})"
        irl = f"IRL {'/'.join(cities)} - {cadence}"
        return f"Remote or {irl}" if remote else irl
    if remote:
        # `Remote (<detail>)` is part of the canonical grammar, so employer detail is kept
        # rather than flattened away: a real value read
        # "Remote, US (in-office 1-2x/quarter; SF office option, not required)" and came out
        # as bare "Remote", discarding both the country restriction and the cadence note.
        bits = []
        # The separator must be a comma, a paren, or a SPACED dash — "Remote-first" is a
        # compound adjective, not "Remote (first)".
        sep = r"(?:,|\(|\s+[–—-]\s+)"
        qual = re.match(rf"remote\s*{sep}\s*([A-Za-z][A-Za-z .]{{0,30}}?)\s*(?:[,)(;.]|$)", low)
        # A country/region scope is exactly the kind of detail worth keeping here (it is a
        # scope, not a city), so this check uses its own narrow skip set, not _WL_STOPWORDS.
        _QUAL_SKIP = {"first", "friendly", "or", "and", "in", "at", "the", "day", "days",
                      "office", "offices", "hybrid", "onsite", "remote", "based"}
        if qual and qual.group(1).strip().lower() not in _QUAL_SKIP:
            bits.append(re.match(rf"[Rr]emote\s*{sep}\s*(.{{0,32}}?)\s*(?:[,)(;.]|$)",
                                 raw).group(1).strip())
        if tail_detail:
            bits.append(tail_detail)
        detail = "; ".join(b for b in dict.fromkeys(bits) if b)
        return f"Remote ({detail})" if detail else "Remote"
    if had_days:
        warn(f"working location had a day count but no recognizable city — set to Unknown: {raw!r}")
        return "Unknown"
    warn(f"working location unparseable — set to Unknown: {raw!r}")
    return "Unknown"


def working_location_facts(canonical, cfg=None):
    """Decompose a CANONICAL Working Location string into the facts the color
    mapper needs. Home-metro detection uses `home_metro_aliases` (+ `home_metro`)
    ONLY — city_priority does NOT make a city a home metro."""
    s = (canonical or "").strip()
    loc_cfg = (cfg or {}).get("location") or {}
    aliases = {str(a).strip().lower() for a in (loc_cfg.get("home_metro_aliases") or []) if str(a).strip()}
    home = str(loc_cfg.get("home_metro") or "").strip().lower()
    if home:
        aliases.add(home)
    facts = {
        "remote_available": s.lower().startswith("remote"),
        "nyc_option": False,       # an acceptable home-metro office is selectable
        "days_exact": None,        # int when cadence is an exact "N days"; a stated
                                   # range "N-M days" reports its MAXIMUM here
        "days_range": None,        # (N, M) when the employer stated a range
        "days_open_ended": False,  # "N+ days"
        "days_unknown": False,     # "unknown days"
        "out_of_geo": False,       # in-person cities exist, none in the home metro
        "cities": [],
        "home_configured": bool(aliases),
    }
    m = re.search(rf"\bIRL (.+) - ({_CADENCE_RE})$", s)
    if m:
        cities = [c.strip() for c in m.group(1).split("/") if c.strip()]
        facts["cities"] = cities
        cad = m.group(2)
        dm = re.match(r"(\d+)(?:\s*[-–—]\s*(\d+))?(\+)?\s*day", cad)
        if dm:
            if dm.group(3):
                facts["days_open_ended"] = True
            else:
                # An employer-stated range is judged by its MAXIMUM: "2-3 days" is
                # within the acceptable 1-3 band, "4-5 days" is not.
                facts["days_exact"] = int(dm.group(2) or dm.group(1))
                facts["days_range"] = (int(dm.group(1)), int(dm.group(2))) if dm.group(2) else None
        else:
            facts["days_unknown"] = True
        facts["nyc_option"] = any(c.lower() in aliases for c in cities)
        facts["out_of_geo"] = bool(cities) and not facts["nyc_option"]
    return facts


def working_location_color(canonical, cfg=None):
    """Map a canonical Working Location string to EXACTLY one of the 4 spec hexes
    (black text; grey is not allowed). Precedence: remote -> green; else
    acceptable-home-metro (1-3 exact -> yellow; >3 / open-ended / unknown cadence
    -> orange); else out-of-geo in-person -> red; else -> orange."""
    f = working_location_facts(canonical, cfg)
    if f["remote_available"]:
        return WL_GREEN
    if f["nyc_option"]:
        if f["days_exact"] is not None and 1 <= f["days_exact"] <= 3:
            return WL_YELLOW
        return WL_ORANGE  # >3 days, open-ended minimum, or unknown cadence
    if f["out_of_geo"] and f["home_configured"]:
        return WL_RED
    # Unknown / no in-person signal / no home metro configured (can't judge geography)
    return WL_ORANGE


# --------------------------------------------------------------------------- #
# Comp Range — outer envelope of APPLICABLE bands, displayed as whole thousands
# ("125-250"), or "??" when unknown. The band-applicability judgment lives in the
# vet-jobs.js scoring prompt (the LLM has the posting + preferences); the FORMAT
# is enforced mechanically here.
# --------------------------------------------------------------------------- #
def normalize_comp_range(text, warn=_warn):
    """Enforce `^\\d+-\\d+$` or `??`. Repairs $, K, commas, full-dollar values
    (232,000-282,000 -> 232-282), en/em dashes, "to" ranges, and a single value
    N -> N-N. Anything unparseable becomes `??` WITH a printed warning."""
    t = re.sub(r"\s+", " ", str(text or "").strip())
    if not t or "?" in t or t.lower() in {"unknown", "n/a", "na", "none", "not posted", "tbd"}:
        return "??"
    if re.fullmatch(r"\d+-\d+", t):
        return t
    s = t.replace(",", "").replace("$", "")
    s = s.replace("–", "-").replace("—", "-")  # en/em dash
    s = re.sub(r"\bto\b", "-", s, flags=re.I)
    nums = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*([kK])?", s):
        if not m.group(1):
            continue
        v = float(m.group(1))
        if not m.group(2) and v >= 10000:  # full-dollar figure -> whole thousands
            v = v / 1000.0
        nums.append(int(round(v)))
    if len(nums) == 1:
        lo = hi = nums[0]
    elif len(nums) == 2:
        lo, hi = nums
        if lo > hi:
            warn(f"comp range endpoints were reversed — swapped: {t!r}")
            lo, hi = hi, lo
    else:
        warn(f"comp range unparseable ({len(nums)} numbers found) — set to ??: {t!r}")
        return "??"
    if not (10 <= lo <= 2000 and 10 <= hi <= 2000):  # sanity: whole-thousands base salary
        warn(f"comp range out of plausible whole-thousands bounds — set to ??: {t!r}")
        return "??"
    return f"{lo}-{hi}"


def comp_fit_label(comp_range, cfg):
    """Candidate-relative Comp Fit label — the APPROVED midpoint rule (2026-07-29),
    replacing the old high-endpoint-only rule that painted a below-floor-midpoint
    band green. `Unknown` for ??/empty; `No comp prefs` when the config has neither
    floor nor target; else: RED `Below floor` iff max < floor; GREEN
    `Meets/above target` iff midpoint >= target; else YELLOW `Near target`.
    (`Above floor` when only a floor is configured and it's met.)"""
    t = (comp_range or "").strip()
    m = re.fullmatch(r"(\d+)-(\d+)", t)
    if not m:
        return "Unknown"
    comp = (cfg or {}).get("comp") or {}
    floor, target = comp.get("floor_base"), comp.get("target_base")
    if floor is None and target is None:
        return "No comp prefs"
    lo, hi = int(m.group(1)), int(m.group(2))
    if floor is not None and hi < floor:
        return "Below floor"
    if target is not None:
        return "Meets/above target" if (lo + hi) / 2 >= target else "Near target"
    return "Above floor"


# --------------------------------------------------------------------------- #
# Lane — the job-centric category taxonomy: "<Bucket> - <descriptor>" with
# buckets Health / Consumer / Work / Other. ("Work", NEVER "Work Tools" — the
# bucket was renamed 2026-07-29.) Lane Fit is candidate data and is untouched:
# the candidate's own lane NAMES (which may legitimately contain "Work Tools")
# never flow through this function.
# --------------------------------------------------------------------------- #
_LANE_RE = re.compile(r"^(health|consumer|work tools|work|other)\s*[-–—]\s*(.+)$", re.I)


def normalize_lane(lane):
    """Repair a Lane value into the canonical taxonomy: `Work Tools - X` ->
    `Work - X`; bare `Work Tools` -> `Work`; enforce `<Bucket> - <descriptor>`
    spacing; force the exact `Health - Mental Health` spelling (no extra
    qualifier words). Mirrored by normalizeLane() in vet-jobs.js — this Python
    copy is the canonical implementation (CLI pass + XLSX regeneration)."""
    s = re.sub(r"\s+", " ", str(lane or "").strip())
    m = _LANE_RE.match(s)
    if m:
        bucket = "Work" if m.group(1).lower() == "work tools" else m.group(1).capitalize()
        desc = m.group(2).strip()
        if bucket == "Health" and re.search(r"mental health", desc, re.I):
            return "Health - Mental Health"
        return f"{bucket} - {desc}"
    if re.fullmatch(r"work tools", s, re.I):
        return "Work"
    return s


# --------------------------------------------------------------------------- #
# Tailored-application names — "Company - Canonical Role" (authoritative spec,
# 2026-07-29). ONE canonicalizer for the job folder, the copied job file, the
# resume filename, cover-letter names, and manifests — replacing four mutually
# inconsistent prompt-instruction sites (job-applier.md, 00-job_application_agent.md,
# tailor-jobs.js, cover-letter.js). Agents obtain the exact string by running:
#
#   .venv/bin/python3 ENGINE__PUBLIC_GIT_TRACKED/03-VETTING/norm_contracts.py \
#       --application-name --company "<Company>" --role "<Role>"
#
# The transformation is DELIBERATELY NARROW — no other rewriting:
#   - "Product Manager" -> "PM" (also inside compounds: "Senior Product Manager"
#     -> "Senior PM"; "Chief Product Officer" is NOT "Product Manager" and stays).
#   - "Sr"/"Sr." -> "Senior". NEVER Senior -> Sr (her explicit answer).
#   - "Vice President" -> "VP"; "Director" stays "Director" (her explicit answer).
#   - "Staff"/"Principal"/"Chief" and meaningful qualifiers are preserved verbatim.
#   - Comma+space separates the core PM title from a trailing specialization:
#     inserted when missing ("Staff PM Referral Growth" -> "Staff PM, Referral
#     Growth"); an existing comma is NEVER removed.
#   - An employer " - " separator INSIDE a title becomes the comma separator
#     ("Staff Product Manager - Referral, Growth" -> "Staff PM, Referral Growth").
#   - "/" and ":" are stripped (filesystem rule — these can't appear in names).
# --------------------------------------------------------------------------- #
_SENIORITY = r"(?:Senior|Staff|Principal|Lead|Group|Associate|Junior|Founding)"
_ROLE_CORE_RE = re.compile(rf"^((?:{_SENIORITY} )*PM)\s+(.+)$", re.I)


def canonical_application_role(role):
    """Canonicalize a job title for tailored-application naming. Idempotent:
    an already-canonical role passes through unchanged."""
    s = re.sub(r"\s+", " ", str(role or "").strip())
    # Filesystem rule: no slash or colon in folder/file names.
    s = re.sub(r"\s*[/:]\s*", " ", s).strip()
    # An employer " - " separator inside the title becomes the comma separator;
    # any further dashes/commas in the trailing part demote to spaces (the
    # canonical grammar has ONE comma: "<core title>, <specialization>").
    parts = re.split(r"\s+[-–—]\s+", s, maxsplit=1)
    if len(parts) == 2:
        head, tail = parts
        tail = re.sub(r"\s+[-–—]\s+|,", " ", tail)
        tail = re.sub(r"\s+", " ", tail).strip()
        s = f"{head}, {tail}" if tail else head
    # Narrow word substitutions (and nothing else).
    s = re.sub(r"\bSr\.?(?=[\s,]|$)", "Senior", s, flags=re.I)
    s = re.sub(r"\bProduct Manager\b", "PM", s, flags=re.I)
    s = re.sub(r"\bVice President\b", "VP", s, flags=re.I)
    s = re.sub(r"\s+", " ", s).strip(" ,")
    # Insert the missing comma between a core PM title and its trailing
    # specialization. Never remove an existing comma.
    if "," not in s:
        m = _ROLE_CORE_RE.match(s)
        if m:
            s = f"{m.group(1)}, {m.group(2)}"
    return s


def canonical_application_name(company, role):
    """The exact `Company - Canonical Role` string used verbatim for the job
    folder, the resume-base filename, and cover-letter names. The company is
    passed through with only whitespace collapse + the filesystem strip — no
    other rewriting."""
    c = re.sub(r"\s+", " ", str(company or "").strip())
    c = re.sub(r"\s*[/:]\s*", " ", c)
    c = re.sub(r"\s+", " ", c).strip(" ,")
    return f"{c} - {canonical_application_role(role)}"


# --------------------------------------------------------------------------- #
# Application ARTIFACT FILENAMES — the candidate-name half of the contract
#
# `canonical_application_name()` above owns the `Company - Role` half, and every agent
# already calls it. The candidate-name PREFIX had no such owner, so two agents in one run
# produced two spellings of the same artifact type:
#     "<First> <Last>-Resume - Acme - Senior PM, Care Delivery.pages"
#     "<First>-<Last>-Resume - Willow Health - Senior PM, Member Growth.pages"
# The name is now DERIVED, not improvised: one builder, one spelling, sourced from
# `candidate.name` in jail.config.json rather than from whatever the agent inferred.
#
# Chosen shape (matches the long-documented spec template and the demo fixtures):
#     <Candidate Name>-Resume - <Company - Role>.<ext>
#     <Candidate Name>-Cover-Letter - <Company - Role>.<ext>
# The candidate's own name keeps its own spacing and punctuation — a hyphenated surname
# stays hyphenated, a two-word name keeps its space. Only the ARTIFACT word is joined
# with a hyphen.
# --------------------------------------------------------------------------- #
RESUME_ARTIFACT = "Resume"
COVER_LETTER_ARTIFACT = "Cover-Letter"
_ARTIFACT_ALIASES = {
    "resume": RESUME_ARTIFACT, "cv": RESUME_ARTIFACT,
    "coverletter": COVER_LETTER_ARTIFACT, "cover letter": COVER_LETTER_ARTIFACT,
    "cover-letter": COVER_LETTER_ARTIFACT, "coverletters": COVER_LETTER_ARTIFACT,
}


def canonical_candidate_name(name):
    """The candidate's name as it appears in an artifact filename: whitespace collapsed
    and path-hostile characters removed, but spacing and hyphenation left exactly as the
    person writes their own name."""
    s = re.sub(r"\s+", " ", str(name or "").strip())
    s = re.sub(r"[/\\:]+", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ,-")


def canonical_application_filename(candidate_name, company, role, ext="",
                                   artifact=RESUME_ARTIFACT):
    """`<Candidate Name>-<Artifact> - <Company - Role><.ext>` — the ONE spelling.
    The extension is preserved verbatim (a `.pages` base stays `.pages`); pass it with
    or without the leading dot."""
    who = canonical_candidate_name(candidate_name)
    stem = f"{who}-{artifact}" if who else artifact
    suffix = str(ext or "").strip()
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    return f"{stem} - {canonical_application_name(company, role)}{suffix}"


def canonical_resume_filename(candidate_name, company, role, ext=""):
    return canonical_application_filename(candidate_name, company, role, ext,
                                          artifact=RESUME_ARTIFACT)


def canonical_cover_letter_filename(candidate_name, company, role, ext=""):
    return canonical_application_filename(candidate_name, company, role, ext,
                                          artifact=COVER_LETTER_ARTIFACT)


# `<anything>-Resume - <rest>` / `<anything> Cover Letter - <rest>`: the candidate half is
# whatever precedes the artifact word, however the agent spelled it.
_ARTIFACT_SPLIT_RE = re.compile(
    r"^(?P<who>.*?)[\s\-_]*(?P<artifact>cover[\s\-_]*letter|resume|cv)\s+-\s+(?P<rest>.+)$",
    re.I)


def normalize_application_filename(filename, candidate_name=None):
    """Repair an existing artifact filename to the canonical spelling, keeping its
    `Company - Role` half and its extension verbatim. Returns the input unchanged when it
    doesn't look like an application artifact — this only ever re-spells the candidate and
    artifact halves, never the job identity."""
    name = str(filename or "").strip()
    stem, dot, ext = name.rpartition(".")
    if not dot or len(ext) > 5 or " " in ext:
        stem, ext = name, ""
    m = _ARTIFACT_SPLIT_RE.match(stem)
    if not m:
        return name
    artifact = _ARTIFACT_ALIASES.get(
        re.sub(r"[\s\-_]+", "-", m.group("artifact").strip().lower()),
        _ARTIFACT_ALIASES.get(re.sub(r"[\s\-_]+", "", m.group("artifact").strip().lower()),
                              RESUME_ARTIFACT))
    who = candidate_name if candidate_name is not None else m.group("who").replace("-", " ")
    who = canonical_candidate_name(who)
    stem_out = f"{who}-{artifact}" if who else artifact
    return f"{stem_out} - {m.group('rest').strip()}" + (f".{ext}" if ext else "")


def candidate_name_from_config(cfg):
    """The candidate's name from jail.config.json (`candidate.name`), or "" when unset —
    the single source, so no agent has to guess how the person spells it."""
    candidate = (cfg or {}).get("candidate")
    if isinstance(candidate, dict):
        return canonical_candidate_name(candidate.get("name"))
    return canonical_candidate_name(candidate if isinstance(candidate, str) else "")


# --------------------------------------------------------------------------- #
# Status — the tracker's lifecycle vocabulary.
# --------------------------------------------------------------------------- #
# The 12 dropdown values, verbatim. This is the ONE definition; make_rankings_xlsx imports it for
# the data-validation list and its color maps, and vet-jobs' generated values are a subset. A cell
# holding anything outside this list silently loses its dropdown match, its lifecycle color, and
# its filter grouping — which is how three rows ended up reading "Apply if Time" (lowercase "if")
# and rendering unfilled.
STATUS_VALUES = [
    "**Currently In Talks**",
    "Applied: Awaiting Response",
    "Apply Again??",
    "Apply ASAP: High Prio",
    "Apply Eventually: Apply If Time",
    "Apply Eventually: Backup Lane",
    "Apply Eventually: On Ice (Applied to Another Position at this Company)",
    "Apply Eventually: Or Skip It",
    "Declined (Applied, Rejected)",
    "Down (Applied, No Response)",
    "Down: Closed Before Applying",
    "Interviewed: Rejected",
]


def _status_column(headers):
    """The Status header, matched by prefix — it carries a user-facing suffix
    ("Status? [You Change]") that has drifted before and may again."""
    for h in headers:
        if str(h or "").strip().lower().startswith("status"):
            return h
    return None


def _status_key(text):
    """Collapse a status to a comparison key: case-, whitespace- and punctuation-insensitive."""
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


_STATUS_BY_KEY = {_status_key(v): v for v in STATUS_VALUES}


def normalize_status(text, warn=_warn):
    """Repair a Status cell to its exact canonical spelling.

    Case, spacing and punctuation drift all repair silently — they carry no meaning and a
    near-miss is never intentional. A value that matches nothing is left EXACTLY as written and
    warned about instead: the column is the candidate's own, and mangling a status they typed
    deliberately would be worse than flagging it. Blank stays blank (an unscored/user row)."""
    raw = str(text or "").strip()
    if not raw or raw in _STATUS_BY_KEY.values():
        return raw
    hit = _STATUS_BY_KEY.get(_status_key(raw))
    if hit:
        return hit
    warn(
        f'Status "{raw}" is not one of the {len(STATUS_VALUES)} tracker values — left as written, '
        "but it will have no dropdown match, no lifecycle color and no filter grouping."
    )
    return raw


# --------------------------------------------------------------------------- #
# CLI — normalize a rankings CSV in place (invoked by vet-jobs.js post-scoring,
# before the XLSX build). Prints every repair it makes.
# --------------------------------------------------------------------------- #
H_WORKLOC = "Working Location"
H_LANE = "Lane"
H_COMPRANGE = "Comp Range"
H_COMPFIT = "Comp Fit"
H_COMPANY = "Company"
H_POSTED = "Job Posted Date"
H_JOBFILE = "Job File"
H_DATACOMPLETE = "Data Completeness"
H_TITLE = "Job Post Title + Link"
H_LANEFIT = "Lane Fit"
H_LOCFIT_LEGACY = "Location Fit"   # removed from the contract; dropped on migration
UNKNOWN_POSTED_DATE = "Unknown"    # never blank, never the capture date, never inferred
# The practicality dimension's prose companion column. Static name (like "Mission Fit Notes") even
# though the score label itself is candidate-relabelable, so both Python passes can find it.
H_PRACTNOTES = "Comp + Lifestyle Fit Notes"
H_PRACTSCORE_DEFAULT = "Comp + Lifestyle Fit Score"  # default label of the score it annotates
H_MISSIONNOTES = "Your Desire Score Notes"           # the column it must sit before


# --------------------------------------------------------------------------- #
# THE 27-COLUMN CONTRACT (order authoritative, approved 2026-07-30)
#
# One definition, shared by the CSV migration pass and the XLSX build. `vet-jobs.js` writes this
# same order; ANY older CSV is migrated to it in place (rename -> drop -> insert -> reorder),
# joined by header NAME so no column's data can shift. The five SCORE labels are dynamic (a
# candidate's scoring card may relabel a dimension), so they are slots resolved per file against
# the defaults + their legacy spellings; everything else is a literal.
#
# `Location Fit` was REMOVED as redundant with `Working Location` (the canonical grammar already
# encodes remote/metro/cadence, both cells shared one 4-hex fill, and a second derived label was
# one more thing to keep in sync). It is dropped from any legacy file.
# --------------------------------------------------------------------------- #
_SCORE_SLOT = "\x00score:"          # internal marker inside the template below
SCORE_SLOTS = ("final", "market", "desire", "style", "practicality")
SCORE_DEFAULT_LABELS = {
    "final": "FINAL Weighted Score",
    "market": "How They May See Your Profile",
    "desire": "Your Desire Score",
    "style": "Culture Fit Score",
    "practicality": "Comp + Lifestyle Fit Score",
}
# Older spellings of the same score column, checked when resolving a slot in an existing file.
SCORE_LEGACY_LABELS = {
    "style": ("Culture Fit",),
    "practicality": ("Comp + Lifestyle Fit",),
}
CONTRACT_TEMPLATE = [
    "Applied Date? [You Fill In]", "Status? [You Change]", H_LANE, H_COMPANY, H_TITLE,
    H_WORKLOC, H_COMPRANGE,
    "Have Intro? [You Add]", "Your Notes? [You Add]", "Decline/Down Date? [You Add]",
    f"{_SCORE_SLOT}final", f"{_SCORE_SLOT}market", f"{_SCORE_SLOT}desire",
    f"{_SCORE_SLOT}style", f"{_SCORE_SLOT}practicality",
    H_POSTED,
    "Top Reasons Notes", "Top Concerns Notes", "Profile Score Notes", H_MISSIONNOTES,
    H_PRACTNOTES,
    H_LANEFIT, H_COMPFIT, H_DATACOMPLETE, H_JOBFILE,
    "Tailored? (Base Resume)", "Cover Letter Drafted?",
]
# Legacy header -> final header. EXACT matches only, so "Comp + Lifestyle Fit Notes" is never
# caught by the "Comp + Lifestyle Fit" score rename.
LEGACY_RENAMES = {
    "Culture Fit": "Culture Fit Score",
    "Comp + Lifestyle Fit": "Comp + Lifestyle Fit Score",
    "Scope Fit Notes": "Profile Score Notes",
    "Mission Fit Notes": "Your Desire Score Notes",
    "Base Resume Used": "Tailored? (Base Resume)",
    "Cover Letter?": "Cover Letter Drafted?",
    "Posted": "Job Posted Date",
    "Top Concerns": "Top Concerns Notes",
    # An even older draft used a hyphen here; the SLASH form is correct.
    "Decline-Down Date? [You Add]": "Decline/Down Date? [You Add]",
}
DROPPED_COLUMNS = (H_LOCFIT_LEGACY,)


def resolve_contract_headers(existing_headers=None, score_labels=None):
    """The exact 27 final headers for a given file: literals from the template, with each score
    slot resolved to the label that file already uses (default or legacy spelling), else the
    engine default. `score_labels` (from score-dimensions.json) overrides the defaults."""
    existing = list(existing_headers or [])
    labels = dict(SCORE_DEFAULT_LABELS)
    for k, v in (score_labels or {}).items():
        if k in labels and str(v or "").strip():
            labels[k] = str(v).strip()
    out = []
    for entry in CONTRACT_TEMPLATE:
        if not entry.startswith(_SCORE_SLOT):
            out.append(entry)
            continue
        slot = entry[len(_SCORE_SLOT):]
        chosen = labels[slot]
        if chosen not in existing:
            # Keep whatever spelling the file already carries (incl. a candidate relabel), so a
            # reorder never silently renames a score column the user has been looking at.
            for cand in (SCORE_DEFAULT_LABELS[slot],) + SCORE_LEGACY_LABELS.get(slot, ()):
                if cand in existing:
                    chosen = cand if cand not in LEGACY_RENAMES else LEGACY_RENAMES[cand]
                    break
        out.append(chosen)
    return out


# --------------------------------------------------------------------------- #
# Data Completeness back-fill — ONE implementation (was duplicated in
# make_rankings_xlsx.py, which now imports this).
# --------------------------------------------------------------------------- #
def fallback_completeness(comp_range, working_location) -> str:
    """Derive the completeness label from a row's own comp/location text (no manifest
    field_status). Mirrors vet-jobs.js fallbackCompleteness: a missing field can't be told apart
    from 'not posted' here, so it is treated as could-not-verify."""
    comp = (comp_range or "").strip()
    loc = (working_location or "").strip()
    comp_missing = (not comp) or ("?" in comp)
    loc_missing = (not loc) or (loc.lower() == "unknown")
    if not comp_missing and not loc_missing:
        return "✓ complete"
    if comp_missing and loc_missing:
        return "⚠ comp+location not verified"
    if comp_missing:
        return "⚠ comp not verified"
    return "⚠ location unknown"


# --------------------------------------------------------------------------- #
# Posted — the employer's own publication date, read back out of the capture
#
# Current captures carry a `Job Posted At:` line in the JOB SNAPSHOT section (a human
# date like `June 13, 2026`, or `Unknown` when the source exposed none); legacy captures
# carry `Posted: YYYY-MM-DD`. BOTH are accepted so old batches regenerate their Posted
# column without re-fetching. This column surfaces the date in the rankings so a
# nine-month-old posting is visible at a glance. Deliberately a STATIC ISO date, not an
# age/"days open" computation: a saved spreadsheet with a computed age silently goes
# stale and starts lying; a date never does.
#
# The search is BOUNDED to the region before `--- JOB TEXT START ---`: LinkedIn (and
# other) fetchers write `Posted:`/`Location:`-style lines INSIDE the body, and a body
# line must never win over the capture's own snapshot line. Only when the marker is
# absent (hand-made legacy captures) does the search fall back to the whole file.
#
# Back-filled by reading each row's `Job File` capture — the same mechanism as the other
# contract columns, so regenerating an OLD rankings CSV populates it too.
# --------------------------------------------------------------------------- #
_POSTED_LINE_RE = re.compile(r"^Posted:\s*(\d{4}-\d{2}-\d{2})", re.M)          # legacy
_JOB_POSTED_AT_RE = re.compile(r"^Job Posted At:\s*(.+?)\s*$", re.M)           # current
_JOB_UPDATED_AT_RE = re.compile(r"^Job Updated At:\s*(.+?)\s*$", re.M)
_BODY_START_MARKER = "--- JOB TEXT START ---"
_CAPTURE_SUBDIR = ("3 - Source Material", "All Job Posts (full text)")


def _parse_capture_date(raw):
    """A capture-date value -> ISO `YYYY-MM-DD`. Accepts the human form
    (`June 13, 2026`) and ISO (with or without a time part); `Unknown`/blank/
    unparseable -> "" (never a guess)."""
    s = str(raw or "").strip()
    if not s or s.lower() == "unknown":
        return ""
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", s)
    if m:
        return m.group(1)
    try:
        return datetime.strptime(s, "%B %d, %Y").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _capture_head(text):
    """The pre-body region of a capture (everything before the JOB TEXT START
    marker). Falls back to the whole file only when the marker is absent, so
    hand-made legacy captures keep working."""
    if _BODY_START_MARKER in text:
        return text.split(_BODY_START_MARKER, 1)[0]
    return text


def _resolve_capture_path(job_file, base_dir=None):
    """Locate a capture from a rankings row's `Job File` value (usually a bare filename).
    Tries it as given, relative to the rankings folder, in the batch's standard source
    folder, then as a last resort a name search under the batch root."""
    name = str(job_file or "").strip()
    if not name:
        return None
    p = Path(name)
    candidates = [p]
    if base_dir:
        b = Path(base_dir)
        candidates += [b / name, b.parent / name, b.parent.joinpath(*_CAPTURE_SUBDIR) / p.name]
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    # Last resort: a name search — but STRICTLY bounded to this batch. Searching the parent
    # unconditionally would escape into the reviews root, where a same-named capture belonging to
    # a *different* batch is a plausible hit; silently binding a row to another batch's job post is
    # exactly the class of mis-mapping that makes the whole sheet untrustworthy. Only step up when
    # the parent is demonstrably this batch's root (it holds the standard capture subdir).
    if base_dir:
        b = Path(base_dir)
        roots = [b]
        try:
            if b.parent.joinpath(_CAPTURE_SUBDIR[0]).is_dir():
                roots.append(b.parent)
        except OSError:
            pass
        for root in roots:
            try:
                hit = next((h for h in root.rglob(p.name) if h.is_file()), None)
            except OSError:
                hit = None
            if hit:
                return hit
    return None


def posted_date_from_capture(job_file, base_dir=None):
    """The employer's publication date from a capture as ISO `YYYY-MM-DD`, or ""
    when the file or line is absent / `Unknown` (a posting whose ATS published no
    date must stay blank, never a guess). Reads the current `Job Posted At:` line
    first, then the legacy `Posted:` line — both bounded to the pre-body region."""
    path = _resolve_capture_path(job_file, base_dir)
    if not path:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    head = _capture_head(text)
    m = _JOB_POSTED_AT_RE.search(head)
    if m:
        return _parse_capture_date(m.group(1))
    m = _POSTED_LINE_RE.search(head)
    return m.group(1) if m else ""


def updated_date_from_capture(job_file, base_dir=None):
    """The employer's last-update date (`Job Updated At:` / legacy `· Updated:`)
    as ISO `YYYY-MM-DD`, "" when absent or `Unknown`. Same bounding rules as
    `posted_date_from_capture`."""
    path = _resolve_capture_path(job_file, base_dir)
    if not path:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    head = _capture_head(text)
    m = _JOB_UPDATED_AT_RE.search(head)
    if m:
        return _parse_capture_date(m.group(1))
    m = re.search(r"·\s*Updated:\s*(\d{4}-\d{2}-\d{2})", head)  # legacy provenance line
    return m.group(1) if m else ""


def practicality_notes_insert_at(headers):
    """Where "Comp + Lifestyle Fit Notes" belongs in an existing header row: immediately AFTER the
    practicality score column, i.e. at the head of the notes block. The score label is dynamic
    (a candidate's scoring card may relabel it), so fall back to the static column the notes must
    precede — "Mission Fit Notes" — which is the same slot; append only if neither anchor exists."""
    if H_PRACTSCORE_DEFAULT in headers:
        return headers.index(H_PRACTSCORE_DEFAULT) + 1
    if H_MISSIONNOTES in headers:
        return headers.index(H_MISSIONNOTES)
    return len(headers)


# --------------------------------------------------------------------------- #
# Mechanical comp envelope (B12) — the tracker's Comp Range is COMPUTED, the
# scorer's band choice is ADVISORY.
#
# Standing rule (Jessica, decided after overriding the scorer by hand twice): with
# no candidate-side basis to exclude a listed US band, include it. The displayed
# Comp Range is therefore min(applicable lows)-max(applicable highs) across the
# capture's OWN listed base-salary bands — endpoints may come from different
# geographic bands. A genuine source conflict (the capture's `Conflicting
# employer information: A vs B` shape) yields the outer envelope of BOTH readings
# plus `⚠ comp conflicting` in Data Completeness — never a silent pick.
#
# Downstream chain: Comp Fit is re-derived from the final Comp Range in the same
# pass (midpoint rule), so label and range stay consistent. The prose notes
# columns and FINAL/practicality SCORES are scorer-owned and are NOT recomputed
# here — a rescore is a human-triggered act, not a normalization side effect.
# --------------------------------------------------------------------------- #
_BAND_RANGE_RE = re.compile(
    r"\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*[-–—]\s*\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*([Kk])?")
_BAND_SINGLE_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*([Kk])?")
_NON_ANNUAL_BAND_RE = re.compile(r"(?i)/hour|/hr\b|hourly|/month|monthly|/week|weekly")
_ABSENCE_PREFIX_RE = re.compile(r"(?i)^(employer did not mention|could not verify|not posted)")
_CONFLICT_PREFIX_RE = re.compile(r"(?i)^conflicting employer information")


def _amount_thousands(raw, has_k):
    try:
        v = float(str(raw).replace(",", ""))
    except ValueError:
        return None
    if has_k or v < 1000:
        return v          # already in thousands ($172-248K shapes, K shared or explicit)
    return v / 1000.0     # full-dollar amounts (USD 182,000-227,000 shapes)


def base_salary_text_from_capture(text):
    """(comp_text, conflicting) — the capture's own Base Salary content: the inline
    value, the joined bullet list, or the legacy `Compensation:` line. Empty when
    the capture honestly reports an absence."""
    head = _capture_head(str(text or ""))
    m = re.search(r"^Base Salary:[ \t]*(.+)$", head, re.M)
    if m:
        val = m.group(1).strip()
        if _CONFLICT_PREFIX_RE.match(val):
            return val, True
        if _ABSENCE_PREFIX_RE.match(val):
            return "", False
        return val, False
    m = re.search(r"^Base Salary:[ \t]*\n((?:[ \t]*-\s+.*\n?)+)", head, re.M)
    if m:
        bullets = [ln.strip().lstrip("- ").strip()
                   for ln in m.group(1).splitlines() if ln.strip()]
        return " · ".join(bullets), False
    m = re.search(r"^Compensation:[ \t]*(.+)$", head, re.M)   # legacy captures
    if m:
        val = re.sub(r"\s*\[[a-z _]+\]\s*$", "", m.group(1)).strip()
        if _ABSENCE_PREFIX_RE.match(val) or val.lower() in ("n/a", "unknown", ""):
            return "", False
        return val, False
    return "", False


def comp_envelope(comp_text):
    """`lo-hi` in whole thousands across EVERY annual band in the text (floor the
    min, ceil the max — endpoints may come from different bands), or ""."""
    text = str(comp_text or "")
    lows, highs = [], []
    for segment in re.split(r"\s*[·;]\s*|\bvs\b", text):
        if _NON_ANNUAL_BAND_RE.search(segment):
            continue   # an hourly/monthly figure is never part of the annual envelope
        matched = False
        for m in _BAND_RANGE_RE.finditer(segment):
            lo = _amount_thousands(m.group(1), bool(m.group(3)))
            hi = _amount_thousands(m.group(2), bool(m.group(3)))
            if lo is None or hi is None or lo > hi or not (10 <= lo <= 2000):
                continue
            lows.append(lo)
            highs.append(hi)
            matched = True
        if not matched:
            sm = _BAND_SINGLE_RE.search(segment)
            if sm:
                v = _amount_thousands(sm.group(1), bool(sm.group(2)))
                if v is not None and 10 <= v <= 2000:
                    lows.append(v)
                    highs.append(v)
    if not lows:
        return ""
    import math
    return f"{int(math.floor(min(lows)))}-{int(math.ceil(max(highs)))}"


def comp_envelope_from_capture(job_file, base_dir=None):
    """(envelope, conflicting) computed mechanically from a row's capture. Empty
    envelope when the capture is absent or lists no annual band — the model's
    value then stands (there is nothing better to derive from)."""
    path = _resolve_capture_path(job_file, base_dir)
    if not path:
        return "", False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", False
    comp_text, conflicting = base_salary_text_from_capture(text)
    if not comp_text:
        return "", False
    return comp_envelope(comp_text), conflicting


COMP_CONFLICT_FLAG = "⚠ comp conflicting"


# --------------------------------------------------------------------------- #
# Row-integrity validation (B2) — runs after normalization, before anything
# downstream trusts the rows. The live defect: one malformed row lost its Lane
# Fit and Job File and had a Comp-Fit-shaped value ('Below floor') sitting in
# Data Completeness — and nothing noticed until a human cross-audit.
#
# Repair ONLY from a trustworthy structured source (Data Completeness can be
# re-derived from the row's own comp/location; Comp Fit is already re-derived
# from the normalized Comp Range upstream). Anything unrepairable FAILS LOUDLY
# naming the row. Values are never invented.
# --------------------------------------------------------------------------- #
COMP_FIT_VALUES = {"Below floor", "Near target", "Meets/above target", "Above floor",
                   "Unknown", "No comp prefs"}
NEEDS_REFETCH_STATUS = "⚠️ NEEDS RE-FETCH — content not verified"
_COMPLETENESS_PART_RE = re.compile(
    r"^(?:✓ complete|⚠ comp\+location not verified|⚠ comp not verified"
    r"|⚠ location unknown|⚠ comp conflicting"
    r"|comp not posted|location not posted|comp not posted \+ location not posted"
    r"|location not posted \+ comp not posted)$")


def is_valid_completeness(value) -> bool:
    """True when a Data Completeness cell is inside its vocabulary (`; `/` · `-joined
    parts of the known labels)."""
    v = str(value or "").strip()
    if not v:
        return False
    parts = [p.strip() for p in re.split(r"\s*[;·]\s*", v) if p.strip()]
    return all(_COMPLETENESS_PART_RE.match(p) for p in parts)


def validate_rankings_rows(rows, csv_path=None, fix=None, out=print):
    """Integrity errors for a normalized rankings table (row 0 = headers).
    Repairs what a trustworthy source allows (via `fix(row, col, value, label, n)`
    when given); returns the list of unrepairable error strings, each naming its
    row. The caller decides whether errors are fatal (the CLI exits nonzero)."""
    errors: list[str] = []
    if not rows:
        return errors
    headers = [str(h).strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(headers)}

    def cell(row, col):
        i = idx.get(col)
        return row[i].strip() if i is not None and i < len(row) else ""

    status_col = _status_column(headers) or "Status? [You Change]"
    for n, row in enumerate(rows[1:], start=2):
        if not any(str(c).strip() for c in row):
            continue
        company = cell(row, H_COMPANY) or "?"

        def err(msg):
            errors.append(f"row {n} ({company}): {msg}")

        # Row shape: every cell under its own header, none spilled past the schema.
        if len(row) != len(headers):
            err(f"row length {len(row)} != header length {len(headers)} — cells are "
                f"not aligned with their columns")
            continue  # nothing below can be trusted by name

        status = cell(row, status_col)
        needs_refetch = status == NEEDS_REFETCH_STATUS
        if status and not needs_refetch and status not in STATUS_VALUES:
            err(f"Status {status!r} is outside the tracker vocabulary")

        # Required identity cells. A NEEDS RE-FETCH row is legitimately sparse
        # (it was never scored), so only the identity columns are demanded there.
        for col in (H_COMPANY, H_TITLE, H_JOBFILE):
            if not cell(row, col):
                err(f"required cell blank: {col} (cannot be re-derived here — "
                    f"re-run the vet step or fill it from the batch's captures)")
        if not needs_refetch:
            if cell(row, H_LANE) and not cell(row, H_LANEFIT):
                err(f"Lane is set ({cell(row, H_LANE)!r}) but Lane Fit is blank — "
                    f"Lane Fit is model output and cannot be invented here")
            cf = cell(row, H_COMPFIT)
            if cf and cf not in COMP_FIT_VALUES:
                err(f"Comp Fit {cf!r} is outside its label domain")
            dc = cell(row, H_DATACOMPLETE)
            if dc and not is_valid_completeness(dc):
                # The exact live shape: a Comp-Fit-shaped value duplicated into
                # Data Completeness. Re-derivable from the row's own comp/location
                # — a TRUSTWORTHY repair, so repair rather than fail.
                if fix is not None and dc in COMP_FIT_VALUES:
                    fix(row, H_DATACOMPLETE,
                        fallback_completeness(cell(row, H_COMPRANGE), cell(row, H_WORKLOC)),
                        f"{H_DATACOMPLETE} (Comp-Fit-shaped value re-derived)", n)
                else:
                    err(f"Data Completeness {dc!r} is outside its vocabulary")
        # Job File must resolve to a capture when the batch layout is present.
        # A copy of the CSV elsewhere (no captures beside it) is only a notice.
        jf = cell(row, H_JOBFILE)
        if jf and csv_path is not None:
            if _resolve_capture_path(jf, base_dir=Path(csv_path).parent) is None:
                out(f"[norm_contracts] notice row {n} ({company}): Job File {jf!r} does "
                    f"not resolve to a capture from {Path(csv_path).parent} — fine for a "
                    f"detached copy, a problem inside a real batch.")
    for e in errors:
        out(f"[norm_contracts] ERROR {e}")
    return errors


def load_config(path):
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def migrate_rankings_headers(rows, score_labels=None, out=None):
    """Migrate a rankings table (list of rows, row 0 = headers) to the exact 27-column contract
    IN PLACE, at the WRITER level so every downstream reader finds it already correct.

    Order of operations: rename legacy headers -> drop removed columns -> insert missing ones ->
    reorder to the contract. Every step joins by header NAME (never index), so no column's data
    can shift onto a neighbour. Values are carried with their header; inserted columns start
    blank and are back-filled by the caller (`Data Completeness` from `fallback_completeness`,
    `Job Posted Date` from the capture). Returns True when anything changed.
    """
    if not rows:
        return False
    headers = [str(h).strip() for h in rows[0]]
    # Row dicts keyed by (renamed) header — index-free from here on.
    renamed = [LEGACY_RENAMES.get(h, h) for h in headers]
    records = []
    for row in rows[1:]:
        rec = {}
        for i, h in enumerate(renamed):
            rec[h] = row[i] if i < len(row) else ""
        records.append(rec)
    target = resolve_contract_headers(renamed, score_labels)
    # NEVER drop a column we don't recognize. Only the explicitly removed contract columns go;
    # anything else a user (or a candidate's relabelled scoring card) added keeps its data, parked
    # after the contract columns. Losing a column the person had been filling in by hand would be
    # a far worse failure than an extra column on the right.
    extras = [h for h in renamed
              if h not in target and h not in DROPPED_COLUMNS and h.strip()]
    target = target + list(dict.fromkeys(extras))
    if renamed == target and all(len(r) == len(target) for r in rows[1:]):
        return False
    if out:
        for legacy, final in LEGACY_RENAMES.items():
            if legacy in headers:
                out(f"[norm_contracts] migrate: renamed column {legacy!r} -> {final!r}")
        for gone in DROPPED_COLUMNS:
            if gone in renamed:
                out(f"[norm_contracts] migrate: dropped column {gone!r} (removed from the contract)")
        for added in target:
            if added not in renamed:
                out(f"[norm_contracts] migrate: inserted column {added!r}")
        if [h for h in renamed if h in target] != [h for h in target if h in renamed]:
            out("[norm_contracts] migrate: reordered columns to the 27-column contract")
    rows[0] = list(target)
    for i, rec in enumerate(records, start=1):
        rows[i] = [rec.get(h, "") for h in target]
    return True


def normalize_rankings_csv(csv_path, cfg, out=print, score_labels=None):
    """Migrate a rankings CSV to the 27-column contract and rewrite its contract-governed
    columns in place, printing every repair. Returns the number of cells changed."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    changed = 0
    # Misalignment must be caught BEFORE migration: the header-name join drops any
    # trailing cell that has no header, so a row wider than the schema would lose
    # data silently. Report it loudly instead (the row still migrates by name).
    pre_migration_errors = []
    n_headers = len(rows[0])
    for n, row in enumerate(rows[1:], start=2):
        if len(row) > n_headers and any(str(c).strip() for c in row[n_headers:]):
            pre_migration_errors.append(
                f"row {n}: {len(row)} cells but the header row has {n_headers} — cells are "
                f"not aligned with their columns (trailing data has no header and would be "
                f"dropped; fix the row before trusting this file)")
    if migrate_rankings_headers(rows, score_labels=score_labels, out=out):
        changed += 1
    headers = [h.strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(headers)}

    def fix(row, col, new, label, rownum):
        nonlocal changed
        i = idx.get(col)
        if i is None or i >= len(row):
            return
        old = row[i]
        if new != old:
            company = row[idx[H_COMPANY]] if H_COMPANY in idx and idx[H_COMPANY] < len(row) else "?"
            out(f"[norm_contracts] repair row {rownum} ({company}): {label}: {old!r} -> {new!r}")
            row[i] = new
            changed += 1

    for n, row in enumerate(rows[1:], start=2):
        if not any(c.strip() for c in row):
            continue
        if H_WORKLOC in idx and idx[H_WORKLOC] < len(row):
            fix(row, H_WORKLOC, normalize_working_location(row[idx[H_WORKLOC]], cfg),
                H_WORKLOC, n)
        if H_COMPRANGE in idx and idx[H_COMPRANGE] < len(row):
            fix(row, H_COMPRANGE, normalize_comp_range(row[idx[H_COMPRANGE]]),
                H_COMPRANGE, n)
            # B12: the MECHANICAL envelope from the capture's own listed bands
            # overrides the model's band choice (which is advisory). A source
            # conflict yields the outer envelope of both readings + a loud flag
            # in Data Completeness — never a silent pick.
            job_file = row[idx[H_JOBFILE]] if H_JOBFILE in idx and idx[H_JOBFILE] < len(row) else ""
            envelope, comp_conflicting = comp_envelope_from_capture(
                job_file, base_dir=Path(csv_path).parent)
            if envelope:
                fix(row, H_COMPRANGE, envelope,
                    f"{H_COMPRANGE} (mechanical envelope of the capture's bands)", n)
            if comp_conflicting and H_DATACOMPLETE in idx and idx[H_DATACOMPLETE] < len(row):
                dc = row[idx[H_DATACOMPLETE]].strip()
                if COMP_CONFLICT_FLAG not in dc:
                    fix(row, H_DATACOMPLETE,
                        (f"{dc} · {COMP_CONFLICT_FLAG}" if dc else COMP_CONFLICT_FLAG),
                        f"{H_DATACOMPLETE} (comp sources conflict)", n)
            # Re-derive Comp Fit from the FINAL comp range — this pass is the
            # single implementation of the midpoint rule; the JS label is a fallback.
            if H_COMPFIT in idx and idx[H_COMPFIT] < len(row):
                fix(row, H_COMPFIT, comp_fit_label(row[idx[H_COMPRANGE]], cfg),
                    H_COMPFIT, n)
        if H_LANE in idx and idx[H_LANE] < len(row):
            fix(row, H_LANE, normalize_lane(row[idx[H_LANE]]), H_LANE, n)
        # Status is the candidate's OWN column, so this only ever repairs spelling drift back to a
        # canonical value — it never reassigns a status. An unrecognized value is warned, not
        # rewritten (see normalize_status).
        status_col = _status_column(headers)
        if status_col and status_col in idx and idx[status_col] < len(row):
            fix(row, status_col, normalize_status(row[idx[status_col]]), status_col, n)
        # Data Completeness is back-filled for a legacy CSV that never had the column (ONE
        # implementation, shared with the XLSX build). A value already present stays put.
        if H_DATACOMPLETE in idx and idx[H_DATACOMPLETE] < len(row) \
                and not row[idx[H_DATACOMPLETE]].strip():
            comp = row[idx[H_COMPRANGE]] if H_COMPRANGE in idx and idx[H_COMPRANGE] < len(row) else ""
            loc = row[idx[H_WORKLOC]] if H_WORKLOC in idx and idx[H_WORKLOC] < len(row) else ""
            fix(row, H_DATACOMPLETE, fallback_completeness(comp, loc), H_DATACOMPLETE, n)
        # Job Posted Date is not model output — it is read back out of the capture. Only ever
        # FILLED IN over a blank or the `Unknown` placeholder (a real date already in the sheet
        # stays put), and it NEVER ends up blank: with no verified employer date it reads
        # `Unknown` rather than implying nobody looked.
        if H_POSTED in idx and idx[H_POSTED] < len(row) \
                and row[idx[H_POSTED]].strip() in ("", UNKNOWN_POSTED_DATE):
            job_file = row[idx[H_JOBFILE]] if H_JOBFILE in idx and idx[H_JOBFILE] < len(row) else ""
            posted = (posted_date_from_capture(job_file, base_dir=Path(csv_path).parent)
                      or UNKNOWN_POSTED_DATE)
            if posted:
                fix(row, H_POSTED, posted, H_POSTED, n)
    # Row-integrity validation (B2), after every repair above: trustworthy repairs
    # are applied through the same `fix` (so they count + print), anything
    # unrepairable is reported loudly and surfaces in the CLI exit code.
    integrity_errors = pre_migration_errors + validate_rankings_rows(
        rows, csv_path=csv_path,
        fix=lambda row, col, new, label, n: fix(row, col, new, label, n), out=out)
    for e in pre_migration_errors:
        out(f"[norm_contracts] ERROR {e}")
    if changed:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
    out(f"[norm_contracts] {csv_path}: {changed} cell(s) repaired."
        + (f" {len(integrity_errors)} row-integrity ERROR(s) — fix the rows or re-run "
           f"the vet step; these cannot be repaired mechanically." if integrity_errors else ""))
    normalize_rankings_csv.last_integrity_errors = integrity_errors
    return changed


def main(argv):
    parser = argparse.ArgumentParser(description="JAIL output-contract normalizers.")
    parser.add_argument("--normalize-rankings-csv", metavar="CSV",
                        help="rewrite the contract-governed columns of a rankings CSV in place")
    parser.add_argument("--config", default=None, help="path to jail.config.json")
    parser.add_argument("--score-labels", default=None,
                        help="JSON mapping of score slot -> column label as written "
                             "(e.g. '{\"style\": \"Culture Fit Score\"}'), so a candidate's "
                             "relabelled score column is recognized instead of treated as an extra")
    parser.add_argument("--application-name", action="store_true",
                        help="print the exact canonical 'Company - Role' string for a tailored "
                             "application (folder name, resume filename, cover-letter names); "
                             "requires --company and --role")
    parser.add_argument("--application-role", action="store_true",
                        help="print just the canonical role; requires --role")
    parser.add_argument("--resume-filename", action="store_true",
                        help="print the canonical tailored-resume filename; requires "
                             "--company, --role and --ext (candidate name from "
                             "jail.config.json unless --candidate-name is given)")
    parser.add_argument("--cover-letter-filename", action="store_true",
                        help="print the canonical cover-letter filename; same inputs as "
                             "--resume-filename")
    parser.add_argument("--candidate-name", default=None,
                        help="override the candidate name (default: candidate.name in "
                             "jail.config.json)")
    parser.add_argument("--ext", default="", help="file extension to preserve, e.g. .pages")
    parser.add_argument("--company", default=None, help="company name for --application-name")
    parser.add_argument("--role", default=None, help="role/title for --application-name / --application-role")
    args = parser.parse_args(argv[1:])
    if args.application_name:
        if not args.company or not args.role:
            parser.error("--application-name requires both --company and --role")
        print(canonical_application_name(args.company, args.role))
        return 0
    if args.application_role:
        if not args.role:
            parser.error("--application-role requires --role")
        print(canonical_application_role(args.role))
        return 0
    if args.resume_filename or args.cover_letter_filename:
        if not args.company or not args.role:
            parser.error("--resume-filename/--cover-letter-filename require both "
                         "--company and --role")
        who = args.candidate_name
        if who is None:
            who = candidate_name_from_config(load_config(args.config or "jail.config.json"))
        if not who:
            parser.error(
                "no candidate name available: set `candidate.name` in jail.config.json "
                "(run /intake, or add it) or pass --candidate-name. The filename's "
                "candidate half must never be improvised.")
        builder = (canonical_resume_filename if args.resume_filename
                   else canonical_cover_letter_filename)
        print(builder(who, args.company, args.role, args.ext))
        return 0
    if args.normalize_rankings_csv:
        cfg = load_config(args.config)
        labels = None
        if args.score_labels:
            try:
                parsed = json.loads(args.score_labels)
                labels = parsed if isinstance(parsed, dict) else None
            except Exception:
                print("[norm_contracts] --score-labels is not valid JSON; using engine defaults.")
        normalize_rankings_csv(args.normalize_rankings_csv, cfg, score_labels=labels)
        if getattr(normalize_rankings_csv, "last_integrity_errors", None):
            return 2   # loud: the workflow that shelled out sees a failing pass
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
