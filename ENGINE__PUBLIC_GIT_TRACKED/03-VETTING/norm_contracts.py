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
# CLI — normalize a rankings CSV in place (invoked by vet-jobs.js post-scoring,
# before the XLSX build). Prints every repair it makes.
# --------------------------------------------------------------------------- #
H_WORKLOC = "Working Location"
H_LANE = "Lane"
H_COMPRANGE = "Comp Range"
H_COMPFIT = "Comp Fit"
H_COMPANY = "Company"
H_POSTED = "Posted"
H_JOBFILE = "Job File"
# The practicality dimension's prose companion column. Static name (like "Mission Fit Notes") even
# though the score label itself is candidate-relabelable, so both Python passes can find it.
H_PRACTNOTES = "Comp + Lifestyle Fit Notes"
H_PRACTSCORE_DEFAULT = "Comp + Lifestyle Fit"  # default label of the score it annotates
H_MISSIONNOTES = "Mission Fit Notes"           # the column it must sit before


# --------------------------------------------------------------------------- #
# Posted — the employer's own publication date, read back out of the capture
#
# Every capture written by prep carries a `Posted: YYYY-MM-DD` provenance line when its ATS
# published one (the only other date in a capture is `Captured:`, our fetch date). This
# column surfaces it in the rankings so a nine-month-old posting is visible at a glance.
# Deliberately a STATIC ISO date, not an age/"days open" computation: a saved spreadsheet
# with a computed age silently goes stale and starts lying; a date never does.
#
# Back-filled by reading each row's `Job File` capture — the same mechanism as the other
# contract columns, so regenerating an OLD rankings CSV populates it too.
# --------------------------------------------------------------------------- #
_POSTED_LINE_RE = re.compile(r"^Posted:\s*(\d{4}-\d{2}-\d{2})", re.M)
_CAPTURE_SUBDIR = ("3 - Source Material", "All Job Posts (full text)")


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
    if base_dir:
        for root in (Path(base_dir), Path(base_dir).parent):
            try:
                hit = next((h for h in root.rglob(p.name) if h.is_file()), None)
            except OSError:
                hit = None
            if hit:
                return hit
    return None


def posted_date_from_capture(job_file, base_dir=None):
    """The `Posted: YYYY-MM-DD` date from a capture, or "" when the file or line is absent
    (a posting whose ATS published no date must stay blank, never a guess)."""
    path = _resolve_capture_path(job_file, base_dir)
    if not path:
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    m = _POSTED_LINE_RE.search(text)
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


def load_config(path):
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def normalize_rankings_csv(csv_path, cfg, out=print):
    """Rewrite the contract-governed columns of a rankings CSV in place,
    printing every repair. Returns the number of cells changed."""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if not rows:
        return 0
    headers = [h.strip() for h in rows[0]]
    changed = 0
    def insert_column(name, at):
        """Positional header insert + blank back-fill, so an OLDER CSV that predates a column
        regenerates with it in the right slot instead of shifting every later column's data."""
        headers.insert(at, name)
        rows[0] = list(headers)
        for row in rows[1:]:
            while len(row) < len(headers) - 1:
                row.append("")
            row.insert(at, "")

    # An OLDER CSV predates the Posted column — insert it (right after Comp Range, keeping
    # the human-scannable block contiguous) so regenerating any batch back-fills the date.
    if H_POSTED not in headers:
        insert_column(H_POSTED,
                      (headers.index(H_COMPRANGE) + 1) if H_COMPRANGE in headers else len(headers))
        changed += 1
    # Likewise for the practicality dimension's notes column. Nothing can back-fill its VALUE
    # (it is model rationale, not derivable), so the cell stays empty — the point of inserting it
    # positionally is that no other column's data shifts.
    if H_PRACTNOTES not in headers:
        insert_column(H_PRACTNOTES, practicality_notes_insert_at(headers))
        changed += 1
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
            # Re-derive Comp Fit from the NORMALIZED comp range — this pass is the
            # single implementation of the midpoint rule; the JS label is a fallback.
            if H_COMPFIT in idx and idx[H_COMPFIT] < len(row):
                fix(row, H_COMPFIT, comp_fit_label(row[idx[H_COMPRANGE]], cfg),
                    H_COMPFIT, n)
        if H_LANE in idx and idx[H_LANE] < len(row):
            fix(row, H_LANE, normalize_lane(row[idx[H_LANE]]), H_LANE, n)
        # Posted is not model output — it is read back out of the capture's provenance line.
        # Only ever FILLED IN, never overwritten (a date already in the sheet stays put).
        if H_POSTED in idx and idx[H_POSTED] < len(row) and not row[idx[H_POSTED]].strip():
            job_file = row[idx[H_JOBFILE]] if H_JOBFILE in idx and idx[H_JOBFILE] < len(row) else ""
            posted = posted_date_from_capture(job_file, base_dir=Path(csv_path).parent)
            if posted:
                fix(row, H_POSTED, posted, H_POSTED, n)
    if changed:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows)
    out(f"[norm_contracts] {csv_path}: {changed} cell(s) repaired.")
    return changed


def main(argv):
    parser = argparse.ArgumentParser(description="JAIL output-contract normalizers.")
    parser.add_argument("--normalize-rankings-csv", metavar="CSV",
                        help="rewrite the contract-governed columns of a rankings CSV in place")
    parser.add_argument("--config", default=None, help="path to jail.config.json")
    parser.add_argument("--application-name", action="store_true",
                        help="print the exact canonical 'Company - Role' string for a tailored "
                             "application (folder name, resume filename, cover-letter names); "
                             "requires --company and --role")
    parser.add_argument("--application-role", action="store_true",
                        help="print just the canonical role; requires --role")
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
    if args.normalize_rankings_csv:
        cfg = load_config(args.config)
        normalize_rankings_csv(args.normalize_rankings_csv, cfg)
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
