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
  The Lever payload carries NO questions, but it does carry `applyUrl`, so a
  caller can render that apply page for the questions.
- LinkedIn (linkedin.com/jobs) via the logged-out "guest" jobPosting endpoint.
- Rippling (ats.rippling.com) via the public ATS board API. This one is unusually
  rich: comp per pay zone, work locations, employment type, AND the application
  questions inline — `activeJobApplication.additionalQuestions` holds the CUSTOM
  questions (screening/knockout/essay) and `.basicQuestions` the routine fields.
  No apply-page render is needed for Rippling.
- Workable (apply.workable.com) via the public accounts/jobs API (content,
  location, workplace). Comp is usually absent and questions are NOT on the API,
  so a caller renders `/<sub>/j/<shortcode>/apply/` for the questions.
- Workday (<tenant>.wdN.myworkdayjobs.com) via the CxS API. The required
  `Job_Posting_Site_ID` is simply the first path segment of the public job URL
  (e.g. `.../WG/job/...` -> site id `WG`), so it needs no guessing. Comp and
  application questions are NOT exposed (the questionnaire is behind candidate
  auth), so Workday yields content/location/company only.

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


# --------------------------------------------------------------------------- #
# Posting dates (2026-07-29)
#
# Every ATS we talk to carries a publication date in a payload we ALREADY parse, and we
# discarded all of them — the only date in a capture was `Captured:` (our own fetch date),
# so nothing downstream could tell a week-old posting from a nine-month-old one. Per ATS:
#   Greenhouse  first_published / updated_at
#   Ashby       publishedAt / updatedAt
#   Rippling    createdOn / updatedOn
#   Workable    published
#   Lever       createdAt  (epoch MILLISECONDS, not seconds)
#   Workday     postedOn is a RELATIVE string ("Posted 30 Days Ago") -> unusable; the CxS
#               payload's startDate is a real ISO date and is used instead
#   generic     JSON-LD datePosted
# Everything is normalized to a plain `YYYY-MM-DD`. NEVER fabricate: an unparseable or
# relative value yields None and the field is simply omitted.
# --------------------------------------------------------------------------- #
_ISO_DATE_PREFIX_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
_EPOCH_RE = re.compile(r"^\d{10,13}$")


def _epoch_to_date(value) -> Optional[str]:
    """Epoch seconds OR milliseconds -> 'YYYY-MM-DD' (UTC). Lever uses milliseconds."""
    from datetime import datetime, timezone
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    if v > 1e11:  # milliseconds
        v = v / 1000.0
    try:
        return datetime.fromtimestamp(v, tz=timezone.utc).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def normalize_posting_date(value) -> Optional[str]:
    """Any ATS date value -> plain 'YYYY-MM-DD', or None.

    Accepts ISO timestamps with times/TZ offsets ('2026-06-13T09:05:32-04:00' ->
    '2026-06-13'; the offset and time are stripped, not shifted), plain dates, and epoch
    seconds/milliseconds. Returns None — never a guess — for empty values, relative wording
    ('Posted 30 Days Ago'), and anything else unparseable."""
    from datetime import date as _date
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return _epoch_to_date(value)
    s = str(value).strip()
    if not s:
        return None
    if _EPOCH_RE.match(s):
        return _epoch_to_date(int(s))
    m = _ISO_DATE_PREFIX_RE.match(s)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        _date(y, mo, d)
    except ValueError:
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _dates(posted, updated=None) -> dict:
    """The two date keys for a fetcher result, normalized. An `updated` equal to (or
    unparseable relative to) `posted` is still recorded — build_output_text decides
    whether to show it."""
    return {"posted_date": normalize_posting_date(posted),
            "updated_date": normalize_posting_date(updated)}

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
#     "employer_apply_url": str | None,   # employer-hosted apply page, kept verbatim when
#                                         # apply_url was replaced by a canonical deep link
#     "posted_date": str | None,          # "YYYY-MM-DD" — when the employer published it
#     "updated_date": str | None,         # "YYYY-MM-DD" — last edit, when the ATS exposes one
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
    # Workable apply-form / Rippling basicQuestions naming variants.
    "firstname", "lastname", "phone_number", "linkedin_link", "current_company",
    "org", "gdpr", "resume_file", "cover_letter_file",
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
    # NOTE (reverted 2026-07-29, by the candidate's explicit call): a previous change
    # excluded voluntary DIVERSITY-STATEMENT prompts ("we recruit from underrepresented
    # communities — if you bring a diverse perspective based on your background, share
    # more here") as self-identification. That was WRONG for this system's purpose. Such
    # a prompt is FREE TEXT that requires genuinely sitting down and composing something
    # about yourself — categorically different from a gender/race dropdown — so it passes
    # the "think and compose a response" keep-test and MUST be kept. Do not re-add an
    # exclusion for it. (The dropdown-style self-ID fields above are still excluded.)
    r"country of residence|current (city|residence|address)|home address|"
    r"where (do|are) you (currently )?(live|located|residing|reside)|"
    r"where are you (currently )?based|"
    # Routine sourcing + accommodation fields. These are often free-text (so the
    # compose keep-rule would otherwise retain them) but they are administrative:
    # they say nothing about the job and need no thought to answer.
    r"(how|where) did you (hear|find out|learn) about|how were you referred|"
    r"referral source|"
    r"accommodations?.{0,40}(interview|application|process|recruit)"
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
# Accepts labeled variants too ("Full Time Employee Benefits:", "Employee Benefits",
# "Our Benefits") — a short qualifier before the keyword is still a benefits heading.
_BENEFITS_HEADING_RE = re.compile(
    r"(?im)^[\s#>*_\-]*(?:(?:full[-\s]?time|part[-\s]?time|employee|our|us|team|your)\s+){0,3}"
    r"(benefits?|perks?( & benefits)?|what we offer)\b[:\s]*$")
_EQUITY_RE = re.compile(r"(?i)([^.\n]*\b(equity|stock options?|RSUs?|restricted stock|ESPP)\b[^.\n]*)")

# THIRD STATE — "Mentioned (no details)" (2026-07-29 spec).
#
# A posting that says "you may also be eligible for bonus, equity, benefits" HAS told us
# equity/benefits exist; it just published no specifics. That is materially different from
# "Not posted" (the employer said nothing at all), and reporting it as Not posted was a real
# regression: the capture claimed the employer omitted equity when the employer had actually
# mentioned it. The same guard also catches the inverse failure mode — a COMPENSATION
# DISCLAIMER sentence ("the range … does not include equity, bonus and benefits") is a
# mention of equity, NOT a description of an equity grant, so it must never be surfaced as
# the Equity value verbatim.
MENTIONED_NO_DETAILS = "Mentioned (no details)"

# Sentence shapes that only MENTION the thing (disclaimer or bare eligibility), with no
# specifics (no grant size, no percentage, no share count, no dollar value).
_MENTION_ONLY_RE = re.compile(
    r"(?i)\b(?:does\s+not\s+include|doesn'?t\s+include|not\s+include|excludes?|"
    r"exclusive\s+of|in\s+addition\s+to|(?:may|might|could|can|will|are|is)\s+(?:also\s+)?be\s+"
    r"eligible(?:\s+for)?|eligibility\s+for)\b")
