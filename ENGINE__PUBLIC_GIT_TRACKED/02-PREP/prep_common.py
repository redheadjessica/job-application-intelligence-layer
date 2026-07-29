#!/usr/bin/env python3
"""Shared prep-reliability helpers used by both fetchers.

One place for: URL normalization + dedupe keys, collision-safe filenames,
thin/failed classification, the per-batch quarantine layout, manifest read/
write/merge, and the human-readable prep report. Both prep_job_urls.py
(requests) and prep_job_urls_playwright.py (render) call process_urls() with a
script-specific `fetch_one` callback so the dedupe / classify / quarantine /
manifest logic lives here, not duplicated.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from ats_fetchers import (
    ATS_HOST_KEYWORDS,
    UUID_RE,
    _greenhouse_ids,
    _linkedin_job_id,
    parse_office_cadence,
    question_provides_employer_comp,
    question_provides_working_location,
    recover_embedded_greenhouse,
)

# --------------------------------------------------------------------------- #
# Per-field completeness vocabulary (comp + working-location gate before ranking)
# --------------------------------------------------------------------------- #
FOUND = "found"
NOT_POSTED = "not_posted"
CAPTURE_FAILED = "capture_failed"
CONFLICTING = "conflicting"
# Hard fields that gate ranking quality (never a reason to quarantine, though).
HARD_FIELDS = ("compensation", "working_location")

# --------------------------------------------------------------------------- #
# Status vocabulary (kept stable so the manifest is a contract ranking can read)
# --------------------------------------------------------------------------- #
USABLE = "usable"
THIN = "thin"
FAILED = "failed"
DUPLICATE = "duplicate"
NEEDS_REVIEW = "needs-review"

# A job-text body shorter than this is quarantined as "thin". Tunable.
THIN_CHAR_THRESHOLD = 700

# Query params that are tracking/noise and safe to drop for the dedupe key.
# (utm_* is handled by prefix; these are exact-match.)
_TRACKING_PARAMS = {
    "gh_src", "gh_jid", "ref", "referrer", "source", "src", "trk", "trackingid",
    "lipi", "refid", "lici", "recommended", "spreadsheet", "fbclid", "gclid",
    "mc_cid", "mc_eid", "campaign", "medium",
}

# Signals a page is a login/apply shell, not the actual posting.
_SHELL_MARKERS = (
    "sign in", "log in to apply", "create an account", "please enable javascript",
    "enable javascript", "you need to enable", "verify you are human", "captcha",
)
# Signals real job content (any one is enough to look like a posting).
_CONTENT_MARKERS = (
    "responsib", "requirement", "qualificat", "what you", "about the role",
    "about the job", "you'll", "you will", "experience", "we're looking",
    "what we", "the role", "responsibilities",
)


# --------------------------------------------------------------------------- #
# Slug + filenames
# --------------------------------------------------------------------------- #
# Double-quote-like characters that a verbatim question label sometimes carries
# on one or both ends. We wrap the label in our own quotes when emitting it, so a
# stray one doubles up (e.g. `…delivery?""`). Strip only these wrapping quotes;
# apostrophes and quotes *inside* the label are left untouched.
_WRAP_QUOTES = "\"“”„‟"


def _strip_wrapping_quotes(text: str) -> str:
    """Trim stray leading/trailing double-quote characters so a verbatim label
    doesn't render a doubled quote when we wrap it in our own."""
    return (text or "").strip().strip(_WRAP_QUOTES).strip()


def slugify(text: str, max_len: int = 80) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text[:max_len] or "job"


def first_line(title: str) -> str:
    return (title or "").split("|")[0].split(" - ")[0].strip()


def base_filename(company: str, title: str) -> str:
    return f"{slugify(company)}__{slugify(first_line(title))}.txt"


def _short_hash(s: str) -> str:
    return hashlib.sha1((s or "").encode("utf-8")).hexdigest()[:6]


def source_token(url: str) -> str | None:
    """Return the ATS platform name (greenhouse/lever/ashby/linkedin/...) if the
    host is a known ATS — used as a friendly collision suffix. None otherwise."""
    host = urlparse(url).netloc.lower().replace("www.", "")
    parts = host.split(".")
    guess = parts[-2] if len(parts) >= 2 else host
    return guess if guess in ATS_HOST_KEYWORDS else None


def unique_filename(company: str, title: str, normalized_url: str,
                    taken: dict[str, str], url: str) -> str:
    """Collision-safe, deterministic filename. Base is `{company}__{title}.txt`.
    If that base is already taken by a DIFFERENT normalized URL, append a stable
    suffix: the ATS source token when available, else a short hash of the
    normalized URL. Re-fetching the SAME url yields the SAME name (retry-safe).
    `taken` maps already-used filename -> the normalized_url that owns it."""
    base = base_filename(company, title)
    if taken.get(base) in (None, normalized_url):
        return base
    suffix = source_token(url) or _short_hash(normalized_url)
    return f"{base[:-4]}-{suffix}.txt"


def failed_filename(url: str, normalized_url: str) -> str:
    host = urlparse(url).netloc.lower().replace("www.", "") or "unknown"
    return f"{slugify(host)}__failed-{_short_hash(normalized_url)}.txt"


# --------------------------------------------------------------------------- #
# URL normalization (conservative — only strip KNOWN noise; never merge unsure)
# --------------------------------------------------------------------------- #
def _lever_id(url: str):
    parts = [p for p in urlparse(url).path.split("/") if p]
    if not parts:
        return None, None
    org = parts[0]
    for p in parts[1:]:
        if UUID_RE.fullmatch(p):
            return org, p.lower()
    m = UUID_RE.search(url)
    return (org, m.group(0).lower()) if m else (org, None)


