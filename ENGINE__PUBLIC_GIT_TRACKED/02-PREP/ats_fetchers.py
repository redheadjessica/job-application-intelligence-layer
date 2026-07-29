#!/usr/bin/env python3
"""ATS-aware job fetchers.

Many applicant tracking systems render the job text client-side with JavaScript,
so a plain HTML GET returns an empty shell and text extraction finds nothing.
Most of them also expose a public JSON API that returns the job text directly.
Pulling from that API is faster and far more reliable than scraping rendered HTML.

This module detects supported ATSes from the URL and fetches the job from the
structured API. `fetch_via_ats(url)` returns a normalized dict on success, or
None when the URL is not a recognized ATS or the lookup fails, so callers can
fall back to their normal fetch path.

Currently supported:
- Ashby (jobs.ashbyhq.com) via the public posting-api job board feed. Rich
  structured comp (per-zone tiers), secondary locations, address, and workplace
  type are captured; application questions are NOT on the posting-api (a caller
  can render the apply page and pass the fields through `filter_questions`).
- Greenhouse (greenhouse.io) via the boards API with `?questions=true&
  pay_transparency=true` — structured pay ranges (when posted), offices, and the
  application questions (EEO/demographics stay in their own keys, never merged).
- Lever (lever.co) via the per-posting JSON endpoint (salaryRange + workplace).
- LinkedIn (linkedin.com/jobs) via the logged-out "guest" jobPosting endpoint.

To add another ATS, write a `_fetch_<name>` function returning the same dict
shape (see below) and register it in `fetch_via_ats`. Extraction stays PII-free:
these fetchers never read the user profile or jail.config.json — the
candidate-relative interpretation of location/comp happens later, at vetting.
"""
from __future__ import annotations

import html
import re
from typing import Optional
from urllib.parse import parse_qs, unquote, urlparse

try:
    import requests
except ImportError:  # the pure URL helpers (ids, company, normalization) don't need it; fetching does
    requests = None

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
)

# Normalized result shape returned by every fetcher:
#   {
#     "title": str,
#     "company": str,
#     "location": str | None,             # employer's primary location string
#     "working_location": str | None,     # primary + secondary metros (+ cadence)
#     "employment_type": str | None,
#     "remote": bool | None,
#     "workplace": str | None,            # "Remote" | "Hybrid" | "Onsite" | None
#     "compensation": str | None,         # normalized, per-zone if applicable
#     "compensation_raw": str | None,     # verbatim employer wording
#     "location_raw": str | None,         # verbatim offices/addresses
#     "cadence_raw": str | None,          # verbatim office-attendance wording
#     "benefits": str | None,             # short summary mined from prose (soft)
#     "equity": str | None,               # short summary mined from prose (soft)
#     "apply_url": str | None,
#     "posting_id": str | None,
#     "source": str,                      # e.g. "ashby-posting-api"
#     "comp_expected": bool,              # ATS says comp SHOULD be present
#     "location_expected": bool,          # ATS reliably carries a location
#     "questions": list[dict],            # KEPT application questions (filtered)
#     "text": str,                        # the body the caller writes out
#   }
#
# A normalized question dict (as produced by the ATS question parsers and
# consumed by `filter_questions` / the output builder):
#   {
#     "label": str,            # full question text, verbatim
#     "help": str | None,      # help/description text, verbatim
#     "type": str,             # coarse type: "textarea"/"select"/"boolean"/...
#     "source_type": str,      # raw ATS type (e.g. "LongText", "ValueSelect")
#     "required": bool,
#     "name": str,             # primary field name / path
#     "names": list[str],      # all underlying field names (GH multi-field Qs)
#     "options": list[str],    # choice labels for selects
#   }


# --------------------------------------------------------------------------- #
# Application-question capture + NARROW filter (shared, generic, PII-free)
#
# Keep a question ONLY if it meets one of:
#   (a) it is a free-compose field (textarea / LongText) asking for a
#       job-specific WRITTEN response the candidate must think and compose, OR
#   (b) its label reveals material job info that affects vetting/ranking:
#       working-location, office cadence, or EMPLOYER-provided compensation.
# Everything else is dropped — the entire routine/identity/EEO set AND
# work-authorization, visa sponsorship, and candidate compensation-EXPECTATIONS.
# This is generic engine behavior: name-based + label-regex only, no per-user
# anything. A comp/location *question* is never the job *fact* (see
# `question_provides_working_location` / `question_provides_employer_comp`).
# --------------------------------------------------------------------------- #

# Exact system/identity field names to drop outright (lowercased). Ashby system
# fields are additionally caught by the `_systemfield_` prefix rule below.
_EXCLUDE_FIELD_NAMES = {
    "first_name", "last_name", "name", "full_name", "preferred_name",
    "preferred_first_name", "email", "phone", "resume", "resume_text", "cv",
    "cover_letter", "cover_letter_text", "linkedin", "linkedin_profile",
    "linkedin_url", "website", "portfolio", "github", "location", "address",
    "current_location", "city", "country", "pronouns", "gender", "race",
    "ethnicity", "hispanic_ethnicity", "veteran_status", "disability_status",
    "work_authorization", "visa", "sponsorship",
}

# Label patterns that mark a question as routine / identity / EEO / work-auth /
# visa / candidate comp-EXPECTATIONS — dropped regardless of field type.
_EXCLUDE_LABEL_RE = re.compile(
    r"(?i)("
    r"first name|last name|full name|preferred (first )?name|name pronunciation|"
    r"\bpronouns?\b|\bemail\b|phone number|\bphone\b|resume|\bcv\b|cover letter|"
    r"linkedin|portfolio|personal website|\bwebsite\b|\bgithub\b|"
    r"authoriz(ed|ation) to work|legally authorized|right to work|"
    r"employment eligibilit|work permit|"
    r"visa|sponsorship|immigration status|"
    r"(requested|desired|expected|your) (compensation|salary)|"
    r"(compensation|salary|pay) (expectation|requirement|range you|range are you)|"
    r"salary expectation|compensation expectation|"
    r"\bgender\b|\brace\b|ethnic|hispanic|latino|veteran|disabilit|"
    r"sexual orientation|self[- ]identif|demographic|"
    r"country of residence|current (city|residence|address)|home address|"
    r"where (do|are) you (currently )?(live|located|residing|reside)"
    r")"
)