# Specifics that make a sentence a real description rather than a bare mention.
_EQUITY_SPECIFICS_RE = re.compile(
    r"(?i)(\$\s?\d|\d[\d,]*\s*(?:shares?|units?|options?|rsus?)\b|\b\d+(?:\.\d+)?\s*%|"
    r"\bvest(?:s|ing|ed)?\b|\bstrike price\b|\bgrant (?:of|size|value)\b)")
# An eligibility/mention sentence that names BENEFITS (used for the benefits third state
# when no Benefits section exists to mine items from).
_BENEFITS_MENTION_RE = re.compile(
    r"(?i)[^.\n]*\b(?:benefits?|perks?)\b[^.\n]*")
# Benefits named as a COMPENSATION COMPONENT or an offered package, with no specifics —
# e.g. "... is $122,400-$170,000 + equity + benefits.", "plus benefits", "benefits package".
# This is the shape the eligibility-only regex above misses: the mention lives inside the
# comp sentence rather than in a benefits section, and reporting "did not mention" while
# the posting says "+ benefits" contradicts the employer's own text.
_BENEFITS_COMPONENT_RE = re.compile(
    r"(?i)(?:[+&]\s*(?:full\s+|comprehensive\s+)?benefits?\b|"
    r"\b(?:plus|and|includes?|including|offers?|with)\s+(?:full\s+|comprehensive\s+|"
    r"competitive\s+|generous\s+)?benefits?\b|"
    r"\bbenefits?\s+(?:package|program|plan)\b)")


def _mention_only(sentence: str, specifics_re: "re.Pattern") -> bool:
    """True when a matched sentence merely MENTIONS the thing (a comp disclaimer or a bare
    eligibility clause) and carries none of the specifics that would make it a description."""
    s = sentence or ""
    return bool(_MENTION_ONLY_RE.search(s)) and not specifics_re.search(s)


def mine_benefits_equity(text: str) -> tuple[Optional[str], Optional[str]]:
    """Best-effort summary of benefits + equity from the description prose. Reads
    a 'Benefits/Perks' section (first handful of bullet/line items) and any
    equity/stock-option sentence. Returns (benefits|None, equity|None), where either
    may be the third state `Mentioned (no details)` — the employer referenced it
    without publishing specifics (distinct from None, i.e. "Not posted")."""
    body = text or ""
    benefits = None
    m = _BENEFITS_HEADING_RE.search(body)
    if m:
        tail = body[m.end():]
        items: list[str] = []
        # The WHOLE labeled section must be summarized (a blank line between bullets is
        # normal formatting, not the end of the section — stopping at the first blank
        # truncated a 7-bullet benefits list to its first item). A bullet list ends at
        # the next heading-like line, or at a non-bullet paragraph after a blank once
        # the section has shown itself to be bullet-shaped.
        raws = tail.splitlines()
        saw_bullet = False
        prev_blank = False
        for i, raw in enumerate(raws):
            stripped = raw.strip()
            is_bullet = bool(re.match(r"^[\-•*·]\s+", stripped))
            line = stripped.lstrip("-•*· \t").strip()
            if not line:
                prev_blank = True
                if items and not saw_bullet:
                    # An intro paragraph followed by the section's bullet list is still
                    # the same section — peek past the blank before calling it done.
                    nxt = next((r.strip() for r in raws[i + 1:] if r.strip()), "")
                    if re.match(r"^[\-•*·]\s+", nxt):
                        continue
                    break  # prose-style section: a blank ends it
                continue
            # Stop at the next section heading (short Title-ish line ending in ':').
            if line.endswith(":") and len(line) < 40 and items:
                break
            # Left the bullet list: a non-bullet paragraph after a blank line.
            if items and saw_bullet and not is_bullet and prev_blank:
                break
            prev_blank = False
            if is_bullet:
                saw_bullet = True
            items.append(line)
            if len(items) >= 10:
                break
        # Never slice mid-word/mid-sentence: an over-long section drops whole ITEMS
        # from the end (the writer applies the real sentence-bounded budget, keeping
        # the most distinctive details).
        while len(items) > 1 and len("; ".join(items)) > 900:
            items.pop()
        if items:
            benefits = "; ".join(items)
    if not benefits:
        # No Benefits section to mine — but ANY mention still means the employer
        # referenced them ("Mentioned", never "Not posted"): an eligibility clause, or
        # benefits named as a comp component / offered package ("+ benefits").
        bm = _BENEFITS_MENTION_RE.search(body)
        if bm and _MENTION_ONLY_RE.search(bm.group(0)):
            benefits = MENTIONED_NO_DETAILS
        elif _BENEFITS_COMPONENT_RE.search(body):
            benefits = MENTIONED_NO_DETAILS
    equity = None
    e = _EQUITY_RE.search(body)
    if e:
        sentence = e.group(1).strip()
        # A comp disclaimer ("… does not include equity …") or a bare eligibility clause is a
        # MENTION, not an equity description — never surface it as the Equity value verbatim.
        if _mention_only(sentence, _EQUITY_SPECIFICS_RE):
            equity = MENTIONED_NO_DETAILS
        else:
            equity = sentence
            if len(equity) > 200:
                equity = equity[:197].rstrip() + "…"
    return benefits, equity