def ats_canonical_key(url: str) -> str | None:
    """A stable canonical id for a known ATS job, so two URL forms of the same
    posting collapse to one dedupe key. None if not a recognized ATS job."""
    host = urlparse(url).netloc.lower()
    try:
        if host.endswith("ashbyhq.com"):
            parts = [p for p in urlparse(url).path.split("/") if p]
            org = parts[0] if parts else None
            m = UUID_RE.search(url)
            if org and m:
                return f"ashby:{org.lower()}:{m.group(0).lower()}"
        if host.endswith("greenhouse.io"):
            board, jid = _greenhouse_ids(url)
            if board and jid:
                return f"greenhouse:{board.lower()}:{jid}"
        if "lever.co" in host:
            org, lid = _lever_id(url)
            if org and lid:
                return f"lever:{org.lower()}:{lid}"
        if "linkedin.com" in host:
            jid = _linkedin_job_id(url)
            if jid:
                return f"linkedin:{jid}"
    except Exception:
        return None
    return None


def _is_tracking(key: str) -> bool:
    k = key.lower()
    return k.startswith("utm_") or k in _TRACKING_PARAMS


def normalize_url(url: str) -> str:
    """Canonical dedupe key. Prefer a known-ATS job id; otherwise a conservative
    generic normalization (lowercase host, drop www/fragment/trailing-slash,
    strip known tracking params, sort the rest). Unknown params are KEPT — they
    might distinguish two real jobs."""
    url = (url or "").strip()
    key = ats_canonical_key(url)
    if key:
        return key
    p = urlparse(url)
    scheme = (p.scheme or "https").lower()
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    q = parse_qs(p.query, keep_blank_values=True)
    kept = [(k, v) for k, vals in q.items() if not _is_tracking(k) for v in vals]
    query = urlencode(sorted(kept))
    path = p.path.rstrip("/") or "/"
    return urlunparse((scheme, host, path, "", query, ""))


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #
def classify(body: str, *, is_ats: bool = False) -> tuple[str, str]:
    """Return (status, reason). USABLE / THIN / FAILED based on the extracted
    job-text body. ATS API results are trusted unless empty.

    BUG FIX (2026-07-16): the content-marker check used to only apply when the body was
    short (< THIN_CHAR_THRESHOLD * 2). A long body with ZERO job-posting content markers —
    e.g. a JS-rendered SPA whose raw HTML is mostly theme/config JSON, not the rendered job
    text — sailed through as USABLE purely because it was long. This is exactly how a
    488KB Microsoft careers-site boilerplate capture got scored as a real job (it wasn't).
    The has_content check now applies unconditionally: length alone never substitutes for
    actual job-posting content."""
    b = (body or "").strip()
    n = len(b)
    if n == 0:
        return FAILED, "empty body"
    low = b.lower()
    has_content = any(m in low for m in _CONTENT_MARKERS)
    is_shell = any(m in low for m in _SHELL_MARKERS)
    if is_ats:
        return (USABLE, "") if n > 0 else (FAILED, "empty body")
    if is_shell and not has_content:
        return THIN, "looks like a login/apply shell (no job content)"
    if n < THIN_CHAR_THRESHOLD:
        return THIN, f"short body ({n} chars, under {THIN_CHAR_THRESHOLD})"
    if not has_content:
        return THIN, (f"no job-posting content markers found (responsibilities/qualifications/"
                       f"about the role/etc.) despite {n} chars — likely boilerplate, theme "
                       f"config, or nav chrome rather than the actual posting text")
    return USABLE, ""


# --------------------------------------------------------------------------- #
# Completeness gate (compensation + working location) — runs BEFORE ranking
# --------------------------------------------------------------------------- #
def _norm_val(v) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


def _distinct(values) -> list:
    seen, out = set(), []
    for v in values:
        if not v:
            continue
        k = _norm_val(v)
        if k and k not in seen:
            seen.add(k)
            out.append(str(v).strip())
    return out


# A plain HTML scrape (requests or a rendered page with no JSON-LD JobPosting) is
# NOT a structured source: a field missing from it is "could not verify"
# (capture_failed), never "not posted", because the real ATS API or a render
# routinely surfaces fields a plain scrape misses. Only a structured source (an
# ATS API, or a JSON-LD JobPosting) can testify that a field is genuinely absent.
_GENERIC_SOURCES = {"requests/html", "playwright/html"}


def _source_is_structured(meta: dict) -> bool:
    """True when a STRUCTURED source (ATS API or JSON-LD JobPosting) was
    successfully consulted for this posting. A genuinely-absent field is only
    trustworthy as `not_posted` from such a source; a bare generic HTML scrape
    yields `capture_failed` instead. An explicit meta['structured_source'] flag
    wins; otherwise anything not tagged as a generic HTML source is treated as
    structured (covers the ATS result dicts, which name themselves e.g.
    'greenhouse-boards-api')."""
    flag = meta.get("structured_source")
    if flag is not None:
        return bool(flag)
    return (meta.get("source") or "").strip().lower() not in _GENERIC_SOURCES


# --------------------------------------------------------------------------- #
# Prose fallback — the completeness verdict must match what the vetting scorer can
# actually read. The scorer reads the job-description BODY, so before we call a
# field capture_failed we scan that same prose: employers routinely write the pay
# range and the location into the JD text even when no structured field carries it.
# --------------------------------------------------------------------------- #

# A monetary amount: a comma-thousands number (240,000), a K-scaled number (180K),
# or a plain 4-7 digit number (240000). Plain small integers like "20" never match,
# so "10-20 people" can't be read as pay; the plain-digit form additionally requires
# a currency marker at match time (below) so ids/years don't false-positive.
_CUR = r"USD|US\$|CAD|C\$|A\$|AUD|EUR|GBP|\$|£|€"
_AMT = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{2,3}(?:\.\d+)?\s?[kK]|\d{4,7}(?:\.\d{2})?"
_PAY_RANGE_RE = re.compile(
    rf"(?P<cur1>{_CUR})?\s?"
    rf"(?P<lo>{_AMT})"
    rf"\s?(?:-|–|—|to|through)\s?"
    rf"(?P<cur2>{_CUR})?\s?"
    rf"(?P<hi>{_AMT})",
    re.I,
)
_SALARY_KEYWORDS = (
    "salary", "compensation", "pay range", "pay for", "base pay", "base salary",
    "annual", "annually", "per year", "/year", "/yr", "a year", "ote",
    "total comp", "target cash", "range for this", "hiring range", "wage",
)