# Label patterns that KEEP a question because it reveals working-location,
# office cadence, or employer-provided compensation.
_REVEAL_LABEL_RE = re.compile(
    r"(?i)("
    r"which office|nearest office|closest (to )?(an? )?office|"
    r"within \d+ ?miles|"
    r"\d+\s*days?\s*(a|per)\s*week|days? per week|"
    r"(attend|in[- ]person|on[- ]?site|onsite|commut).{0,40}(office|day|week)|"
    r"(office|hub|on[- ]?site).{0,40}(attend|day|week|cadence|proximity|commut)|"
    r"relocat|"
    r"(base )?(salary|compensation) (range|band) (for this|is |will)"
    r")"
)

# Coarse types that count as "free compose".
_COMPOSE_TYPE_HINTS = ("textarea", "longtext", "long_text", "essay", "multiline", "paragraph")

# Cadence extraction ("2 days per week", "at least 3 days a week", etc.).
_CADENCE_RE = re.compile(r"(?i)((?:at least |minimum of |a minimum of )?\d+\s*days?\s*(?:a|per)\s*week)")


def _is_compose_type(qtype: str) -> bool:
    t = (qtype or "").lower()
    return any(h in t for h in _COMPOSE_TYPE_HINTS)


def question_provides_working_location(q: dict) -> bool:
    """True if this KEPT question states the job's location/office-cadence
    requirement (e.g. "attend a listed office N days/week"). A "where do you
    currently live?" question does NOT qualify — that is the applicant's
    location and is dropped by the exclusion filter before it ever gets here."""
    label = (q or {}).get("label") or ""
    low = label.lower()
    if _EXCLUDE_LABEL_RE.search(low):
        return False
    has_office = any(k in low for k in ("office", "in person", "in-person", "onsite", "on-site", "hub"))
    has_cadence = bool(_CADENCE_RE.search(low)) or "days per week" in low
    has_miles = "miles" in low and "office" in low
    return (has_office and has_cadence) or has_miles


def question_provides_employer_comp(q: dict) -> bool:
    """True only if the question states an EMPLOYER-provided pay figure, not the
    candidate's expectations. Candidate comp-expectations are excluded upstream."""
    label = (q or {}).get("label") or ""
    if _EXCLUDE_LABEL_RE.search(label.lower()):
        return False
    return bool(_REVEAL_LABEL_RE.search(label) and re.search(r"(?i)(salary|compensation|pay|\$)", label))


def parse_office_cadence(q: dict) -> Optional[dict]:
    """From an office-attendance question, return the employer's COMPLETE
    eligible-metro list + the cadence, verbatim-ish and PII-free. No mapping to
    any candidate city (that happens at vetting from jail.config.json).
    Returns {"metros": [...], "cadence": str|None, "verbatim": str} or None."""
    if not question_provides_working_location(q):
        return None
    label = q.get("label") or ""
    metros = [o for o in (q.get("options") or []) if o]
    cadence = None
    m = _CADENCE_RE.search(label)
    if m:
        cadence = m.group(1).strip()
    return {"metros": metros, "cadence": cadence, "verbatim": label.strip()}


def filter_questions(questions: list[dict]) -> list[dict]:
    """Apply the narrow keep-filter. Input/kept dicts share the normalized
    question shape documented at the top of this module. Order is preserved and
    kept questions are returned EXACTLY as given (text, help, choices, required)."""
    kept: list[dict] = []
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        names = [(n or "").lower() for n in (q.get("names") or [q.get("name")]) if n]
        # Ashby system fields, plus any exact routine/identity field name.
        if any(n.startswith("_systemfield_") for n in names):
            continue
        if any(n in _EXCLUDE_FIELD_NAMES for n in names):
            continue
        label = q.get("label") or ""
        if _EXCLUDE_LABEL_RE.search(label.lower()):
            continue
        is_compose = _is_compose_type(q.get("type") or q.get("source_type"))
        reveals = question_provides_working_location(q) or bool(_REVEAL_LABEL_RE.search(label))
        if is_compose or reveals:
            kept.append(q)
    return kept


# --------------------------------------------------------------------------- #
# Benefits / equity prose mining (SOFT — fine to come back "Not posted")
# --------------------------------------------------------------------------- #
_BENEFITS_HEADING_RE = re.compile(r"(?im)^[\s#>*_\-]*(benefits?|perks?( & benefits)?|what we offer)\b[:\s]*$")
_EQUITY_RE = re.compile(r"(?i)([^.\n]*\b(equity|stock options?|RSUs?|restricted stock|ESPP)\b[^.\n]*)")


def mine_benefits_equity(text: str) -> tuple[Optional[str], Optional[str]]:
    """Best-effort summary of benefits + equity from the description prose. Reads
    a 'Benefits/Perks' section (first handful of bullet/line items) and any
    equity/stock-option sentence. Returns (benefits|None, equity|None)."""
    body = text or ""
    benefits = None
    m = _BENEFITS_HEADING_RE.search(body)
    if m:
        tail = body[m.end():]
        items: list[str] = []
        for raw in tail.splitlines():
            line = raw.strip(" \t-•*·").strip()
            if not line:
                if items:
                    break
                continue
            # Stop at the next section heading (short Title-ish line ending in ':').
            if line.endswith(":") and len(line) < 40 and items:
                break
            items.append(line)
            if len(items) >= 6:
                break
        if items:
            benefits = "; ".join(items)
            if len(benefits) > 300:
                benefits = benefits[:297].rstrip() + "…"
    equity = None
    e = _EQUITY_RE.search(body)
    if e:
        equity = e.group(1).strip()
        if len(equity) > 200:
            equity = equity[:197].rstrip() + "…"
    return benefits, equity