def fetch_via_ats(url: str, timeout: int = 20) -> Optional[dict]:
    """Dispatch to the matching ATS fetcher, or return None if unrecognized.

    Beyond the known ATS hosts, a CUSTOM career domain that carries an ATS
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
        if host.endswith("rippling.com"):
            return _fetch_rippling(url, timeout=timeout)
        if host.endswith("workable.com"):
            return _fetch_workable(url, timeout=timeout)
        if "myworkdayjobs.com" in host:
            return _fetch_workday(url, timeout=timeout)
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


# Ashby component `compensationType` values that are BASE SALARY. Everything else
# (EquityPercentage, Bonus, Commission, …) is additional compensation and must never
# reach the Base Salary field — "Offers Equity" is not a salary band.
_ASHBY_SALARY_TYPES = {"salary", "hourly", "basesalary", "base"}
# A component type -> the Additional Compensation component name we report.
_ASHBY_ADDITIONAL_NAMES = {
    "equitypercentage": "Equity", "equity": "Equity", "equityamount": "Equity",
    "bonus": "Bonus", "annualbonus": "Bonus", "signingbonus": "Signing Bonus",
    "commission": "Commission", "targetcommission": "Commission",
}


# Summary wording that describes a non-salary component rather than a pay band, for
# stripping it out of a " • "-joined tier summary even when the component list is absent.
_NON_SALARY_WORDING_RE = re.compile(
    r"(?i)^(?:offers?|includes?|plus|eligible for)?\s*"
    r"(?:equity|stock|options?|rsus?|bonus|commission|benefits?|perks?)\b")


def _ashby_component_kind(component: dict) -> str:
    return re.sub(r"[^a-z]+", "", str((component or {}).get("compensationType") or "").lower())


def _ashby_additional_components(comp: dict) -> list[str]:
    """Component NAMES for the non-salary parts of an Ashby comp object (equity,
    bonus, commission …), in the order the employer listed them. These belong in
    Additional Compensation, never in Base Salary."""
    out: list[str] = []
    for t in (comp or {}).get("compensationTiers") or []:
        if not isinstance(t, dict):
            continue
        for c in (t.get("components") or []):
            if not isinstance(c, dict):
                continue
            kind = _ashby_component_kind(c)
            if not kind or kind in _ASHBY_SALARY_TYPES:
                continue
            name = _ASHBY_ADDITIONAL_NAMES.get(kind)
            if not name:
                # Unknown non-salary type: fall back to its own summary wording.
                name = (c.get("summary") or "").strip() or None
            if name and name not in out:
                out.append(name)
    return out


def _ashby_compensation(comp: dict) -> tuple[Optional[str], Optional[str]]:
    """Return (normalized per-zone BASE-SALARY string, verbatim raw) from Ashby's
    `compensation` object. Prefers the per-zone `compensationTiers`.

    Only components whose `compensationType` is a salary type are represented: the
    structured components beat the `tierSummary` STRING, which glues non-salary
    parts on with " • " ("$172K – $248K • Offers Equity") and used to be split into
    pseudo-bands — one of them reading "Offers Equity" as if it were a pay range.
    """
    if not isinstance(comp, dict):
        return None, None
    tiers = comp.get("compensationTiers") or []
    zone_parts: list[str] = []
    for t in tiers:
        if not isinstance(t, dict):
            continue
        title = (t.get("title") or "").strip()
        summary = (t.get("tierSummary") or "").strip()
        # Explicit min/max/currency/interval from the SALARY components only, plus the
        # display wording of every NON-salary component so it can be stripped from the
        # summary string below.
        comp_bits = []
        non_salary_wording = []
        for c in (t.get("components") or []):
            if not isinstance(c, dict):
                continue
            kind = _ashby_component_kind(c)
            if kind and kind not in _ASHBY_SALARY_TYPES:
                wording = (c.get("summary") or "").strip()
                if wording:
                    non_salary_wording.append(wording)
                continue
            lo, hi = c.get("minValue"), c.get("maxValue")
            cur = c.get("currencyCode") or ""
            interval = (c.get("interval") or "").strip()
            if lo or hi:
                rng = f"{cur} {lo:,}–{hi:,}".strip() if (lo and hi) else f"{cur} {lo or hi:,}".strip()
                if interval and interval.upper() not in ("", "1 YEAR"):
                    rng = f"{rng}/{interval}"
                comp_bits.append(rng)
        # The tier summary carries the employer's own display wording (currency symbols,
        # abbreviated thousands) so it stays PREFERRED — but the non-salary parts it glues
        # on with " • " are removed first, since "Offers Equity" is not a pay band. The
        # structured salary components are the fallback when no usable summary survives.
        salary_summary = ""
        if summary:
            parts = [p.strip() for p in re.split(r"\s*•\s*", summary) if p.strip()]
            keep = [p for p in parts
                    if p not in non_salary_wording and not _NON_SALARY_WORDING_RE.search(p)]
            salary_summary = ", ".join(keep)
        detail = salary_summary or (", ".join(comp_bits) if comp_bits else "")
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
    # Prefer the HTML description: it carries the employer's REAL list structure,
    # which the structure-preserving renderer keeps (`- item` / `1. item` lines).
    # descriptionPlain is Ashby's own pre-flattened text — fallback only.
    body = _html_to_text(job.get("descriptionHtml") or "")
    if not body:
        body = (job.get("descriptionPlain") or "").strip()
    if not body:
        return None

    comp, comp_raw = _ashby_compensation(job.get("compensation") or {})
    additional_comp = _ashby_additional_components(job.get("compensation") or {})
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
        # Structured non-salary components (equity/bonus/commission), for
        # Additional Compensation — never merged into Base Salary.
        "additional_compensation_components": additional_comp,
        "remote": job.get("isRemote"),
        "workplace": workplace,
        "compensation": comp,
        "compensation_raw": comp_raw,
        "location_raw": location_raw,
        "cadence_raw": None,
        "benefits": benefits,
        "equity": equity,
        "apply_url": job.get("applyUrl") or job.get("jobUrl"),
        **_dates(job.get("publishedAt"), job.get("updatedAt")),
        "posting_id": str(job.get("id")) if job.get("id") else None,
        "source": "ashby-posting-api",
        "comp_expected": comp_expected,
        "location_expected": True,
        "questions": [],  # not on the posting-api; render the apply page for these
        "text": body,
    }


# --------------------------------------------------------------------------- #
# Rendered apply-page field normalization (shared by Ashby / Lever / Workable /
# Homerun — every ATS whose questions are only visible on the apply page).
# --------------------------------------------------------------------------- #

# Field types emitted by the DOM scrape (Ashby's own vocabulary is the canon).
_APPLY_TYPE_MAP = {
    "longtext": "textarea", "textarea": "textarea",
    "string": "input_text", "email": "input_text", "phone": "input_text",
    "file": "file", "boolean": "boolean",
    "valueselect": "select", "multiselect": "select", "select": "select",
    "name": "input_text", "location": "input_text",
    "number": "input_number", "date": "input_date",
}

# Required-marker glyphs apply forms append to a label ("First name *", "Email ✱").
_REQUIRED_MARKER_CLASS = r"[\*✱✲＊⁎٭]"

# Rendered chrome that lands inside a label container but is not question text.
_APPLY_LABEL_NOISE = {
    "select...", "select…", "choose file", "attach resume/cv", "attach",
    "svgs not supported by this browser.", "upload", "browse",
}


def clean_apply_label(title: str, options: Optional[list] = None) -> tuple[str, bool]:
    """Turn a scraped label container's raw innerText into a clean question label.

    Rendered containers pick up more than the question: a required-marker glyph on
    its own line, the select's own option text, and file-input chrome. Returns
    (clean_label, required_marker_seen) — the second value lets a form that marks
    required-ness only visually still report `required`."""
    text = (title or "").replace("\xa0", " ")
    noise = set(_APPLY_LABEL_NOISE)
    for o in (options or []):
        label = (o.get("label") or o.get("value") or "") if isinstance(o, dict) else str(o or "")
        if label.strip():
            noise.add(label.strip().lower())
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.lower() in noise:
            continue
        lines.append(line)
    joined = " ".join(lines)
    stripped = re.sub(rf"^\s*(?:{_REQUIRED_MARKER_CLASS}\s*)+", "", joined)
    stripped = re.sub(rf"(?:\s*{_REQUIRED_MARKER_CLASS})+\s*$", "", stripped)
    marker = stripped != joined
    return re.sub(r"\s{2,}", " ", stripped).strip(), marker


def normalize_apply_fields(form: dict) -> list[dict]:
    """Normalize the fields scraped from a rendered apply page into the shared
    question shape. Field types follow Ashby's vocabulary (LongText, String, Email,
    Phone, File, Boolean, ValueSelect, Name, Location) because the DOM scrape emits
    it for every ATS. Ashby system/identity fields are named `_systemfield_*`.
    This does NOT filter — pass the result through `filter_questions`."""
    out: list[dict] = []
    for f in (form.get("fields") or []):
        if not isinstance(f, dict):
            continue
        raw_type = (f.get("type") or "").strip()
        raw_options = f.get("options") or []
        options = []
        for o in raw_options:
            if isinstance(o, dict):
                options.append(o.get("label") or o.get("value") or "")
            elif o:
                options.append(str(o))
        name = f.get("path") or f.get("id") or ""
        label, marker = clean_apply_label(f.get("title") or "", raw_options)
        out.append({
            "label": label,
            "help": (f.get("descriptionPlain") or f.get("description") or None),
            "type": _APPLY_TYPE_MAP.get(raw_type.lower(), raw_type.lower() or "input_text"),
            "source_type": raw_type,
            "required": bool(f.get("isRequired")) or marker,
            "name": name,
            "names": [name],
            "options": [o for o in options if o],
        })
    return out


# Back-compat alias: the normalizer started out Ashby-only and callers/tests still
# reference that name.
normalize_ashby_apply_fields = normalize_apply_fields


# ATSes whose application questions live ONLY on the rendered apply page, because
# their job API returns none. Rippling and Greenhouse are deliberately absent:
# their APIs carry the questions inline, so rendering them would be pure cost.
APPLY_RENDER_ATSES = ("ashby", "lever", "workable", "homerun")


def detect_apply_ats(*hints: Optional[str]) -> Optional[str]:
    """Identify the ATS behind a job from any mix of apply-URL / job-URL / `source`
    label, returning one of APPLY_RENDER_ATSES (or None).

    Host-based first, then the `?ashby_jid=` custom-domain marker, then a substring
    of the ATS source label. Detecting by SOURCE and not host alone is what lets
    custom-domain jobs (`lark.com/careers?ashby_jid=<uuid>` is served by Ashby under
    the employer's own domain) get their questions captured at all."""
    hosts = {"ashbyhq.com": "ashby", "lever.co": "lever",
             "workable.com": "workable", "homerun.co": "homerun"}
    for hint in hints:
        text = str(hint or "").strip().lower()
        if not text:
            continue
        if "://" in text:
            # A URL: match on the HOST only. Matching the whole string would let a
            # role slug like "clever-analytics" masquerade as Lever.
            host = urlparse(text).netloc
            for needle, ats in hosts.items():
                if host == needle or host.endswith("." + needle):
                    return ats
            if "ashby_jid=" in text:
                return "ashby"
        else:
            # A `source` label such as "ashby-posting-api (custom-domain jid)".
            for ats in APPLY_RENDER_ATSES:
                if ats in text:
                    return ats
    return None


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


# --------------------------------------------------------------------------- #
# Canonical Greenhouse apply URL (2026-07-29)
#
# A Greenhouse job's `absolute_url` is whatever the employer configured. Most employers point
# it at a real deep link (careers.<co>.com/positions/<id>, <co>.com/jobs/apply/<id>/…), which
# we keep. But some point it at their LISTING or SEARCH page and rely on `?gh_jid=<id>` to
# redirect client-side: stripe.com/jobs/search?gh_jid=, pinterestcareers.com/jobs/?gh_jid=,
# ordergroove.com/jobs/?gh_jid=, careers.onepeloton.com/en/all-jobs/?gh_jid=. Saved as the
# Application URL, those are near-useless later — they load a job SEARCH, not the posting.
#
# Detection is generic, not a host list: the id is absent from the PATH, present in the QUERY,
# and the path's last segment is a listing-ish one. Then we prefer the canonical ATS deep link
# and preserve the employer URL verbatim in the archival block so nothing is lost.
# --------------------------------------------------------------------------- #
_LISTING_PATH_SEGMENTS = {"jobs", "job", "search", "all-jobs", "openings", "open-roles"}


def canonical_greenhouse_apply_url(board: str, job_id) -> Optional[str]:
    """The canonical Greenhouse deep link for a posting."""
    if not board or not job_id:
        return None
    return f"https://job-boards.greenhouse.io/{board}/jobs/{job_id}"


def greenhouse_apply_url_is_listing_page(apply_url: Optional[str], job_id) -> bool:
    """True when an employer-hosted Greenhouse apply URL is a LISTING/SEARCH page that only
    carries the job id in its query string (so it depends on a redirect), rather than a real
    deep link whose PATH contains the id."""
    if not apply_url or not job_id:
        return False
    jid = str(job_id)
    parsed = urlparse(apply_url)
    path = (parsed.path or "").lower()
    if jid in path:
        return False              # a genuine deep link — keep it
    if jid not in (parsed.query or ""):
        return False              # id isn't in the query either; don't second-guess it
    last = path.rstrip("/").rsplit("/", 1)[-1]
    return last in _LISTING_PATH_SEGMENTS


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

    # Prefer the canonical ATS deep link over an employer LISTING/SEARCH page that only
    # redirects via ?gh_jid=; the employer URL is preserved verbatim either way.
    employer_apply_url = job.get("absolute_url")
    apply_url = employer_apply_url or url
    employer_apply_verbatim = None
    if greenhouse_apply_url_is_listing_page(employer_apply_url, job.get("id")):
        canonical = canonical_greenhouse_apply_url(board, job.get("id"))
        if canonical:
            apply_url = canonical
            employer_apply_verbatim = employer_apply_url

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
        "apply_url": apply_url,
        "employer_apply_url": employer_apply_verbatim,
        **_dates(job.get("first_published"), job.get("updated_at")),
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
        # Lever's createdAt is epoch MILLISECONDS (13 digits), unlike every other ATS here.
        **_dates(job.get("createdAt"), job.get("updatedAt")),
        "posting_id": posting_id,
        "source": "lever-postings-api",
        "comp_expected": False,
        "location_expected": bool(location or working_location),
        "structured_source": True,
        # Not on the postings API — the caller renders `applyUrl` for these.
        "questions": [],
        "text": body,
    }