def _prose_compensation(body: str) -> str | None:
    """Best-effort employer pay figure written into the JD prose. Returns a cleaned
    range string, or None. Requires a currency marker OR a nearby salary keyword so
    non-salary numeric ranges don't false-positive."""
    if not body:
        return None
    text = re.sub(r"\s+", " ", body)
    low = text.lower()
    for m in _PAY_RANGE_RE.finditer(text):
        lo, hi = m.group("lo"), m.group("hi")
        has_cur = bool(m.group("cur1") or m.group("cur2"))
        has_comma_or_k = any(("," in x or "k" in x.lower()) for x in (lo, hi))
        window = low[max(0, m.start() - 90): m.start()]
        after = low[m.end(): m.end() + 25]
        has_kw = (any(k in window for k in _SALARY_KEYWORDS)
                  or any(k in after for k in ("per year", "annually", "/yr", "/year",
                                              "a year", "base", "salary")))
        # A currency marker is enough; a comma/K-scaled figure needs a salary keyword;
        # a bare plain-digit range (240000-334000) needs an explicit currency so ids
        # and year ranges can't masquerade as pay.
        if has_cur or (has_comma_or_k and has_kw):
            return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


# US state abbreviations, to keep the "City, ST" prose pattern from matching noise.
_US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}
# Inter-word separator is [ \t], NOT \s: \s matches newlines, which let a city glue
# onto the trailing token of the PREVIOUS line across a break ("Google Cloud\nAustin,
# TX" -> captured as one city). Keeping it on a single line fixes that (2026-07-29 audit).
_CITY_STATE_RE = re.compile(r"\b([A-Z][A-Za-z.\-]+(?:[ \t][A-Z][A-Za-z.\-]+){0,2}),[ \t]*([A-Z]{2})\b")
_REMOTE_RE = re.compile(
    r"(?i)\b(fully[- ]remote|remote[- ]first|remote[- ]friendly|100%\s*remote|"
    r"work from (home|anywhere)|this (role|position) is remote|remote position|"
    r"remote role|remote,|remote \(|open to remote)\b")
_CADENCE_RE = re.compile(
    r"(?i)\b(hybrid|on-?site|in-?office|in the office|in[- ]person|"
    r"\d\s*days?\s*(?:per|a)\s*week|days?\s*(?:per|a)\s*week in|relocate to)\b")
# The keyword group is \b-terminated so a plural nav label ("Locations" / "Office
# locations") does NOT match "location" and leak its trailing "s" as the value — the
# 2026-07-29 completeness audit caught exactly this (4 jobs green-lit with
# working-location = "s"). A separator stays optional so "Location New York" still works.
_LOC_LABEL_RE = re.compile(
    r"(?im)^\s*(?:office location|work location|location|based in)\b\s*[:\-–]?\s*(.+)$")

# A trailing marketing sentence or markdown-link/URL after the real place, captured by
# a naive prose grab (e.g. Rippling: "San Francisco, CA, [Rippling has raised ...](url) …").
_LOC_TRAILING_JUNK_RE = re.compile(r"\s*(?:\[|\(|https?://|www\.).*$", re.S)
# Bare nav/label tokens that must never count as a location on their own.
_LOC_NAV_BLOCKLIST = {"locations", "location", "careers", "apply", "menu", "jobs", "home", "s"}


def _sanitize_location(val: str | None) -> str | None:
    """Clean a raw prose location candidate and confirm it actually looks like a
    location before the completeness gate is allowed to call working-location `found`.
    Returns a short trustworthy snippet, or None (-> capture_failed downstream).

    Handles the failure modes the 2026-07-29 audit surfaced:
      "Google Cloud\\nAustin, TX" -> "Austin, TX"      (division prefix / multiline)
      "Product\\nMenlo Park, CA"  -> "Menlo Park, CA"
      "San Francisco, CA, [Rippling has raised ...](url) …" -> "San Francisco, CA"
      "s" / "Locations"          -> None              (nav-label leak)
    """
    if not val:
        return None
    # Multiline: keep the single most location-like line (City,ST > remote/cadence).
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", val) if ln.strip()]
    if lines:
        lines.sort(key=lambda ln: (
            2 if _CITY_STATE_RE.search(ln) else 1 if (_REMOTE_RE.search(ln) or _CADENCE_RE.search(ln)) else 0),
            reverse=True)
        val = lines[0]
    # A real "City, ST" anywhere wins — drops any division prefix or trailing marketing.
    cm = _CITY_STATE_RE.search(val)
    if cm and cm.group(2) in _US_STATES:
        return f"{cm.group(1)}, {cm.group(2)}"
    # Otherwise cut a trailing URL / markdown link / parenthetical marketing tail.
    val = _LOC_TRAILING_JUNK_RE.sub("", val).strip(" ,;:·—–-\t").strip()
    if len(val) < 3 or val.lower() in _LOC_NAV_BLOCKLIST:
        return None
    # Trust it if it carries a real workplace signal (Remote/hybrid/onsite/cadence),
    # or reads as a compact "City, Region" phrase (US or international). A longer
    # free-text clause with no such signal is prose, not a location.
    if _REMOTE_RE.search(val) or _CADENCE_RE.search(val):
        return val[:120]
    if "," in val and len(val.split()) <= 6 and re.match(r"^[A-Z][\w.\-]+", val):
        return val[:120]
    return None