def fetch_via_ats(url: str, timeout: int = 20) -> Optional[dict]:
    """Dispatch to the matching ATS fetcher, or return None if unrecognized.

    Beyond the four known ATS hosts, a CUSTOM career domain that carries an ATS
    id in its query string is routed to that ATS: `?ashby_jid=<uuid>` -> Ashby,
    `?gh_jid=<digits>` -> Greenhouse. This rescues postings like
    `lark.com/careers?ashby_jid=...` whose own page renders only a cookie banner.
    (The gh_jid path runs through the embedded-Greenhouse recovery, which carries
    the title-match safety guard, so it is handled in the fetch cascade rather
    than blindly here.)"""
    host = urlparse(url).netloc.lower()
    qs = parse_qs(urlparse(url).query)
    try:
        if host.endswith("ashbyhq.com"):
            return _fetch_ashby(url, timeout=timeout)
        if host.endswith("greenhouse.io"):
            return _fetch_greenhouse(url, timeout=timeout)
        if host.endswith("lever.co"):
            return _fetch_lever(url, timeout=timeout)
        if "linkedin.com" in host:
            return _fetch_linkedin(url, timeout=timeout)
        # Custom (non-ATS) host carrying an ATS id in the query string.
        if qs.get("ashby_jid"):
            hit = _fetch_ashby_by_jid(url, qs["ashby_jid"][0], timeout=timeout)
            if hit:
                return hit
    except Exception:
        # Any failure here is non-fatal: the caller falls back to HTML fetching.
        return None
    return None


# --------------------------------------------------------------------------- #
# Ashby
# --------------------------------------------------------------------------- #

# Cache board feeds per org so a batch with many jobs from one company fetches
# the (potentially large) feed only once per run.
_ASHBY_BOARD_CACHE: dict[str, list] = {}