# --------------------------------------------------------------------------- #
# Rippling
#
# URL shape:  https://ats.rippling.com/{board}/jobs/{uuid}[?jobSite=...]
# API:        https://api.rippling.com/platform/api/ats/v1/board/{board}/jobs/{uuid}
#
# The `Accept: application/json` header is REQUIRED — without it the API returns
# a 404 HTML page, which is what makes this endpoint look nonexistent.
#
# Rippling is the only ATS here that returns the application questions on the same
# call as the job content, so no apply-page render is ever needed for it.
# --------------------------------------------------------------------------- #

_RIPPLING_API = "https://api.rippling.com/platform/api/ats/v1/board/{board}/jobs/{job_id}"

# Rippling `questionType` (the reliable signal) -> coarse type. `dataType` is a
# poor compose signal on its own: a LONG_ANSWER essay can carry dataType "Text".
_RIPPLING_QUESTION_TYPE_MAP = {
    "long_answer": "textarea",
    "short_answer": "input_text",
    "knockout": "select",
    "single_select_radio": "select",
    "single_select_dropdown": "select",
    "multi_select": "select",
    "yes_no_scale_4": "select",
    "number": "input_number",
    "date": "input_date",
    "file": "file",
}

# Rippling `basicQuestions` fieldType, and the secondary `dataType` fallback.
_RIPPLING_FIELD_TYPE_MAP = {
    "short_answer": "input_text",
    "long_answer": "textarea",
    "phone_number": "input_text",
    "pronoun": "select",
    "file": "file",
    "number": "input_number",
    "date": "input_date",
    "select": "select",
    "enum": "select",
    "text": "input_text",
    "paragraph": "textarea",
    "boolean": "boolean",
}