def _prose_working_location(body: str) -> str | None:
    """Best-effort job location/cadence written into the JD prose: a "City, ST",
    a Remote/hybrid/onsite signal, or an explicit Location: line. Returns a short,
    validated snippet, or None. Every candidate is run through _sanitize_location so a
    nav-label leak ("Locations" -> "s") or a marketing tail never counts as found."""
    if not body:
        return None
    m = _LOC_LABEL_RE.search(body)
    if m and m.group(1).strip():
        cleaned = _sanitize_location(m.group(1))
        if cleaned:
            return cleaned
    m = _REMOTE_RE.search(body)
    if m:
        return m.group(0).strip().rstrip(",(").strip().title()
    for cm in _CITY_STATE_RE.finditer(body):
        if cm.group(2) in _US_STATES:
            return f"{cm.group(1)}, {cm.group(2)}"
    m = _CADENCE_RE.search(body)
    if m:
        return m.group(0).strip()
    return None


def assess_completeness(meta: dict | None, body: str, questions: list | None) -> dict:
    """Per-field capture status for the ranking gate. Each of compensation and
    working-location (plus title/description presence) is exactly one of:
    `found` / `not_posted` / `capture_failed` / `conflicting`.

    Rules (PII-free; candidate-relative interpretation happens later at vetting):
      - Employer compensation must be a real employer figure. A candidate
        "compensation expectations?" question does NOT satisfy it (such questions
        are already dropped by the filter and never reach here).
      - Working location must be the JOB's location/cadence. "Where do you live?"
        does NOT satisfy it; an office-attendance question DOES (and supplies the
        cadence). Two disagreeing sources -> `conflicting` (keep both, flagged).
    """
    meta = meta or {}
    questions = questions or []
    fs: dict = {"conflicts": []}

    title = (meta.get("title") or "").strip()
    fs["title"] = FOUND if title and title != "Unknown Title" else CAPTURE_FAILED
    fs["description"] = FOUND if (body or "").strip() else CAPTURE_FAILED

    # ---- compensation ----
    comp_sources = _distinct([s for _, s in (meta.get("compensation_sources") or [])] or [meta.get("compensation")])
    comp_from_q = any(question_provides_employer_comp(q) for q in questions)
    comp_prose = _prose_compensation(body)
    if len(comp_sources) >= 2:
        fs["compensation"] = CONFLICTING
        fs["conflicts"].append(f"compensation: {' vs '.join(comp_sources[:2])}")
    elif meta.get("compensation") or comp_from_q:
        fs["compensation"] = FOUND
    elif comp_prose:
        # The scorer reads the JD body; comp is written into the prose even though no
        # structured field carried it. This IS found — not a capture failure.
        fs["compensation"] = FOUND
        fs["compensation_source"] = "description"
        fs["compensation_prose"] = comp_prose
    elif meta.get("comp_expected"):
        # A structured source expected comp but it came back empty -> capture failure.
        fs["compensation"] = CAPTURE_FAILED
    elif _source_is_structured(meta):
        # A structured source was consulted and comp is genuinely absent (e.g.
        # Greenhouse pay_transparency with empty pay_input_ranges, Ashby
        # shouldDisplayCompensationOnJobPostings=false, JSON-LD with no salary).
        fs["compensation"] = NOT_POSTED
    else:
        # A bare generic HTML scrape: a missing figure is could-not-verify, not
        # proof the employer didn't publish (this is the field-driven retry trigger).
        fs["compensation"] = CAPTURE_FAILED

    # ---- working location ----
    loc_sources = _distinct([s for _, s in (meta.get("location_sources") or [])]
                            or [meta.get("working_location") or meta.get("location")])
    office_q = any(question_provides_working_location(q) for q in questions)
    loc_prose = _prose_working_location(body)
    if len(loc_sources) >= 2:
        fs["working_location"] = CONFLICTING
        fs["conflicts"].append(f"working-location: {' vs '.join(loc_sources[:2])}")
    elif meta.get("working_location") or meta.get("location") or office_q:
        fs["working_location"] = FOUND
    elif loc_prose:
        # Location written into the JD prose (a named city / Remote / cadence) — the
        # scorer can read it, so it is found, not a capture failure.
        fs["working_location"] = FOUND
        fs["working_location_source"] = "description"
        fs["working_location_prose"] = loc_prose
    elif meta.get("location_expected"):
        # A structured source expected a location but it came back empty.
        fs["working_location"] = CAPTURE_FAILED
    elif _source_is_structured(meta):
        # Structured source consulted; location genuinely absent.
        fs["working_location"] = NOT_POSTED
    else:
        # Generic scrape: missing location is could-not-verify (retry trigger).
        fs["working_location"] = CAPTURE_FAILED

    return fs


def missing_hard_fields(field_status: dict | None) -> list[str]:
    """Hard fields whose capture actually failed (a retry might help). `not_posted`
    and `conflicting` are NOT retryable-missing — the employer just didn't publish,
    or we already have two readings."""
    fs = field_status or {}
    return [f for f in HARD_FIELDS if fs.get(f) == CAPTURE_FAILED]


# --------------------------------------------------------------------------- #
# Output text + quarantine stubs
# --------------------------------------------------------------------------- #
_STATUS_LABEL = {
    FOUND: "found", NOT_POSTED: "not posted", CAPTURE_FAILED: "capture failed",
    CONFLICTING: "conflicting",
}


