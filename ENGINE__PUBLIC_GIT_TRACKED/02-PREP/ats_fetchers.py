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
- Ashby (jobs.ashbyhq.com) via the public posting-api job board feed.
- LinkedIn (linkedin.com/jobs) via the logged-out "guest" jobPosting endpoint.

To add another ATS, write a `_fetch_<name>` function returning the same dict
shape and register it in `fetch_via_ats`.
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
#     "location": str | None,
#     "employment_type": str | None,
#     "remote": bool | None,
#     "compensation": str | None,
#     "apply_url": str | None,
#     "text": str,          # the body the caller writes out
#     "source": str,        # e.g. "ashby-posting-api"
#   }


def fetch_via_ats(url: str, timeout: int = 20) -> Optional[dict]:
    """Dispatch to the matching ATS fetcher, or return None if unrecognized."""
    host = urlparse(url).netloc.lower()
    try:
        if host.endswith("ashbyhq.com"):
            return _fetch_ashby(url, timeout=timeout)
        if host.endswith("greenhouse.io"):
            return _fetch_greenhouse(url, timeout=timeout)
        if host.endswith("lever.co"):
            return _fetch_lever(url, timeout=timeout)
        if "linkedin.com" in host:
            return _fetch_linkedin(url, timeout=timeout)
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

    body = (job.get("descriptionPlain") or "").strip()
    if not body:
        body = _html_to_text(job.get("descriptionHtml") or "")
    if not body:
        return None

    comp = None
    c = job.get("compensation") or {}
    if isinstance(c, dict):
        comp = c.get("compensationTierSummary") or c.get(
            "scrapeableCompensationSalarySummary"
        )

    company = _prettify_slug(org)
    text = _compose_ashby_text(job, body, comp)

    return {
        "title": (job.get("title") or "").strip() or "Unknown Title",
        "company": company,
        "location": job.get("location"),
        "employment_type": job.get("employmentType"),
        "remote": job.get("isRemote"),
        "compensation": comp,
        "apply_url": job.get("applyUrl") or job.get("jobUrl"),
        "text": text,
        "source": "ashby-posting-api",
    }


def _compose_ashby_text(job: dict, body: str, comp: Optional[str]) -> str:
    """Prepend a compact metadata block (useful for vetting) to the description."""
    lines = []
    if job.get("location"):
        lines.append(f"Location: {job['location']}")
    if job.get("employmentType"):
        lines.append(f"Employment Type: {job['employmentType']}")
    if job.get("isRemote") is not None:
        lines.append(f"Remote: {'Yes' if job['isRemote'] else 'No'}")
    if comp:
        lines.append(f"Compensation: {comp}")
    header = "\n".join(lines)
    return f"{header}\n\n{body}".strip() if header else body


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
        params={"questions": "false"},
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    if resp.status_code != 200:
        return None
    job = resp.json()

    raw = job.get("content") or ""
    body = _html_to_text(html.unescape(raw))
    if not body:
        return None

    loc = job.get("location") or {}
    location = loc.get("name") if isinstance(loc, dict) else (loc or None)

    company = _greenhouse_company(board, timeout) or _prettify_slug(board)

    header = f"Location: {location}" if location else ""
    text = f"{header}\n\n{body}".strip() if header else body

    return {
        "title": (job.get("title") or "").strip() or "Unknown Title",
        "company": company,
        "location": location,
        "employment_type": None,
        "remote": None,
        "compensation": None,
        "apply_url": job.get("absolute_url") or url,
        "text": text,
        "source": "greenhouse-boards-api",
    }


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
    text = _compose_lever_text(location, employment_type, comp, body)

    return {
        "title": (job.get("text") or "").strip() or "Unknown Title",
        "company": company,
        "location": location,
        "employment_type": employment_type,
        "remote": None,
        "compensation": comp,
        "apply_url": job.get("applyUrl") or job.get("hostedUrl") or url,
        "text": text,
        "source": "lever-postings-api",
    }


def _compose_lever_text(location, employment_type, comp, body: str) -> str:
    lines = []
    if location:
        lines.append(f"Location: {location}")
    if employment_type:
        lines.append(f"Employment Type: {employment_type}")
    if comp:
        lines.append(f"Compensation: {comp}")
    header = "\n".join(lines)
    return f"{header}\n\n{body}".strip() if header else body


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