def _rippling_ids(url: str):
    """Return (board_slug, job_uuid) for a Rippling ATS URL, or (None, None)."""
    parsed = urlparse(url)
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if not parts:
        return None, None
    board = parts[0]
    job_id = None
    for p in parts[1:]:
        if UUID_RE.fullmatch(p):
            job_id = p.lower()
            break
    if job_id is None:
        m = UUID_RE.search(url)
        job_id = m.group(0).lower() if m else None
    return board, job_id


def _fetch_rippling(url: str, timeout: int = 20) -> Optional[dict]:
    board, job_id = _rippling_ids(url)
    if not board or not job_id:
        return None
    resp = requests.get(
        _RIPPLING_API.format(board=board, job_id=job_id),
        # Accept: application/json is mandatory — without it Rippling serves a
        # 404 HTML shell instead of the job record.
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        return None
    try:
        job = resp.json()
    except Exception:
        return None
    if not isinstance(job, dict):
        return None
    return _rippling_job_to_result(job, board, url)


def parse_rippling_questions(job: dict) -> list[dict]:
    """Normalize Rippling's application questions into the shared question shape.

    Two sources, both on `activeJobApplication`:
      - `basicQuestions`: the routine/identity fields ({oid, fieldType, title,
        required}). Included so the shared filter drops them by NAME, exactly like
        every other ATS — never special-cased here.
      - `additionalQuestions`: the CUSTOM questions. This is a list of question
        SETS, each `{name, id, form: {questions: [...]}}`; the real questions live
        at `form.questions[]`. May be None when the employer added none.

    Does NOT filter — pass the result through `filter_questions`.
    """
    app = job.get("activeJobApplication") or {}
    out: list[dict] = []

    for f in (app.get("basicQuestions") or []):
        if not isinstance(f, dict):
            continue
        raw_type = (f.get("fieldType") or "").strip()
        name = (f.get("oid") or "").strip()
        out.append({
            "label": (f.get("title") or "").strip(),
            "help": None,
            "type": _RIPPLING_FIELD_TYPE_MAP.get(raw_type.lower(), "input_text"),
            "source_type": raw_type,
            "required": bool(f.get("required")),
            "name": name,
            "names": [name],
            "options": [],
        })

    for qset in (app.get("additionalQuestions") or []):
        if not isinstance(qset, dict):
            continue
        form = qset.get("form") or {}
        for q in (form.get("questions") or []):
            if not isinstance(q, dict):
                continue
            qtype = (q.get("questionType") or "").strip()
            dtype = (q.get("dataType") or "").strip()
            coarse = (_RIPPLING_QUESTION_TYPE_MAP.get(qtype.lower())
                      or _RIPPLING_FIELD_TYPE_MAP.get(dtype.lower())
                      or "input_text")
            options = [str(c) for c in (q.get("strChoices") or []) if c not in (None, "")]
            options += [str(c) for c in (q.get("intChoices") or []) if c not in (None, "")]
            name = (q.get("uniqueKey") or "").strip()
            out.append({
                "label": (q.get("title") or "").strip(),
                "help": (q.get("description") or None),
                "type": coarse,
                "source_type": qtype or dtype,
                "required": bool(q.get("isRequired")),
                "name": name,
                "names": [name],
                "options": options,
            })
    return out


def _rippling_compensation(pay_ranges) -> tuple[Optional[str], Optional[str]]:
    """Return (normalized per-zone comp, verbatim raw) from `payRangeDetails`,
    a list of {location, currency, frequency, rangeStart, rangeEnd, isRemote}."""
    if not isinstance(pay_ranges, list) or not pay_ranges:
        return None, None
    parts: list[str] = []
    for r in pay_ranges:
        if not isinstance(r, dict):
            continue
        lo, hi = r.get("rangeStart"), r.get("rangeEnd")
        if not (lo or hi):
            continue

        def _amt(v):
            try:
                f = float(v)
                return f"{int(f):,}" if f == int(f) else f"{f:,.2f}"
            except Exception:
                return str(v)

        cur = (r.get("currency") or "").strip()
        rng = f"{_amt(lo)}–{_amt(hi)}" if (lo and hi) else _amt(lo or hi)
        piece = f"{cur} {rng}".strip()
        freq = (r.get("frequency") or "").strip().lower()
        if freq and freq not in ("year", "yearly", "annual", "annually"):
            piece = f"{piece}/{freq}"
        zone = (r.get("location") or "").strip()
        if r.get("isRemote"):
            zone = f"{zone} (remote)".strip() if zone else "Remote"
        parts.append(f"{zone}: {piece}" if zone else piece)
    if not parts:
        return None, None
    joined = " · ".join(parts)
    return joined, joined


def _rippling_employment_type(emp) -> Optional[str]:
    """Rippling inverts the usual convention: `label` is the machine token
    ("SALARIED_FT") and `id` is the human string ("Salaried, full-time")."""
    if isinstance(emp, str):
        return emp or None
    if not isinstance(emp, dict):
        return None
    ident = (emp.get("id") or "").strip()
    label = (emp.get("label") or "").strip()
    # Prefer whichever value reads as prose: has a space or a lowercase letter and
    # is not a SCREAMING_SNAKE token.
    for cand in (ident, label):
        if cand and not re.fullmatch(r"[A-Z0-9_]+", cand):
            return cand
    return ident or label or None


def _rippling_job_to_result(job: dict, board: str, url: Optional[str] = None) -> Optional[dict]:
    """Pure Rippling job-object -> normalized result (unit-testable vs a saved
    board-API fixture)."""
    desc = job.get("description")
    if isinstance(desc, dict):
        # Two HTML blocks: the company blurb and the role itself, in page order.
        body = "\n\n".join(
            t for t in (_html_to_text(desc.get(k) or "") for k in ("company", "role")) if t
        )
    else:
        body = _html_to_text(desc or "")
    body = (body or "").strip()
    if not body:
        return None

    locations = [str(l).strip() for l in (job.get("workLocations") or []) if l]
    locations = [l for l in dict.fromkeys(locations) if l]
    working_location = "; ".join(locations) or None
    location = locations[0] if locations else None
    remote_flags = [bool(re.search(r"(?i)\bremote\b", l)) for l in locations]
    remote = (all(remote_flags) if remote_flags else None)
    workplace = "Remote" if remote else ("Hybrid" if any(remote_flags) else None)

    comp, comp_raw = _rippling_compensation(job.get("payRangeDetails"))
    benefits, equity = mine_benefits_equity(body)
    questions = filter_questions(parse_rippling_questions(job))
    job_url = job.get("url") or url

    return {
        "title": (job.get("name") or "").strip() or "Unknown Title",
        "company": (job.get("companyName") or "").strip() or _prettify_slug(board),
        "location": location,
        "working_location": working_location,
        "employment_type": _rippling_employment_type(job.get("employmentType")),
        "remote": remote,
        "workplace": workplace,
        "compensation": comp,
        "compensation_raw": comp_raw,
        "location_raw": working_location,
        "cadence_raw": None,
        "benefits": benefits,
        "equity": equity,
        "apply_url": job_url,
        **_dates(job.get("createdOn"), job.get("updatedOn")),
        "posting_id": str(job.get("uuid")) if job.get("uuid") else None,
        "source": "rippling-ats-api",
        # Rippling doesn't declare whether comp SHOULD be present, so an empty
        # payRangeDetails is "not posted", not a capture failure.
        "comp_expected": False,
        "location_expected": True,
        "structured_source": True,
        "questions": questions,
        "text": body,
    }


# --------------------------------------------------------------------------- #
# Workable
#
# URL shape:  https://apply.workable.com/{subdomain}/j/{SHORTCODE}[/apply/]
# API:        https://apply.workable.com/api/v1/accounts/{subdomain}/jobs/{SHORTCODE}
# Company:    https://apply.workable.com/api/v1/accounts/{subdomain}  -> {"name": ...}
#
# The job API carries content / location / workplace / employment type but NO
# questions and (usually) no salary, so questions come from rendering the apply
# page — see `apply_page_url` in prep_job_urls_playwright.py.
# --------------------------------------------------------------------------- #

_WORKABLE_ACCOUNT_CACHE: dict[str, Optional[str]] = {}

_WORKABLE_EMPLOYMENT_TYPES = {
    "full": "Full-time", "part": "Part-time", "contract": "Contract",
    "temporary": "Temporary", "internship": "Internship",
}

_WORKABLE_WORKPLACE = {
    "remote": "Remote", "hybrid": "Hybrid", "on_site": "Onsite", "onsite": "Onsite",
}


def workable_ids(url: str):
    """Return (subdomain, shortcode) for a Workable apply URL, or (None, None).
    Shape: apply.workable.com/{subdomain}/j/{SHORTCODE}[/apply/]"""
    parts = [unquote(p) for p in urlparse(url).path.split("/") if p]
    if len(parts) < 3 or parts[1].lower() != "j":
        return (parts[0] if parts else None), None
    return parts[0], parts[2]


def _workable_company(subdomain: str, timeout: int) -> Optional[str]:
    """The account's display name is the clean company name ('feeldco' -> 'Feeld')."""
    if subdomain in _WORKABLE_ACCOUNT_CACHE:
        return _WORKABLE_ACCOUNT_CACHE[subdomain]
    name = None
    try:
        resp = requests.get(
            f"https://apply.workable.com/api/v1/accounts/{subdomain}",
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout,
        )
        if resp.status_code == 200:
            name = (resp.json().get("name") or "").strip() or None
    except Exception:
        name = None
    _WORKABLE_ACCOUNT_CACHE[subdomain] = name
    return name


def _fetch_workable(url: str, timeout: int = 20) -> Optional[dict]:
    subdomain, shortcode = workable_ids(url)
    if not subdomain or not shortcode:
        return None
    resp = requests.get(
        f"https://apply.workable.com/api/v1/accounts/{subdomain}/jobs/{shortcode}",
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        return None
    try:
        job = resp.json()
    except Exception:
        return None
    if not isinstance(job, dict):
        return None
    company = _workable_company(subdomain, timeout) or _prettify_slug(subdomain)
    return _workable_job_to_result(job, subdomain, company, url)


def _workable_place(loc) -> Optional[str]:
    if not isinstance(loc, dict):
        return None
    city, region, country = loc.get("city"), loc.get("region"), loc.get("country")
    piece = ", ".join(p for p in [city, region] if p)
    return piece or (country or None)


def _workable_job_to_result(job: dict, subdomain: str, company: str,
                            url: Optional[str] = None) -> Optional[dict]:
    """Pure Workable job-object -> normalized result (unit-testable vs a saved
    accounts-API fixture)."""
    parts = [job.get("description") or "", job.get("requirements") or "",
             job.get("benefits") or ""]
    body = _html_to_text("\n".join(p for p in parts if p)).strip()
    if not body:
        return None

    location = _workable_place(job.get("location"))
    metros = [_workable_place(l) for l in (job.get("locations") or [])
              if isinstance(l, dict) and not l.get("hidden")]
    metros = [m for m in dict.fromkeys([location] + metros) if m]
    working_location = "; ".join(metros) or None

    workplace_raw = (job.get("workplace") or "").strip().lower()
    workplace = _WORKABLE_WORKPLACE.get(workplace_raw)
    emp_raw = (job.get("type") or "").strip().lower()
    employment_type = _WORKABLE_EMPLOYMENT_TYPES.get(emp_raw) or (job.get("type") or None)

    # Workable exposes salary only when the employer opted into it; usually null.
    comp = None
    salary = job.get("salary")
    if isinstance(salary, dict):
        lo, hi = salary.get("salary_from"), salary.get("salary_to")
        cur = salary.get("salary_currency") or ""
        if lo or hi:
            rng = f"{lo:,}–{hi:,}" if (lo and hi) else f"{lo or hi:,}"
            comp = f"{cur} {rng}".strip()
    elif isinstance(salary, str) and salary.strip():
        comp = salary.strip()

    benefits, equity = mine_benefits_equity(body)
    shortcode = job.get("shortcode")
    apply_url = (f"https://apply.workable.com/{subdomain}/j/{shortcode}/"
                 if shortcode else url)

    return {
        "title": (job.get("title") or "").strip() or "Unknown Title",
        "company": company,
        "location": location,
        "working_location": working_location,
        "employment_type": employment_type,
        "remote": job.get("remote") if isinstance(job.get("remote"), bool) else None,
        "workplace": workplace,
        "compensation": comp,
        "compensation_raw": comp,
        "location_raw": working_location,
        "cadence_raw": None,
        "benefits": benefits,
        "equity": equity,
        "apply_url": apply_url,
        **_dates(job.get("published")),
        "posting_id": str(shortcode) if shortcode else None,
        "source": "workable-api",
        "comp_expected": False,
        "location_expected": True,
        "structured_source": True,
        # Not on the API — the caller renders the apply page for these.
        "questions": [],
        "text": body,
    }


# --------------------------------------------------------------------------- #
# Workday
#
# URL shape:  https://{tenant}.wd{N}.myworkdayjobs.com[/{locale}]/{siteId}/job/{...}
# API:        https://{host}/wday/cxs/{tenant}/{siteId}/job/{...}
#
# The CxS API needs the tenant's `Job_Posting_Site_ID`, which is often treated as
# undiscoverable. It isn't: it is the first non-locale path segment of the public
# job URL (`.../WG/job/...` -> `WG`). Guessing the company name instead 404s.
#
# What Workday does NOT give us: compensation and the application questions. The
# payload carries only a `questionnaireId` — the questionnaire itself is behind
# candidate authentication — so Workday questions stay uncaptured by design.
# --------------------------------------------------------------------------- #

# Locale segments that can precede the site id (e.g. /en-US/Careers/job/...).
_WORKDAY_LOCALE_RE = re.compile(r"^[a-z]{2}(-[A-Za-z]{2})?$")


def workday_cxs_url(url: str) -> Optional[str]:
    """Build the CxS job endpoint for a public Workday job URL, or None."""
    parsed = urlparse(url)
    host = parsed.netloc
    tenant = host.split(".")[0].lower()
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    # Drop a leading locale segment; already-CxS URLs pass through untouched.
    if parts and parts[0].lower() == "wday":
        return f"https://{host}{parsed.path}"
    if parts and _WORKDAY_LOCALE_RE.match(parts[0]) and len(parts) > 1:
        parts = parts[1:]
    if len(parts) < 2 or parts[1].lower() != "job":
        return None
    site_id = parts[0]
    rest = "/".join(parts[1:])
    return f"https://{host}/wday/cxs/{tenant}/{site_id}/{rest}"


def _fetch_workday(url: str, timeout: int = 20) -> Optional[dict]:
    api = workday_cxs_url(url)
    if not api:
        return None
    resp = requests.get(
        api,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        return None
    try:
        payload = resp.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return _workday_payload_to_result(payload, url)


def _workday_payload_to_result(payload: dict, url: Optional[str] = None) -> Optional[dict]:
    """Pure Workday CxS payload -> normalized result (unit-testable vs a saved
    CxS fixture)."""
    info = payload.get("jobPostingInfo") or {}
    body = _html_to_text(html.unescape(info.get("jobDescription") or "")).strip()
    if not body:
        return None

    location = (info.get("location") or "").strip() or None
    req_loc = info.get("jobRequisitionLocation") or {}
    req_desc = (req_loc.get("descriptor") or "").strip() if isinstance(req_loc, dict) else ""
    org = payload.get("hiringOrganization") or {}
    company = (org.get("name") or "").strip() if isinstance(org, dict) else ""
    benefits, equity = mine_benefits_equity(body)
    remote_type = (info.get("remoteType") or "").strip() or None

    return {
        "title": (info.get("title") or "").strip() or "Unknown Title",
        "company": company or (urlparse(url or "").netloc.split(".")[0].title() or "Unknown"),
        "location": location,
        "working_location": location,
        "employment_type": (info.get("timeType") or "").strip() or None,
        "remote": True if (remote_type and "remote" in remote_type.lower()) else None,
        "workplace": remote_type,
        # Workday CxS never exposes pay; it is genuinely absent, not mis-parsed.
        "compensation": None,
        "compensation_raw": None,
        "location_raw": "; ".join(p for p in dict.fromkeys([location, req_desc]) if p) or None,
        "cadence_raw": None,
        "benefits": benefits,
        "equity": equity,
        "apply_url": info.get("externalUrl") or url,
        # Workday's `postedOn` is a RELATIVE string ("Posted 30 Days Ago") — unusable, and
        # normalize_posting_date rejects it rather than fabricating a date. `startDate` is a
        # real ISO date and is the only absolute date the CxS payload exposes, so it is the
        # fallback (nearest available publication signal, not a literal publish timestamp).
        **_dates(normalize_posting_date(info.get("postedOn")) or info.get("startDate")),
        "posting_id": (info.get("jobReqId") or info.get("id") or None),
        "source": "workday-cxs-api",
        "comp_expected": False,
        "location_expected": True,
        "structured_source": True,
        # The questionnaire is behind candidate auth (only `questionnaireId` is
        # public), so Workday application questions cannot be captured.
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


def _jsonld_org_name(hiring_organization) -> Optional[str]:
    """The employer name from schema.org `hiringOrganization` — a dict with `.name`, or a
    bare string. This is the ONE clean structured identity source on a generic career page
    (it used to be read and thrown away), so it is preferred over scraped page chrome."""
    if isinstance(hiring_organization, dict):
        name = hiring_organization.get("name") or hiring_organization.get("legalName")
        return str(name).strip() or None if name else None
    if isinstance(hiring_organization, str) and hiring_organization.strip():
        return hiring_organization.strip()
    return None


def extract_jsonld_jobposting(html_text: str) -> Optional[dict]:
    """Scan <script type="application/ld+json"> blocks for a schema.org JobPosting and
    return {"location", "employment_type", "compensation", "hiring_organization", "title"}
    (each str|None), or None if no JobPosting block is found. Handles a bare object, an
    @graph array, or a top-level JSON array of blocks.

    The RETURN-NONE criterion is deliberately unchanged (still keyed on location /
    employment_type / compensation): callers set `structured_source: bool(jobposting)`, so
    adding identity to the criterion would silently change which captures count as a
    structured source. Identity simply rides along on the dicts we already return.

    BUG FIX (2026-07-29): the parameter used to be named `html`, which SHADOWED the stdlib
    `html` module this function calls — `html.unescape(...)` raised AttributeError on the
    str, the bare `except Exception: continue` swallowed it, and the function therefore
    returned None for EVERY page. JSON-LD capture has silently never worked. The parameter
    is now `html_text` so the module reference resolves (both callers pass positionally)."""
    import json as _json

    for raw in _JSONLD_RE.findall(html_text or ""):
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
                return {
                    "location": location,
                    "employment_type": employment_type,
                    "compensation": comp,
                    "hiring_organization": _jsonld_org_name(node.get("hiringOrganization")),
                    "title": (str(node.get("title")).strip() or None) if node.get("title") else None,
                    # The only posting date a generic career page reliably publishes.
                    "posted_date": normalize_posting_date(node.get("datePosted")),
                    "updated_date": normalize_posting_date(node.get("dateModified")),
                }
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
    # Workday is the exception: the org lives in the HOST (the tenant subdomain),
    # while the first path segment is the job-posting SITE id ("WG", "Careers"),
    # which is not a company name.
    if "myworkdayjobs.com" in host and host_parts:
        return _prettify_slug(host_parts[0])
    skip = {"embed", "job_app", "jobs", "job", "j", "o", "careers", "career", "apply"}
    path_parts = [unquote(p) for p in parsed.path.split("/") if p]
    slug = next((s for s in path_parts if s.lower() not in skip), None)
    if not slug:
        slug = (parse_qs(parsed.query).get("for") or [None])[0]
    return _prettify_slug(slug) if slug else None


_OG_SITE_NAME_RE = re.compile(
    r'(?is)<meta[^>]+(?:property|name)\s*=\s*["\']og:site_name["\'][^>]*'
    r'content\s*=\s*["\']([^"\']+)["\']')
_OG_SITE_NAME_ALT_RE = re.compile(
    r'(?is)<meta[^>]+content\s*=\s*["\']([^"\']+)["\'][^>]*'
    r'(?:property|name)\s*=\s*["\']og:site_name["\']')


def employer_declared_name(html_text: Optional[str] = None,
                           jsonld: Optional[dict] = None) -> Optional[str]:
    """The employer's OWN declared name from their careers page, in confidence order:
    JSON-LD `hiringOrganization.name` (or an Organization `name`), then
    `og:site_name`. Returns None when the page declares neither.

    Why this exists: a board TOKEN title-cased into one word ("helpscout" ->
    "Helpscout") is a guess, and several ATS APIs expose no organization name at all.
    When the posting lives on the employer's own domain, the page itself is the better
    authority for how the company spells its name ("Help Scout")."""
    for key in ("hiring_organization", "hiringOrganization", "organization"):
        val = (jsonld or {}).get(key)
        if isinstance(val, dict):
            val = val.get("name")
        if isinstance(val, str) and val.strip():
            return re.sub(r"\s+", " ", val).strip()
    src = str(html_text or "")
    for rx in (_OG_SITE_NAME_RE, _OG_SITE_NAME_ALT_RE):
        m = rx.search(src)
        if m:
            name = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip()
            if name:
                return name
    return None


def _prettify_slug(slug: str) -> str:
    s = re.sub(r"[-_]+", " ", slug).strip()
    # Title-case but keep existing capitalization for already-cased words.
    return " ".join(w if w[:1].isupper() else w.capitalize() for w in s.split()) or slug


# --------------------------------------------------------------------------- #
# HTML -> text, STRUCTURE-PRESERVING (2026-07-29 spec): the employer's own list
# structure survives into the captured body — `<ul>/<ol>/<li>` become `- item` /
# `1. item` lines (nested lists indented two spaces per level), headings and
# paragraphs stay blank-line separated, link TEXT is kept. Nothing is invented:
# prose is never bulleted, wording is never altered, no text is dropped.
# --------------------------------------------------------------------------- #
_HTML_LIST_TAGS = {"ul", "ol"}
_HTML_BLOCK_TAGS = {
    "p", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "table", "tr",
    "header", "footer", "section", "article", "div", "main", "aside", "figure",
    "figcaption", "body", "html",
}


# A single <br /> is a LINE BREAK inside its block; a <br /><br /> run is a
# PARAGRAPH BREAK (new block). The sentinel survives whitespace collapsing so
# the distinction reaches the renderer intact.
_BR_SENTINEL = "\x00"
_PARA_BREAK_RE = re.compile(rf"(?:{_BR_SENTINEL}[ \t]*){{2,}}")


def _segment_lines(segment: str) -> list[str]:
    """Clean lines of one paragraph segment: single-<br> sentinels and embedded
    newlines become line boundaries; horizontal whitespace collapses."""
    lines: list[str] = []
    for part in segment.split(_BR_SENTINEL):
        for raw in part.split("\n"):
            ln = re.sub(r"[ \t]+", " ", raw).strip()
            if ln:
                lines.append(ln)
    return lines


def _render_html_list(tag, depth: int) -> str:
    """A <ul>/<ol> as `- item` / `1. item` lines; nested lists indent 2 spaces
    per level. A single <br> inside an item is a line break (continuation line,
    indented under the item — never a new bullet); a <br><br> run, or any
    further block-level element an ATS nests inside the item (the observed
    Ashby shape: `Role Details:` + employment/cadence paragraphs + a nested
    comp list jammed into the final <li>), ends the item's text — the rest
    renders as its own blank-line-separated blocks IN DOCUMENT ORDER, never
    fused onto the bullet."""
    from bs4 import NavigableString, Tag

    ordered = tag.name.lower() == "ol"
    indent = "  " * depth
    out_parts: list[str] = []
    for i, li in enumerate(tag.find_all("li", recursive=False), 1):
        marker = f"{i}." if ordered else "-"
        item_lines: list[str] = []      # the bullet's own text (+ continuations)
        tail_blocks: list[str] = []     # everything after the item text, in order
        inline_buf: list[str] = []

        def flush():
            raw = "".join(inline_buf)
            inline_buf.clear()
            for seg in _PARA_BREAK_RE.split(raw):
                seg_lines = _segment_lines(seg)
                if not seg_lines:
                    continue
                if not item_lines and not tail_blocks:
                    item_lines.extend(seg_lines)
                else:
                    tail_blocks.append("\n".join(seg_lines))

        def walk(node):
            for c in node.children:
                if isinstance(c, NavigableString):
                    inline_buf.append(str(c))
                elif isinstance(c, Tag):
                    n = c.name.lower()
                    if n in ("script", "style", "noscript"):
                        continue
                    if n == "br":
                        inline_buf.append(_BR_SENTINEL)
                    elif n in _HTML_LIST_TAGS:
                        flush()
                        rendered = _render_html_list(c, depth + 1)
                        if rendered:
                            tail_blocks.append(rendered)
                    elif c.find(list(_HTML_LIST_TAGS)) is not None:
                        walk(c)  # block wrapper holding a list — recurse in order
                    elif n in _HTML_BLOCK_TAGS:
                        flush()
                        blocks = [b for b in _html_blocks(c, 0) if b.strip()]
                        # The item's own text is the FIRST block (its internal
                        # single-<br> line breaks become continuation lines);
                        # everything after is separate, in document order.
                        if not item_lines and not tail_blocks and blocks:
                            item_lines.extend(blocks.pop(0).split("\n"))
                        tail_blocks.extend(blocks)
                    else:
                        inline_buf.append(c.get_text(" "))
            flush()

        walk(li)
        first = item_lines[0] if item_lines else ""
        bullet = [f"{indent}{marker} {first}".rstrip()]
        bullet += [f"{indent}  {cont}" for cont in item_lines[1:]]
        piece = "\n".join(bullet)
        for block in tail_blocks:
            # A nested list stays adjacent to its item; plain blocks are
            # blank-line separated (a heading gets its own paragraph).
            if block.lstrip().startswith(("-", "1.")) and block.startswith("  " * (depth + 1)):
                piece += "\n" + block
            else:
                piece += "\n\n" + block
        out_parts.append(piece)
    return "\n".join(out_parts)


def _html_blocks(node, depth: int = 0) -> list[str]:
    """Block-level text pieces of a node, in document order. Lists render via
    `_render_html_list`; paragraph-ish content collapses internal whitespace."""
    from bs4 import NavigableString, Tag

    out: list[str] = []
    inline_buf: list[str] = []

    def flush():
        raw = "".join(inline_buf)
        inline_buf.clear()
        # A <br><br> run splits the buffered inline flow into separate blocks;
        # a single <br> becomes a line break within its block.
        for seg in _PARA_BREAK_RE.split(raw):
            text = "\n".join(_segment_lines(seg))
            if text:
                out.append(text)

    for c in node.children:
        if isinstance(c, NavigableString):
            inline_buf.append(str(c))
        elif isinstance(c, Tag):
            n = c.name.lower()
            if n in ("script", "style", "noscript"):
                continue
            if n == "br":
                inline_buf.append(_BR_SENTINEL)
            elif n in _HTML_LIST_TAGS:
                flush()
                rendered = _render_html_list(c, depth)
                if rendered:
                    out.append(rendered)
            elif n in _HTML_BLOCK_TAGS:
                flush()
                out.extend(_html_blocks(c, depth))
            else:
                # Inline tag (a/strong/em/span/…): text only — a link keeps its text.
                inline_buf.append(c.get_text(" "))
    flush()
    return out


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    try:
        from bs4 import Comment, BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        # HTML comments are never job content, but bs4 will happily hand their text back —
        # a page with a large comment block leaks it straight into the captured job text.
        for c in soup.find_all(string=lambda s: isinstance(s, Comment)):
            c.extract()
        text = "\n\n".join(_html_blocks(soup))
    except Exception:
        # Crude tag strip if bs4 is unavailable.
        text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