def _apply_office_cadence(meta: dict, questions: list) -> tuple[str | None, str | None]:
    """If a kept question carries an office-attendance requirement, fold its full
    eligible-metro list + cadence into the working-location string (verbatim; no
    candidate-city mapping — vetting does that from jail.config.json)."""
    working = meta.get("working_location") or meta.get("location")
    cadence_raw = meta.get("cadence_raw")
    for q in questions or []:
        parsed = parse_office_cadence(q)
        if not parsed:
            continue
        metros = parsed.get("metros") or []
        cadence = parsed.get("cadence")
        if metros:
            metro_str = "; ".join(metros)
            working = f"{working}; {metro_str}" if working else metro_str
            # Dedupe while preserving order.
            working = "; ".join(dict.fromkeys(p.strip() for p in working.split(";") if p.strip()))
        if cadence:
            working = f"{working} — {cadence}" if working else cadence
        cadence_raw = cadence_raw or parsed.get("verbatim")
    return working, cadence_raw


def build_output_text(url: str, title: str, company: str, body_text: str, *,
                      meta: dict | None = None, questions: list | None = None,
                      field_status: dict | None = None, methods_tried: list | None = None,
                      captured: str | None = None) -> str:
    """Dual-preservation layout: a provenance line, a NORMALIZED block (for
    vetting) with per-field statuses + a completeness line + optional conflicts,
    an APPLICATION QUESTIONS block (kept questions only, verbatim), a verbatim
    EMPLOYER-PROVIDED SOURCE block, then the full job text between the stable
    START/END markers. Parseable and stable (golden-file tested)."""
    meta = meta or {}
    questions = questions if questions is not None else (meta.get("questions") or [])
    fs = field_status or assess_completeness(meta, body_text, questions)

    apply_url = meta.get("apply_url") or "n/a"
    source = meta.get("source") or "requests/html"
    posting_id = meta.get("posting_id") or "n/a"
    methods = ", ".join(dict.fromkeys(methods_tried or [])) or (meta.get("method") or source)
    captured = captured or datetime.now(timezone.utc).date().isoformat()

    workplace = meta.get("workplace") or ("Remote" if meta.get("remote") else None)
    working_location, cadence_raw = _apply_office_cadence(meta, questions)
    compensation = meta.get("compensation")
    benefits = meta.get("benefits")
    equity = meta.get("equity")

    # When a field was found only in the JD prose (no structured value), surface that
    # prose figure on the line and mark it "(from description)" so the value shown
    # matches the found status and what the scorer reads.
    comp_from_prose = not compensation and fs.get("compensation_source") == "description"
    if comp_from_prose:
        compensation = fs.get("compensation_prose")
    loc_from_prose = not working_location and fs.get("working_location_source") == "description"
    if loc_from_prose:
        working_location = fs.get("working_location_prose")

    def _stat(field: str) -> str:
        return f"[{_STATUS_LABEL.get(fs.get(field), 'unknown')}]"

    def _val(v, status_field, from_prose=False):
        if v:
            return f"{v} (from description)" if from_prose else str(v)
        st = fs.get(status_field)
        return "Not posted" if st == NOT_POSTED else ("Could not verify" if st == CAPTURE_FAILED else "n/a")

    lines: list[str] = []
    lines.append(f"URL: {url}")
    lines.append(f"Application URL: {apply_url}")
    lines.append(f"Company: {company}")
    lines.append(f"Role: {title}")
    lines.append(f"Source: {source} · Posting ID: {posting_id} · Captured: {captured} · Methods tried: {methods}")
    lines.append("")
    lines.append("== NORMALIZED (for vetting) ==")
    lines.append(f"Employment Type: {meta.get('employment_type') or 'n/a'}")
    lines.append(f"Workplace: {workplace or 'n/a'}")
    lines.append(f"Working Location: {_val(working_location, 'working_location', loc_from_prose)}   {_stat('working_location')}")
    lines.append(f"Compensation: {_val(compensation, 'compensation', comp_from_prose)}   {_stat('compensation')}")
    lines.append(f"Benefits: {benefits or 'Not posted'}")
    lines.append(f"Equity: {equity or 'Not posted'}")
    lines.append(
        f"Completeness: title {'✓' if fs.get('title') == FOUND else '✗'} · "
        f"description {'✓' if fs.get('description') == FOUND else '✗'} · "
        f"compensation {_STATUS_LABEL.get(fs.get('compensation'), 'unknown')} · "
        f"working-location {_STATUS_LABEL.get(fs.get('working_location'), 'unknown')}"
    )
    for c in (fs.get("conflicts") or []):
        lines.append(f"[CONFLICT]: {c}")
    lines.append("")
    lines.append("== APPLICATION QUESTIONS (thoughtful / job-material only) ==")
    if questions:
        for i, q in enumerate(questions, 1):
            req = "required" if q.get("required") else "optional"
            qtype = q.get("source_type") or q.get("type") or "text"
            help_txt = f" — {q['help']}" if q.get("help") else ""
            opts = q.get("options") or []
            opt_str = "  (options: " + " / ".join(f'"{o}"' for o in opts) + ")" if opts else ""
            label = _strip_wrapping_quotes(q.get("label", "").strip())
            lines.append(f'{i}. [{qtype}, {req}] "{label}"{help_txt}{opt_str}')
    else:
        lines.append("(none kept)")
    lines.append("")
    lines.append("== EMPLOYER-PROVIDED SOURCE (verbatim; the durable archive) ==")
    lines.append(f'Compensation (verbatim): "{meta.get("compensation_raw") or ""}"')
    lines.append(f'Locations/Addresses (verbatim): "{meta.get("location_raw") or ""}"')
    lines.append(f'Office cadence (verbatim): "{cadence_raw or ""}"')
    lines.append("")
    lines.append("--- JOB TEXT START ---")
    lines.append("")
    lines.append(body_text)
    lines.append("")
    lines.append("--- JOB TEXT END ---")
    return "\n".join(lines) + "\n"