def _ashby_board(org: str, timeout: int) -> list:
    if org in _ASHBY_BOARD_CACHE:
        return _ASHBY_BOARD_CACHE[org]
    api = f"https://api.ashbyhq.com/posting-api/job-board/{org}"
    resp = requests.get(
        api,
        params={"includeCompensation": "true"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    resp.raise_for_status()
    jobs = resp.json().get("jobs", []) or []
    _ASHBY_BOARD_CACHE[org] = jobs
    return jobs


def _fetch_ashby(url: str, timeout: int = 20) -> Optional[dict]:
    """Fetch an Ashby job posting from the public posting-api board feed.

    URL shape: https://jobs.ashbyhq.com/{org}/{job-uuid}[/application][?...]
    The board feed is the authoritative source; we match the posting by its UUID.
    """
    parsed = urlparse(url)
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if not parts:
        return None

    org = parts[0]
    # The posting UUID may be any later path segment (a trailing slug or
    # "/application" can follow it). Fall back to scanning the whole URL.
    job_id = None
    for p in parts[1:]:
        m = UUID_RE.fullmatch(p)
        if m:
            job_id = m.group(0).lower()
            break
    if job_id is None:
        m = UUID_RE.search(url)
        job_id = m.group(0).lower() if m else None
    if job_id is None:
        # A board root with no specific posting: let the caller fall back.
        return None

    jobs = _ashby_board(org, timeout=timeout)
    job = next((j for j in jobs if str(j.get("id", "")).lower() == job_id), None)
    if job is None:
        return None
    return _ashby_job_to_result(job, org)


def _ashby_org_candidates(url: str) -> list[str]:
    """Candidate Ashby org slugs for a CUSTOM domain carrying `?ashby_jid=` —
    e.g. lark.com/careers?ashby_jid=... -> ['lark']. Domain-derived; the UUID jid
    match against the org's board feed is the real guard (UUIDs are globally
    unique, so a hit in any org's board IS the posting)."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    labels = [l for l in host.split(".") if l]
    out: list[str] = []
    if len(labels) >= 2:
        for cand in _brand_token_variants(labels[-2]):
            if cand not in _GENERIC_DOMAIN_LABELS and cand not in out:
                out.append(cand)
    for l in labels:
        for cand in _brand_token_variants(l):
            if cand not in _GENERIC_DOMAIN_LABELS and cand not in out:
                out.append(cand)
    return out


def _fetch_ashby_by_jid(url: str, jid: str, timeout: int = 20) -> Optional[dict]:
    """Fetch an Ashby posting referenced by `?ashby_jid=<uuid>` on a NON-Ashby
    host. The org is guessed from the domain; the posting is matched by its UUID
    against the org's board feed (a UUID match is unambiguous, so no title guard
    is needed here). Returns the normalized Ashby result or None."""
    m = UUID_RE.search(jid or "")
    if not m:
        return None
    job_uuid = m.group(0).lower()
    for org in _ashby_org_candidates(url):
        try:
            jobs = _ashby_board(org, timeout=timeout)
        except Exception:
            continue
        job = next((j for j in jobs if str(j.get("id", "")).lower() == job_uuid), None)
        if job is not None:
            result = _ashby_job_to_result(job, org)
            if result:
                result["source"] = "ashby-posting-api (custom-domain jid)"
            return result
    return None


def _ashby_compensation(comp: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (normalized per-zone string, verbatim raw) from Ashby's
    `compensation` object. Prefers the per-zone `compensationTiers`."""
    if not isinstance(comp, dict):
        return None, None
    tiers = comp.get("compensationTiers") or []
    zone_parts: list[str] = []
    for t in tiers:
        if not isinstance(t, dict):
            continue
        title = (t.get("title") or "").strip()
        summary = (t.get("tierSummary") or "").strip()
        # Prefer explicit min/max/currency/interval from the salary component.
        comp_bits = []
        for c in (t.get("components") or []):
            if not isinstance(c, dict):
                continue
            lo, hi = c.get("minValue"), c.get("maxValue")
            cur = c.get("currencyCode") or ""
            interval = (c.get("interval") or "").strip()
            if lo or hi:
                rng = f"{cur} {lo:,}–{hi:,}".strip() if (lo and hi) else f"{cur} {lo or hi:,}".strip()
                if interval and interval.upper() not in ("", "1 YEAR"):
                    rng = f"{rng}/{interval}"
                comp_bits.append(rng)
        detail = summary or (", ".join(comp_bits) if comp_bits else "")
        if title and detail:
            zone_parts.append(f"{title}: {detail}")
        elif detail:
            zone_parts.append(detail)
    normalized = " · ".join(zone_parts) if zone_parts else (
        comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary")
    )
    raw_bits = []
    if comp.get("compensationTierSummary"):
        raw_bits.append(comp["compensationTierSummary"])
    for t in tiers:
        if isinstance(t, dict) and t.get("tierSummary"):
            label = f"{t.get('title')}: " if t.get("title") else ""
            raw_bits.append(f"{label}{t['tierSummary']}")
    raw = "; ".join(dict.fromkeys(raw_bits)) or normalized
    return normalized, raw


def _ashby_working_location(job: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (working_location string, verbatim locations/addresses) from the
    primary location + secondaryLocations (metros only — no candidate mapping)."""
    metros: list[str] = []
    if job.get("location"):
        metros.append(str(job["location"]).strip())
    for sl in (job.get("secondaryLocations") or []):
        if isinstance(sl, dict) and sl.get("location"):
            metros.append(str(sl["location"]).strip())
    metros = [m for m in dict.fromkeys(metros) if m]
    working = "; ".join(metros) if metros else None

    def _addr(a):
        pa = (a or {}).get("postalAddress") if isinstance(a, dict) else None
        if not isinstance(pa, dict):
            return None
        piece = ", ".join(p for p in [pa.get("addressLocality"), pa.get("addressRegion"),
                                      pa.get("addressCountry")] if p)
        return piece or None

    addrs = []
    primary = _addr(job.get("address"))
    if primary:
        addrs.append(primary)
    for sl in (job.get("secondaryLocations") or []):
        piece = _addr(sl.get("address")) if isinstance(sl, dict) else None
        if piece:
            addrs.append(piece)
    location_raw = "; ".join(dict.fromkeys(addrs)) or None
    return working, location_raw


def _ashby_job_to_result(job: dict, org: str) -> Optional[dict]:
    """Pure Ashby job-object -> normalized result. Kept separate from the network
    fetch so it is unit-testable against a saved posting-api fixture."""
    body = (job.get("descriptionPlain") or "").strip()
    if not body:
        body = _html_to_text(job.get("descriptionHtml") or "")
    if not body:
        return None

    comp, comp_raw = _ashby_compensation(job.get("compensation") or {})
    working_location, location_raw = _ashby_working_location(job)
    benefits, equity = mine_benefits_equity(body)
    workplace = job.get("workplaceType")
    comp_expected = bool(job.get("shouldDisplayCompensationOnJobPostings"))

    return {
        "title": (job.get("title") or "").strip() or "Unknown Title",
        "company": _prettify_slug(org),
        "location": job.get("location"),
        "working_location": working_location,
        "employment_type": job.get("employmentType"),
        "remote": job.get("isRemote"),
        "workplace": workplace,
        "compensation": comp,
        "compensation_raw": comp_raw,
        "location_raw": location_raw,
        "cadence_raw": None,
        "benefits": benefits,
        "equity": equity,
        "apply_url": job.get("applyUrl") or job.get("jobUrl"),
        "posting_id": str(job.get("id")) if job.get("id") else None,
        "source": "ashby-posting-api",
        "comp_expected": comp_expected,
        "location_expected": True,
        "questions": [],  # not on the posting-api; render the apply page for these
        "text": body,
    }


def normalize_ashby_apply_fields(form: dict) -> list[dict]:
    """Normalize the fields scraped from a rendered Ashby apply page into the
    shared question shape. Ashby form-field types seen: LongText, String, Email,
    Phone, File, Boolean, ValueSelect, Name, Location. System/identity fields are
    named `_systemfield_*`. This does NOT filter — pass the result through
    `filter_questions`."""
    type_map = {
        "longtext": "textarea", "string": "input_text", "email": "input_text",
        "phone": "input_text", "file": "file", "boolean": "boolean",
        "valueselect": "select", "multiselect": "select", "name": "input_text",
        "location": "input_text", "number": "input_number", "date": "input_date",
    }
    out: list[dict] = []
    for f in (form.get("fields") or []):
        if not isinstance(f, dict):
            continue
        raw_type = (f.get("type") or "").strip()
        options = []
        for o in (f.get("options") or []):
            if isinstance(o, dict):
                options.append(o.get("label") or o.get("value") or "")
            elif o:
                options.append(str(o))
        name = f.get("path") or f.get("id") or ""
        out.append({
            "label": (f.get("title") or "").strip(),
            "help": (f.get("descriptionPlain") or f.get("description") or None),
            "type": type_map.get(raw_type.lower(), raw_type.lower() or "input_text"),
            "source_type": raw_type,
            "required": bool(f.get("isRequired")),
            "name": name,
            "names": [name],
            "options": [o for o in options if o],
        })
    return out


# --------------------------------------------------------------------------- #
# LinkedIn
# --------------------------------------------------------------------------- #

def _linkedin_job_id(url: str) -> Optional[str]:
    """Pull the numeric job id from any LinkedIn job URL shape."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    for key in ("currentJobId", "jobId"):
        vals = query.get(key)
        if vals and vals[0].isdigit():
            return vals[0]
    # .../jobs/view/<slug>-<id>/  or  .../jobs/view/<id>
    m = re.search(r"/jobs/view/(?:[^/]*?-)?(\d{6,})", parsed.path)
    if m:
        return m.group(1)
    # Last resort: any long digit run in the path.
    m = re.search(r"(\d{8,})", parsed.path)
    return m.group(1) if m else None


def _fetch_linkedin(url: str, timeout: int = 20) -> Optional[dict]:
    """Fetch a LinkedIn job via the logged-out guest jobPosting endpoint.

    LinkedIn job pages require login and render client-side, but the public
    job-view served to logged-out visitors is backed by a guest endpoint that
    returns a self-contained HTML fragment with the title, company, location,
    and full description. We parse that fragment.
    """
    job_id = _linkedin_job_id(url)
    if not job_id:
        return None

    api = f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
    resp = requests.get(
        api,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=timeout,
    )
    # 429 (rate limited) or other non-200: let the caller fall back.
    if resp.status_code != 200 or not resp.text.strip():
        return None

    try:
        from bs4 import BeautifulSoup
    except Exception:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")

    def pick(*selectors):
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(" ", strip=True)
                if txt:
                    return txt
        return None

    title = pick("h2.top-card-layout__title", ".topcard__title", "h1", "h2") or "Unknown Title"
    company = pick("a.topcard__org-name-link", ".topcard__flavor", ".top-card-layout__card a")
    location = pick(".topcard__flavor--bullet", ".top-card-layout__second-subline .topcard__flavor")

    # LinkedIn surfaces a posted salary range in a dedicated element in the guest
    # fragment (when the employer provided one). Pull it so it lands in the
    # "Compensation:" header the scorer reads, instead of being dropped.
    comp = pick(
        ".compensation__salary",
        ".salary.compensation__salary",
        ".compensation__salary-range",
        "div.salary",
    )

    desc_el = soup.select_one(".show-more-less-html__markup") or soup.select_one(
        ".description__text"
    )
    body = _html_to_text(str(desc_el)) if desc_el else _html_to_text(resp.text)
    if not body:
        return None

    # Fallback: if no structured salary element, scan the description body for an
    # explicit salary line (many employers write the range into the JD text).
    if not comp and body:
        m = re.search(
            r"(?im)^.*(?:salary|compensation|base pay|pay range|annual)\b.*"
            r"\$\s?\d{2,3}[,\d]*\s?(?:k|,000)?\s?(?:[-–to]+)\s?\$?\s?\d{2,3}[,\d]*\s?(?:k|,000)?.*$",
            body,
        )
        if m:
            comp = m.group(0).strip()[:200]

    lines = []
    if location:
        lines.append(f"Location: {location}")
    if comp:
        lines.append(f"Compensation: {comp}")
    header = "\n".join(lines)
    text = f"{header}\n\n{body}".strip() if header else body

    return {
        "title": title,
        "company": company or "LinkedIn",
        "location": location,
        "employment_type": None,
        "remote": None,
        "compensation": comp,
        "apply_url": url,
        "text": text,
        "source": "linkedin-guest-api",
    }


# --------------------------------------------------------------------------- #
# Greenhouse
# --------------------------------------------------------------------------- #

# The rendered Greenhouse page often reports its "company" as the generic ATS name
# ("Greenhouse"), and the host (job-boards.greenhouse.io) is useless for the company.
# The board token in the URL path IS the company's slug, and the board's API record
# carries its clean display name. We always derive the real company from that.

_GH_COMPANY_CACHE: dict[str, Optional[str]] = {}


def _greenhouse_company(board: str, timeout: int) -> Optional[str]:
    """The board's display name is the clean company name (e.g. 'honehealth' -> 'Hone')."""
    if board in _GH_COMPANY_CACHE:
        return _GH_COMPANY_CACHE[board]
    name = None
    try:
        resp = requests.get(
            f"https://boards-api.greenhouse.io/v1/boards/{board}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code == 200:
            name = (resp.json().get("name") or "").strip() or None
    except Exception:
        name = None
    _GH_COMPANY_CACHE[board] = name
    return name


def _greenhouse_ids(url: str):
    """Return (board_token, job_id) for any Greenhouse URL shape, or (None, None)."""
    parsed = urlparse(url)
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    qs = parse_qs(parsed.query)
    # Embed form: /embed/job_app?for={board}&token={id}
    if "embed" in [p.lower() for p in parts]:
        token = (qs.get("token") or [None])[0]
        return (qs.get("for") or [None])[0], (token if (token and token.isdigit()) else None)
    # Standard form: /{board}/jobs/{id}
    board = parts[0] if parts else None
    job_id = None
    for i, p in enumerate(parts):
        if p.lower() in ("jobs", "job") and i + 1 < len(parts) and parts[i + 1].isdigit():
            job_id = parts[i + 1]
            break
    if job_id is None:
        m = re.search(r"(\d{5,})", parsed.path)
        job_id = m.group(1) if m else None
    return board, job_id


def _fetch_greenhouse(url: str, timeout: int = 20) -> Optional[dict]:
    """Fetch a Greenhouse job from the public boards API.

    The company is taken from the board (token/display name), never from the page,
    so it can't come back as "Greenhouse".
    """
    board, job_id = _greenhouse_ids(url)
    if not board or not job_id:
        return None

    resp = requests.get(
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}",
        # questions=true surfaces the application form; pay_transparency=true adds
        # structured pay_input_ranges (often empty — comp may legitimately be absent).
        params={"questions": "true", "pay_transparency": "true"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        return None
    job = resp.json()
    company = _greenhouse_company(board, timeout) or _prettify_slug(board)
    return _greenhouse_job_to_result(job, board, company, url)


def parse_greenhouse_questions(job: dict) -> list[dict]:
    """Normalize Greenhouse's `questions[]` into the shared question shape.

    Reads ONLY the `questions` array. EEO/demographics live in separate
    `compliance` / `demographic_questions` keys and geo probes in
    `location_questions` — those are never merged in (identity data, always dropped)."""
    out: list[dict] = []
    for q in (job.get("questions") or []):
        if not isinstance(q, dict):
            continue
        fields = q.get("fields") or []
        names = [(f.get("name") or "") for f in fields if isinstance(f, dict)]
        types = [(f.get("type") or "") for f in fields if isinstance(f, dict)]
        # A "textarea" field is the compose signal; prefer it as the coarse type.
        coarse = "textarea" if any("textarea" in t for t in types) else (types[0] if types else "")
        options: list[str] = []
        for f in fields:
            for v in (f.get("values") or []) if isinstance(f, dict) else []:
                lbl = v.get("label") if isinstance(v, dict) else v
                if lbl:
                    options.append(str(lbl))
        out.append({
            "label": (q.get("label") or "").strip(),
            "help": (q.get("description") or None),
            "type": coarse,
            "source_type": coarse,
            "required": bool(q.get("required")),
            "name": names[0] if names else "",
            "names": names,
            "options": options,
        })
    return out


def _greenhouse_pay(job: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (normalized comp, verbatim raw) from `pay_input_ranges` (may be
    empty — then comp is genuinely not posted)."""
    ranges = job.get("pay_input_ranges") or []
    parts = []
    for r in ranges:
        if not isinstance(r, dict):
            continue
        lo, hi = r.get("min_cents"), r.get("max_cents")
        cur = r.get("currency_type") or ""
        title = (r.get("title") or "").strip()
        if lo or hi:
            def _dollars(c):
                try:
                    return f"{int(c) // 100:,}"
                except Exception:
                    return str(c)
            rng = f"{cur} {_dollars(lo)}–{_dollars(hi)}".strip() if (lo and hi) else \
                  f"{cur} {_dollars(lo or hi)}".strip()
            parts.append(f"{title}: {rng}" if title else rng)
    if not parts:
        return None, None
    joined = " · ".join(parts)
    return joined, joined


def _greenhouse_job_to_result(job: dict, board: str, company: str, url: str) -> Optional[dict]:
    """Pure Greenhouse job-object -> normalized result (unit-testable vs a saved
    boards-API fixture)."""
    raw = job.get("content") or ""
    body = _html_to_text(html.unescape(raw))
    if not body:
        return None

    loc = job.get("location") or {}
    location = loc.get("name") if isinstance(loc, dict) else (loc or None)
    offices = [o.get("name") for o in (job.get("offices") or [])
               if isinstance(o, dict) and o.get("name")]
    office_str = "; ".join(dict.fromkeys(offices)) or None

    comp, comp_raw = _greenhouse_pay(job)
    benefits, equity = mine_benefits_equity(body)
    questions = filter_questions(parse_greenhouse_questions(job))

    # Working location comes from the posting's location; an office-cadence
    # question (if any survived the filter) enriches it downstream.
    working_location = location or office_str

    return {
        "title": (job.get("title") or "").strip() or "Unknown Title",
        "company": company,
        "location": location,
        "working_location": working_location,
        "employment_type": job.get("employment_type"),
        "remote": None,
        "workplace": None,
        "compensation": comp,
        "compensation_raw": comp_raw,
        "location_raw": office_str,
        "cadence_raw": None,
        "benefits": benefits,
        "equity": equity,
        "apply_url": job.get("absolute_url") or url,
        "posting_id": str(job.get("id")) if job.get("id") else None,
        "source": "greenhouse-boards-api",
        # GH commonly omits pay even with pay_transparency=true, so an empty comp
        # is "not posted", not a capture failure.
        "comp_expected": False,
        "location_expected": True,
        "questions": questions,
        "text": body,
    }


# --------------------------------------------------------------------------- #
# Embedded-Greenhouse recovery (custom career domains backed by Greenhouse)
# --------------------------------------------------------------------------- #

# Subdomain / TLD labels that are never the Greenhouse board token itself.
_GENERIC_DOMAIN_LABELS = {
    "careers", "career", "jobs", "job", "www", "apply", "boards", "board",
    "work", "hire", "hiring", "talent", "recruiting", "join", "com", "org",
    "net", "io", "co", "ai", "app", "inc",
}

# Stopwords stripped before comparing a page title to a Greenhouse job title.
_TITLE_STOPWORDS = {
    "the", "a", "an", "of", "and", "or", "for", "to", "in", "at", "with", "on",
    "senior", "staff", "lead", "principal", "junior", "sr", "jr", "ii", "iii",
    "careers", "career", "jobs", "job", "remote", "hybrid", "onsite", "role",
    "position", "opening", "apply", "hiring",
}


def _title_tokens(text: str) -> set:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if len(w) >= 3 and w not in _TITLE_STOPWORDS}


def _titles_reasonably_match(page_title: str, gh_title: str) -> bool:
    """Do a page's title and a candidate Greenhouse job title describe the same
    role? Significant-word overlap: at least two shared tokens, or coverage of
    half the shorter title's tokens."""
    ta, tb = _title_tokens(page_title), _title_tokens(gh_title)
    if not ta or not tb:
        return False
    inter = ta & tb
    if not inter:
        return False
    shorter = min(len(ta), len(tb))
    return len(inter) >= 2 or len(inter) >= max(1, (shorter + 1) // 2)


def _title_supported_by_body(gh_title: str, body: str) -> bool:
    """A strong same-posting signal even when the page <title> is generic: the
    Greenhouse job title's significant words appear in the page body we already
    fetched (so a wrong board's unrelated job is rejected)."""
    tt = _title_tokens(gh_title)
    if not tt:
        return False
    body_tokens = set(re.findall(r"[a-z0-9]+", (body or "").lower()))
    inter = tt & body_tokens
    return len(inter) >= 2 and len(inter) >= max(1, (len(tt) + 1) // 2)


def _url_slug_title(url: str) -> str:
    """A role title guessed from the URL path slug, e.g.
    .../sr-product-manager-core-saving-experience/ -> 'sr product manager core
    saving experience'. Empty when the path has no word-slug segment."""
    best = ""
    for p in urlparse(url).path.split("/"):
        s = unquote(p)
        if not s or s.isdigit():
            continue
        if "-" in s or "_" in s:
            words = re.sub(r"[-_]+", " ", s).strip()
            if len(words) > len(best):
                best = words
    return best


def _embedded_gh_job_id(url: str, html_text: Optional[str]) -> Optional[str]:
    """A Greenhouse numeric job id from the URL path/query or the page HTML."""
    for src in (url, html_text or ""):
        m = re.search(r"gh_jid=(\d{5,})", src)
        if m:
            return m.group(1)
    ids = re.findall(r"(\d{6,})", urlparse(url).path)
    if ids:
        return max(ids, key=len)
    return None


def _gh_board_tokens_from_html(html_text: Optional[str]) -> list[str]:
    """High-confidence board tokens: an explicit greenhouse.io board reference in
    the page HTML (embed `for=`, boards URL path, or a data attribute)."""
    if not html_text:
        return []
    out: list[str] = []
    for m in re.finditer(
        r"(?:boards|job-boards|boards-api)\.greenhouse\.io/(?:embed/[^\"'?]*\?[^\"']*?\bfor=)?"
        r"([A-Za-z0-9][A-Za-z0-9_-]+)", html_text):
        tok = (m.group(1) or "").strip().lower()
        if tok and tok not in ("embed", "v1", "job_app") and tok not in out:
            out.append(tok)
    for m in re.finditer(r"[?&]for=([A-Za-z0-9][A-Za-z0-9_-]+)", html_text):
        tok = m.group(1).strip().lower()
        if tok and tok not in out:
            out.append(tok)
    return out


# Brandable suffixes glued onto a company label in a career domain, so
# `pinterestcareers.com` -> board `pinterest`, `stripe-jobs.com` -> `stripe`.
_BRAND_SUFFIXES = ("careers", "career", "jobs", "job", "hiring", "talent",
                   "people", "hr", "recruiting", "work", "hq")


def _brand_token_variants(label: str) -> list[str]:
    """A domain label plus plausible board-token variants: the label itself, a
    de-hyphenated form, and the label with a trailing brand suffix stripped."""
    out: list[str] = []
    for cand in (label, label.replace("-", "")):
        if cand and cand not in out:
            out.append(cand)
    for suf in _BRAND_SUFFIXES:
        for base in (label, label.replace("-", "")):
            if base.endswith(suf) and len(base) > len(suf) + 2:
                stripped = base[: -len(suf)].rstrip("-")
                if stripped and stripped not in out:
                    out.append(stripped)
    return out


def _gh_board_tokens_from_domain(url: str) -> list[str]:
    """Lower-confidence board-token guesses derived from the career domain, e.g.
    careers.airbnb.com -> ['airbnb']; pinterestcareers.com -> ['pinterestcareers',
    'pinterest']."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    labels = [l for l in host.split(".") if l]
    out: list[str] = []
    if len(labels) >= 2:
        for cand in _brand_token_variants(labels[-2]):
            if cand not in _GENERIC_DOMAIN_LABELS and cand not in out:
                out.append(cand)
    for l in labels:
        for cand in _brand_token_variants(l):
            if cand not in _GENERIC_DOMAIN_LABELS and cand not in out:
                out.append(cand)
    return out


def recover_embedded_greenhouse(url: str, *, page_title: Optional[str] = None,
                                body: Optional[str] = None,
                                html_text: Optional[str] = None,
                                timeout: int = 20) -> Optional[dict]:
    """Recover a Greenhouse-backed posting served under a CUSTOM career domain
    (e.g. careers.airbnb.com/positions/8044715 -> board `airbnb`, job 8044715).

    Extracts a Greenhouse numeric job id from the URL/HTML, then tries the real
    boards API with candidate board tokens (HTML-referenced first, then domain
    guesses). SAFETY: a domain-guessed token is accepted only when the returned
    job title reasonably matches the page title we already have, or its title
    words appear in the page body — guarding against a wrong board that merely
    happens to have a job with the same numeric id. Returns the normalized
    ATS-result dict (with 'text') or None.
    """
    if requests is None:
        return None
    host = urlparse(url).netloc.lower().replace("www.", "")
    host_guess = host.split(".")[-2] if "." in host else host
    # Known ATS hosts are already handled by fetch_via_ats — don't double-dip.
    if host_guess in ATS_HOST_KEYWORDS:
        return None
    job_id = _embedded_gh_job_id(url, html_text)
    if not job_id:
        return None

    html_tokens = _gh_board_tokens_from_html(html_text)
    candidates = html_tokens + [t for t in _gh_board_tokens_from_domain(url) if t not in html_tokens]
    for token in candidates:
        try:
            resp = requests.get(
                f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}",
                params={"questions": "true", "pay_transparency": "true"},
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=timeout,
            )
        except Exception:
            continue
        if resp.status_code != 200:
            continue
        try:
            job = resp.json()
        except Exception:
            continue
        company = _greenhouse_company(token, timeout) or _prettify_slug(token)
        result = _greenhouse_job_to_result(job, token, company, url)
        if not result:
            continue
        gh_title = result.get("title") or ""
        high_conf = token in html_tokens
        slug_title = _url_slug_title(url)
        if not high_conf and not (
            _titles_reasonably_match(page_title or "", gh_title)
            or _titles_reasonably_match(slug_title, gh_title)
            or _title_supported_by_body(gh_title, body or "")
        ):
            # A domain-guessed board returned SOME job — but not the one on the page.
            continue
        result["source"] = "greenhouse-boards-api (embedded recovery)"
        result["recovered_via"] = f"greenhouse:{token}:{job_id}"
        result["structured_source"] = True
        return result
    return None


# --------------------------------------------------------------------------- #
# Lever
# --------------------------------------------------------------------------- #

def _lever_ids(url: str):
    """Return (company, posting_id) for a Lever URL: jobs.lever.co/{company}/{uuid}[/apply][?...]."""
    parsed = urlparse(url)
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if not parts:
        return None, None
    company = parts[0]
    posting_id = None
    for p in parts[1:]:
        if UUID_RE.fullmatch(p):
            posting_id = p.lower()
            break
    if posting_id is None:
        m = UUID_RE.search(url)
        posting_id = m.group(0).lower() if m else None
    return company, posting_id


def _fetch_lever(url: str, timeout: int = 20) -> Optional[dict]:
    """Fetch a Lever job posting from its public per-posting JSON endpoint:
    https://api.lever.co/v0/postings/{company}/{postingId}?mode=json
    """
    company_slug, posting_id = _lever_ids(url)
    if not company_slug or not posting_id:
        return None

    resp = requests.get(
        f"https://api.lever.co/v0/postings/{company_slug}/{posting_id}",
        params={"mode": "json"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        return None
    job = resp.json()
    if not isinstance(job, dict):
        return None

    cats = job.get("categories") or {}
    location = cats.get("location")
    employment_type = cats.get("commitment")
    workplace = job.get("workplaceType")  # "remote" / "on-site" / "hybrid" when present
    all_locations = cats.get("allLocations") if isinstance(cats.get("allLocations"), list) else None

    body_html = "\n".join(
        part for part in [job.get("descriptionPlain"), job.get("description")] if part
    ) if not job.get("lists") else None
    # Lever splits the body into a top description + labeled "lists" (Responsibilities, etc).
    parts_html = [job.get("description") or ""]
    for section in (job.get("lists") or []):
        text = section.get("text") or ""
        content = section.get("content") or ""
        parts_html.append(f"{text}\n{content}")
    if job.get("additional"):
        parts_html.append(job["additional"])
    body = _html_to_text("\n".join(p for p in parts_html if p)) or (body_html or "")
    if not body:
        return None

    comp = None
    salary = job.get("salaryRange") or job.get("compensation")
    if isinstance(salary, dict):
        lo, hi, cur = salary.get("min"), salary.get("max"), salary.get("currency") or ""
        if lo or hi:
            comp = f"{cur} {lo or ''}-{hi or ''}".strip()
    elif isinstance(salary, str):
        comp = salary

    company = _prettify_slug(company_slug)
    working_location = "; ".join(dict.fromkeys([l for l in (all_locations or [location]) if l])) or None
    benefits, equity = mine_benefits_equity(body)

    return {
        "title": (job.get("text") or "").strip() or "Unknown Title",
        "company": company,
        "location": location,
        "working_location": working_location,
        "employment_type": employment_type,
        "remote": (workplace or "").lower() == "remote" if workplace else None,
        "workplace": workplace.title() if isinstance(workplace, str) else None,
        "compensation": comp,
        "compensation_raw": comp,
        "location_raw": working_location,
        "cadence_raw": None,
        "benefits": benefits,
        "equity": equity,
        "apply_url": job.get("applyUrl") or job.get("hostedUrl") or url,
        "posting_id": posting_id,
        "source": "lever-postings-api",
        "comp_expected": False,
        "location_expected": bool(location or working_location),
        "questions": [],
        "text": body,
    }


# --------------------------------------------------------------------------- #
# Generic JSON-LD JobPosting (schema.org) — for non-ATS company career sites.
# Safe because it's the page's own structured data for THIS job, never a sibling/
# related-jobs sidebar (unlike a raw text search for a city name, which can pick up
# an unrelated posting listed elsewhere on the page).
# --------------------------------------------------------------------------- #

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S
)


def extract_jsonld_jobposting(html: str) -> Optional[dict]:
    """Scan <script type="application/ld+json"> blocks for a schema.org JobPosting and
    return {"location": str|None, "employment_type": str|None, "compensation": str|None},
    or None if no JobPosting block is found. Handles a bare object, an @graph array, or a
    top-level JSON array of blocks."""
    import json as _json

    for raw in _JSONLD_RE.findall(html or ""):
        try:
            data = _json.loads(html.unescape(raw.strip()))
        except Exception:
            continue
        candidates = data if isinstance(data, list) else [data]
        for c in candidates:
            if isinstance(c, dict) and isinstance(c.get("@graph"), list):
                candidates = candidates + c["@graph"]
        for node in candidates:
            if not isinstance(node, dict):
                continue
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if not any(str(t).lower() == "jobposting" for t in types if t):
                continue
            location = _jsonld_location(node.get("jobLocation"))
            employment_type = node.get("employmentType")
            if isinstance(employment_type, list):
                employment_type = ", ".join(str(e) for e in employment_type)
            comp = _jsonld_compensation(node.get("baseSalary"))
            if location or employment_type or comp:
                return {"location": location, "employment_type": employment_type, "compensation": comp}
    return None


def _jsonld_location(job_location) -> Optional[str]:
    nodes = job_location if isinstance(job_location, list) else [job_location]
    parts = []
    for n in nodes:
        if not isinstance(n, dict):
            continue
        addr = n.get("address") or {}
        if isinstance(addr, dict):
            locality = addr.get("addressLocality")
            region = addr.get("addressRegion")
            piece = ", ".join(p for p in [locality, region] if p)
            if piece:
                parts.append(piece)
    if parts:
        return "; ".join(dict.fromkeys(parts))  # dedupe, preserve order
    # applicantLocationRequirements (remote postings sometimes use this instead)
    return None


def _jsonld_compensation(base_salary) -> Optional[str]:
    if not isinstance(base_salary, dict):
        return None
    val = base_salary.get("value") or {}
    if not isinstance(val, dict):
        return None
    lo, hi, unit = val.get("minValue"), val.get("maxValue"), val.get("unitText") or ""
    currency = base_salary.get("currency") or ""
    if lo or hi:
        rng = f"{lo or ''}-{hi or ''}".strip("-")
        return f"{currency} {rng} {unit}".strip()
    return None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

# Host keywords that are ATS platforms, NOT the hiring company. For these, the real
# company is the org slug in the URL path (or ?for=), never the host. This stops
# "Greenhouse", "Lever", etc. from being written as the company on the HTML-fallback path.
ATS_HOST_KEYWORDS = {
    "greenhouse", "lever", "ashbyhq", "myworkdayjobs", "workday", "icims",
    "smartrecruiters", "bamboohr", "jobvite", "rippling", "breezy", "workable",
}


def ats_company_from_url(url: str) -> Optional[str]:
    """If the URL host is a known ATS, return the hiring company derived from the org
    slug in the path (or ?for=), prettified. Returns None for non-ATS hosts so callers
    keep their normal company detection."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    host_parts = host.split(".")
    host_guess = host_parts[-2] if len(host_parts) >= 2 else host
    if host_guess not in ATS_HOST_KEYWORDS:
        return None
    skip = {"embed", "job_app", "jobs", "job", "o", "careers", "career", "apply"}
    path_parts = [unquote(p) for p in parsed.path.split("/") if p]
    slug = next((s for s in path_parts if s.lower() not in skip), None)
    if not slug:
        slug = (parse_qs(parsed.query).get("for") or [None])[0]
    return _prettify_slug(slug) if slug else None


def _prettify_slug(slug: str) -> str:
    s = re.sub(r"[-_]+", " ", slug).strip()
    # Title-case but keep existing capitalization for already-cased words.
    return " ".join(w if w[:1].isupper() else w.capitalize() for w in s.split()) or slug


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    except Exception:
        # Crude tag strip if bs4 is unavailable.
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