def thin_text(url: str, title: str, company: str, body_text: str, reason: str, ts: str,
              *, meta: dict | None = None, questions: list | None = None,
              field_status: dict | None = None, methods_tried: list | None = None) -> str:
    return (
        f"# QUARANTINED — THIN FETCH (needs your review)\n"
        f"# Reason: {reason}\n"
        f"# Fetched: {ts}\n"
        f"# What to do: open this, confirm it's the real job post. If it's incomplete,\n"
        f"#   paste the full job text below the marker, then re-run prep (it will pick it up),\n"
        f"#   OR move this file into 'All Job Posts (full text)/' if it's actually fine.\n\n"
        + build_output_text(url, title, company, body_text, meta=meta, questions=questions,
                            field_status=field_status, methods_tried=methods_tried)
    )


def failed_text(url: str, error: str, ts: str) -> str:
    return (
        f"# FAILED FETCH (no usable content)\n"
        f"# URL: {url}\n"
        f"# Error: {error}\n"
        f"# Fetched: {ts}\n"
        f"# What to do: re-run prep to retry this URL, or paste the full job text below\n"
        f"#   the marker and move this file into 'All Job Posts (full text)/'.\n\n"
        f"--- JOB TEXT START ---\n\n\n--- JOB TEXT END ---\n"
    )


# --------------------------------------------------------------------------- #
# Batch layout + manifest + report
# --------------------------------------------------------------------------- #
def batch_dirs(source_dir) -> dict:
    """Given the source folder (".../3 - Source Material/All Job Posts (full text)"),
    derive the sibling quarantine dirs and the batch's prep-report dir."""
    src = Path(source_dir).resolve()
    sm = src.parent            # "3 - Source Material"
    batch = sm.parent          # batch root (__READY_TO_REVIEW__PRIVATE_GITIGNORED/MM-DD-YY)
    return {
        "batch": batch,
        "source": src,
        "needs_review": sm / "Needs Review",
        "failed": sm / "Failed",
        "report": batch / "0 - Prep Report",
    }


def ensure_dirs(dirs: dict) -> None:
    for k in ("source", "needs_review", "failed", "report"):
        dirs[k].mkdir(parents=True, exist_ok=True)


def _rel(path: Path, batch: Path) -> str:
    try:
        return str(Path(path).resolve().relative_to(batch.resolve()))
    except Exception:
        return str(path)


def new_manifest(batch: str) -> dict:
    return {"schema_version": 1, "batch": batch, "fetched_at": None,
            "input_count": 0, "counts": {}, "entries": []}


def load_manifest(path: Path) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def save_manifest(path: Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _counts(entries: list[dict]) -> dict:
    c = {USABLE: 0, THIN: 0, FAILED: 0, DUPLICATE: 0, NEEDS_REVIEW: 0}
    for e in entries:
        c[e["status"]] = c.get(e["status"], 0) + 1
    return c


def write_report(path: Path, manifest: dict) -> None:
    e = manifest["entries"]
    c = manifest["counts"]
    usable = [x for x in e if x["status"] == USABLE]
    thin = [x for x in e if x["status"] == THIN]
    failed = [x for x in e if x["status"] == FAILED]
    dups = [x for x in e if x["status"] == DUPLICATE]
    possible = [x for x in usable if x.get("possible_duplicate_group")]
    # Usable posts still missing a hard field (comp / working-location). These rank
    # anyway — but loudly flagged, distinguishing "employer didn't publish" from
    # "expected from the ATS but came back empty".
    incomplete = [x for x in usable
                  if any((x.get("field_status") or {}).get(f) in (CAPTURE_FAILED, NOT_POSTED, CONFLICTING)
                         for f in HARD_FIELDS)]
    safe = "Yes — usable posts are ready to rank." if usable else "No usable posts yet."

    lines = [f"# Prep Report — {manifest['batch']}", ""]
    lines.append(f"Prep finished. I found {manifest['input_count']} URL(s):")
    lines.append(f"- ✅ {c.get(USABLE,0)} usable job post(s)  → \"3 - Source Material/All Job Posts (full text)/\"")
    lines.append(f"- ♻️ {c.get(DUPLICATE,0)} duplicate(s) skipped")
    lines.append(f"- ⚠️ {c.get(THIN,0)} thin post(s) — needs review  → \"3 - Source Material/Needs Review/\"")
    lines.append(f"- ❌ {c.get(FAILED,0)} failed fetch(es)  → \"3 - Source Material/Failed/\"")
    lines.append(f"- 👀 {len(possible)} possible same company/title duplicate(s) — review")
    lines += ["", f"**Safe to rank now?** {safe}", ""]
    lines.append("Usable posts are ready for ranking. Please review the thin/failed items before "
                 "relying on them (open them, paste the real job text if needed, then re-run prep).")
    if incomplete:
        lines.append(f"- ⚠️ {len(incomplete)} usable post(s) with an incomplete comp/location capture — see below")
    lines += ["", "## Details"]
    if incomplete:
        lines.append("**⚠️ Incomplete captures (still ranked — review the flagged field):**")
        for x in incomplete:
            fsx = x.get("field_status") or {}
            bits = []
            for f in HARD_FIELDS:
                st = fsx.get(f)
                if st == CAPTURE_FAILED:
                    bits.append(f"{f.replace('_', '-')}: capture failed (expected from "
                                f"{x.get('method') or 'source'} but came back empty)")
                elif st == NOT_POSTED:
                    bits.append(f"{f.replace('_', '-')}: not posted (employer didn't publish)")
                elif st == CONFLICTING:
                    bits.append(f"{f.replace('_', '-')}: conflicting (two sources disagree — both kept)")
            lines.append(f"- {x.get('company','?')} — {x.get('title','?')}: {'; '.join(bits)}  ({x['original_url']})")
    if possible:
        lines.append("**Possible duplicates (kept both — review):**")
        for x in possible:
            lines.append(f"- {x.get('company','?')} — {x.get('title','?')}  ({x['original_url']})")
    if thin:
        lines.append("**Thin (in Needs Review/):**")
        for x in thin:
            lines.append(f"- {Path(x.get('quarantine_path','')).name} — {x.get('notes','')}  ({x['original_url']})")
    if failed:
        lines.append("**Failed (in Failed/):**")
        for x in failed:
            lines.append(f"- {x['original_url']} — {x.get('error','error')}")
    if dups:
        lines.append("**Duplicates skipped:**")
        for x in dups:
            lines.append(f"- {x['original_url']}  (same as {x.get('duplicate_of','')})")
    lines.append("")
    lines.append("Next: rank the usable posts. For thin/failed ones, paste the real text or re-run prep to retry.")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _remove_if_exists(rel_path: str, batch: Path) -> None:
    if not rel_path:
        return
    fp = (batch / rel_path)
    try:
        if fp.exists():
            fp.unlink()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# Orchestrator — both scripts call this with their own fetch_one()
# --------------------------------------------------------------------------- #
def process_urls(urls: list[str], source_dir, fetch_one, *, force: bool = False,
                  fetch_fallback=None, fallback_label: str | None = None) -> dict:
    """fetch_one(url) -> dict: {ok: bool, title, company, body, method, error}.
    Manifest-aware: a plain re-run skips already-usable URLs and retries
    thin/failed ones (set force=True to refetch everything).

    HARD RULE (Jessica, 7/16/26): a job must never be scored against content nobody has
    confirmed is the real posting. Before quarantining a THIN/FAILED result, always try a
    SECOND fetch method if one is available (fetch_fallback — same signature as fetch_one).
    Only after both methods fail does a URL get quarantined, and the quarantine notes then
    say plainly that multiple methods were attempted and both failed. If no fallback is
    available at all (e.g. Playwright isn't installed), that limitation is recorded in the
    manifest/report too, rather than silently only trying once."""
    dirs = batch_dirs(source_dir)
    ensure_dirs(dirs)
    batch_root = dirs["batch"]
    mpath = dirs["report"] / "prep-manifest.json"
    manifest = load_manifest(mpath) or new_manifest(batch_root.name)
    prev_by_norm = {e["normalized_url"]: e for e in manifest.get("entries", [])}

    # Rebuild the "taken filename -> owning normalized_url" map from prior entries.
    taken: dict[str, str] = {}
    for e in manifest.get("entries", []):
        rel = e.get("output_path") or e.get("quarantine_path")
        if rel:
            taken[Path(rel).name] = e["normalized_url"]

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    entries: list[dict] = []
    seen: dict[str, str] = {}   # normalized_url -> original_url (first this run)

    def base_entry(url, norm, **kw):
        d = {"original_url": url, "normalized_url": norm, "status": None, "method": None,
             "company": None, "title": None, "char_count": None, "output_path": None,
             "quarantine_path": None, "duplicate_of": None, "duplicate_group": None,
             "possible_duplicate_group": None, "notes": "", "error": None, "fetched_at": ts,
             # Completeness gate (comp + working-location before ranking). A missing
             # hard field never quarantines — the job stays usable and ranks, flagged.
             "field_status": None, "missing_fields": [], "methods_tried": [],
             "has_compensation": None, "has_working_location": None}
        d.update(kw)
        return d

    for raw in urls:
        url = raw.strip()
        if not url or url.startswith("#"):
            continue
        norm = normalize_url(url)

        if norm in seen:
            entries.append(base_entry(url, norm, status=DUPLICATE, duplicate_of=seen[norm],
                                      notes="exact/normalized duplicate of an earlier URL this run"))
            continue
        seen[norm] = url

        prev = prev_by_norm.get(norm)
        if prev and prev.get("status") == USABLE and not force:
            carried = dict(prev)
            carried["notes"] = (prev.get("notes") or "").strip() or "carried forward (already usable)"
            entries.append(carried)
            continue

        # Retrying this URL: remove any prior file so we never orphan/duplicate.
        if prev:
            _remove_if_exists(prev.get("output_path"), batch_root)
            _remove_if_exists(prev.get("quarantine_path"), batch_root)
            for fn, owner in list(taken.items()):
                if owner == norm:
                    taken.pop(fn, None)

        def _evaluate(r):
            """(status, reason, field_status) for one fetch result."""
            if not r.get("ok"):
                return FAILED, (r.get("error") or "fetch failed"), {}
            st, rs = classify(r.get("body") or "", is_ats=(r.get("method") == "ats"))
            f_status = assess_completeness(r.get("meta") or {}, r.get("body") or "",
                                           r.get("questions") if r.get("questions") is not None
                                           else (r.get("meta") or {}).get("questions"))
            return st, rs, f_status

        res = fetch_one(url) or {}
        methods_tried = [res.get("method") or "unknown"]
        status, reason, field_status = _evaluate(res)

        # HARD RULE: never quarantine on one method alone if a second one is available.
        # The fallback fetch fires when the first attempt is THIN/FAILED *or* when a hard
        # field (compensation / working-location) came back as a genuine capture failure
        # (field-driven, not just body-thinness) — this is the completeness gate that
        # runs BEFORE ranking, so we don't rank an incomplete capture then re-fetch later.
        field_gap = missing_hard_fields(field_status)
        if (status != USABLE or field_gap) and fetch_fallback is not None:
            res2 = fetch_fallback(url) or {}
            methods_tried.append(res2.get("method") or fallback_label or "fallback")
            status2, reason2, field_status2 = _evaluate(res2)
            gap2 = missing_hard_fields(field_status2)
            improved_body = status2 == USABLE or (status == FAILED and status2 == THIN)
            improved_fields = status2 == USABLE and len(gap2) < len(field_gap)
            if improved_body or improved_fields:
                res, status, reason, field_status, field_gap = res2, status2, reason2, field_status2, gap2
            if status != USABLE:
                reason = f"{reason} (tried {', '.join(methods_tried)}, all failed to produce usable content)"
        elif status != USABLE and fetch_fallback is None:
            reason = (f"{reason} — only one fetch method attempted ({methods_tried[0]}); "
                      f"no fallback method available (e.g. Playwright not installed) to auto-retry")

        # Embedded-Greenhouse recovery: many custom career domains (careers.<co>.com)
        # are Greenhouse-backed. If we still lack a hard field (or never got usable
        # content), and this non-ATS URL carries a Greenhouse-style job id, hit the
        # real GH boards API with board tokens derived from the domain / page HTML.
        # Accepted only when the returned title matches what we already have (guards
        # a wrong-board-token collision) — this is what lets e.g. Airbnb recover
        # comp + location a plain scrape of careers.airbnb.com misses.
        if status != USABLE or field_gap:
            rec = recover_embedded_greenhouse(
                url, page_title=res.get("title"), body=res.get("body"),
                html_text=(res.get("meta") or {}).get("raw_html"))
            if rec:
                methods_tried.append("greenhouse-embedded")
                rec_meta = dict(rec)
                rec_meta["method"] = "ats"
                rec_meta["structured_source"] = True
                res_rec = {"ok": True, "title": rec.get("title"),
                           "company": rec.get("company"), "body": rec.get("text") or "",
                           "method": "ats", "error": None, "meta": rec_meta,
                           "questions": rec.get("questions") or []}
                status_r, reason_r, field_status_r = _evaluate(res_rec)
                gap_r = missing_hard_fields(field_status_r)
                if status_r == USABLE and (status != USABLE or len(gap_r) < len(field_gap)):
                    res, status, reason, field_status, field_gap = (
                        res_rec, status_r, reason_r, field_status_r, gap_r)

        if status == FAILED:
            fn = failed_filename(url, norm)
            out = dirs["failed"] / fn
            out.write_text(failed_text(url, reason, ts), encoding="utf-8")
            entries.append(base_entry(url, norm, status=FAILED, method=res.get("method"),
                                      error=reason, notes=f"methods tried: {', '.join(methods_tried)}",
                                      methods_tried=methods_tried,
                                      quarantine_path=_rel(out, batch_root)))
            continue

        title = (res.get("title") or "Unknown Title").strip()
        company = (res.get("company") or "Unknown").strip()
        body = res.get("body") or ""
        method = res.get("method")
        meta = res.get("meta") or {}
        questions = res.get("questions") if res.get("questions") is not None else meta.get("questions")
        missing = missing_hard_fields(field_status)
        has_comp = field_status.get("compensation") == FOUND
        has_loc = field_status.get("working_location") == FOUND

        fn = unique_filename(company, title, norm, taken, url)
        taken[fn] = norm
        out_text = build_output_text(url, title, company, body, meta=meta, questions=questions,
                                     field_status=field_status, methods_tried=methods_tried)
        if status == USABLE:
            out = dirs["source"] / fn
            out.write_text(out_text, encoding="utf-8")
            note_bits = []
            if len(methods_tried) > 1:
                note_bits.append(f"usable after fallback (tried: {', '.join(methods_tried)})")
            if missing:
                note_bits.append("incomplete capture: " + ", ".join(
                    f"{f.replace('_', '-')} {field_status.get(f)}" for f in missing))
            entries.append(base_entry(url, norm, status=USABLE, method=method, company=company,
                                      title=title, char_count=len(body), notes="; ".join(note_bits),
                                      field_status=field_status, missing_fields=missing,
                                      methods_tried=methods_tried, has_compensation=has_comp,
                                      has_working_location=has_loc, output_path=_rel(out, batch_root)))
        else:  # THIN
            out = dirs["needs_review"] / fn
            out.write_text(thin_text(url, title, company, body, reason, ts, meta=meta,
                                     questions=questions, field_status=field_status,
                                     methods_tried=methods_tried), encoding="utf-8")
            entries.append(base_entry(url, norm, status=THIN, method=method, company=company,
                                      title=title, char_count=len(body), notes=reason,
                                      field_status=field_status, missing_fields=missing,
                                      methods_tried=methods_tried, has_compensation=has_comp,
                                      has_working_location=has_loc,
                                      quarantine_path=_rel(out, batch_root)))

    # Soft-flag possible same company/title duplicates among usable posts (keep both).
    groups: dict[tuple, list[dict]] = {}
    for e in entries:
        if e["status"] == USABLE and e.get("company") and e.get("title"):
            groups.setdefault((e["company"].lower(), first_line(e["title"]).lower()), []).append(e)
    gid = 0
    for key, members in groups.items():
        if len(members) > 1:
            gid += 1
            for m in members:
                m["possible_duplicate_group"] = f"g{gid}"
                m["notes"] = (m["notes"] + "; possible same company/title duplicate — review").strip("; ")

    manifest["entries"] = entries
    manifest["input_count"] = sum(1 for u in urls if u.strip() and not u.strip().startswith("#"))
    manifest["counts"] = _counts(entries)
    manifest["fetched_at"] = ts
    save_manifest(mpath, manifest)
    write_report(dirs["report"] / "prep-report.md", manifest)
    _print_summary(manifest, dirs)
    return manifest


def _print_summary(manifest: dict, dirs: dict) -> None:
    c = manifest["counts"]
    print("")
    print(f"Prep finished — {manifest['input_count']} URL(s):")
    print(f"  usable:   {c.get(USABLE,0)}   (ready to rank)")
    print(f"  thin:     {c.get(THIN,0)}   (in 'Needs Review/')")
    print(f"  failed:   {c.get(FAILED,0)}   (in 'Failed/')")
    print(f"  dupes:    {c.get(DUPLICATE,0)}   (skipped)")
    possible = sum(1 for e in manifest["entries"] if e.get("possible_duplicate_group"))
    if possible:
        print(f"  possible same company/title dupes: {possible} (kept both — review)")
    print(f"Report:   {dirs['report'] / 'prep-report.md'}")
    print(f"Usable:   {dirs['source']}")
