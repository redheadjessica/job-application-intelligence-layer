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

import fcntl
import hashlib
import json
import os
import re
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from html import unescape as html_unescape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo

from ats_fetchers import (
    ATS_HOST_KEYWORDS,
    MENTIONED_NO_DETAILS,
    UUID_RE,
    _EQUITY_SPECIFICS_RE,
    _gh_board_tokens_from_domain,
    _greenhouse_ids,
    _linkedin_job_id,
    _prettify_slug,
    mine_benefits_equity,
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


# --------------------------------------------------------------------------- #
# Captured-identity normalization — `company-name__job-title.txt` (spec 2026-07-29)
#
# Every fetch path (ATS API / requests / playwright / JSON-LD / embedded-GH recovery)
# funnels its (company, title) pair through `normalize_capture_identity` at the ONE choke
# point in `process_urls`, so a posting gets the same filename and the same
# `Company:`/`Role:` header regardless of which method won the race. That single
# insertion point is what makes it idempotent per URL: re-normalizing an already-clean
# identity is a no-op.
#
# The regression this fixes: careers.airbnb.com produced BOTH
# `careers-at-airbnb__product-manager-incubations.txt` (playwright: `best_company_from_title`
# accepted "Careers at Airbnb" as the company) AND
# `product-manager-incubations__product-manager-incubations.txt` (requests: `detect_company`
# rejected the career-y segment and fell through to the ROLE segment). The only correct name
# is `airbnb__product-manager-incubations.txt`.
# --------------------------------------------------------------------------- #

# "Careers at X" / "Jobs at X" prefix and "X Careers" / "X Jobs" suffix wrappers.
_CO_WRAPPER_PREFIX_RE = re.compile(r"^(?:careers?|jobs?)\s+at\s+", re.I)
_CO_WRAPPER_SUFFIX_RE = re.compile(r"[\s|·]+(?:careers?|jobs?)$", re.I)
# Any residual site-branding word means the value is chrome, not an employer name.
_CAREERY_RE = re.compile(r"\b(careers?|jobs?)\b", re.I)
# Separator between a real title and a trailing site-branding suffix.
_BRAND_SEP = r"\s*[|\-–—·]\s*"
# "<Role> - Careers at <Co>" / "<Role> — Jobs at <Co>"
_TITLE_SUFFIX_AT_RE = re.compile(
    rf"{_BRAND_SEP}(?:careers?|jobs?)\s+at\s+(?P<co>[^|\-–—·]+?)\s*$", re.I)
# "<Role> | <Co> Careers" / "<Role> - <Co> Jobs"
_TITLE_SUFFIX_CO_RE = re.compile(
    rf"{_BRAND_SEP}(?P<co>[^|\-–—·]+?)\s+(?:careers?|jobs?)\s*$", re.I)
# "<Role> | Careers" / "<Role> - Jobs" (branding with no employer name in it)
_TITLE_SUFFIX_BARE_RE = re.compile(rf"{_BRAND_SEP}(?:careers?|jobs?)\s*$", re.I)
# Job-board hosts that are never the employer (the ATS hosts are handled separately).
_BOARD_HOSTS = {
    "linkedin", "indeed", "glassdoor", "ziprecruiter", "wellfound", "angellist",
    "builtin", "otta", "dice", "monster", "simplyhired", "google", "jobs",
}
# Domain labels that are site structure, never a company name.
_DOMAIN_CHROME = {
    "careers", "career", "jobs", "job", "www", "apply", "boards", "board", "work",
    "hire", "hiring", "talent", "recruiting", "join", "my", "app", "web",
}
_PSEUDO_TLDS = {"co", "com", "org", "net", "gov", "edu", "ac"}


def _clean_company_wrappers(name: str) -> str:
    """Strip `Careers at X` / `Jobs at X` / `X Careers` / `X Jobs` wrappers (case-
    insensitive, iteratively) and any stray separator punctuation left behind."""
    s = re.sub(r"\s+", " ", str(name or "").strip())
    for _ in range(4):
        before = s
        s = _CO_WRAPPER_PREFIX_RE.sub("", s)
        s = _CO_WRAPPER_SUFFIX_RE.sub("", s)
        s = s.strip(" \t|·:,-–—")
        if s == before:
            break
    s = re.sub(r"\s+", " ", s).strip()
    # A name we DERIVED by stripping a wrapper often comes out of lowercase page chrome
    # ("careers at airbnb" -> "airbnb"); title-case it so the header and the filename agree
    # with every other route. A company that arrived already cased is left alone.
    if s and s != str(name or "").strip() and not any(ch.isupper() for ch in s):
        s = _prettify_slug(s)
    return s


def _strip_title_branding(title: str) -> tuple[str, str | None]:
    """Remove site-branding suffixes from a page/job title. Returns
    (clean_title, employer_name_recovered_from_the_suffix_or_None) — the suffix often
    NAMES the employer ("- Careers at Airbnb"), which is the best company signal a
    scraped page offers."""
    s = re.sub(r"\s+", " ", str(title or "").strip())
    wrapper_co = None
    for _ in range(3):
        before = s
        for rx in (_TITLE_SUFFIX_AT_RE, _TITLE_SUFFIX_CO_RE):
            m = rx.search(s)
            if m and m.start() > 0:
                co = _clean_company_wrappers(m.group("co"))
                if co and not _CAREERY_RE.search(co):
                    wrapper_co = wrapper_co or co
                s = s[:m.start()].strip(" \t|·:,-–—")
                break
        else:
            m = _TITLE_SUFFIX_BARE_RE.search(s)
            if m and m.start() > 0:
                s = s[:m.start()].strip(" \t|·:,-–—")
        if s == before:
            break
    return re.sub(r"\s+", " ", s).strip(), wrapper_co


def _company_from_domain(url: str | None) -> str | None:
    """Employer name derived from the URL host (`careers.airbnb.com` -> `Airbnb`). Returns
    None for ATS hosts and job boards, whose host names the platform, not the employer."""
    host = urlparse(url or "").netloc.lower().replace("www.", "")
    labels = [p for p in host.split(".") if p]
    if len(labels) < 2:
        return None
    idx = len(labels) - 2
    if labels[idx] in _PSEUDO_TLDS and len(labels) >= 3:  # example.co.uk
        idx -= 1
    label = labels[idx]
    if label in _DOMAIN_CHROME:
        return None
    if label in ATS_HOST_KEYWORDS or label in _BOARD_HOSTS:
        # A big-company domain can be BOTH a job board and its own employer careers site
        # (google.com/search/jobs vs google.com/about/careers/...). On an explicit `/careers`
        # path the host does name the employer — without this, a careers-site posting whose
        # title is also its company had no alternative name at all, so the ROLE stayed in the
        # company slot and the filename doubled it (`<role>__<role>.txt`).
        if not re.search(r"/careers(?:/|$)", urlparse(url or "").path, re.I):
            return None
    return _prettify_slug(label)


def _identity_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


# --------------------------------------------------------------------------- #
# "Never company-as-role" — the guard symmetric to never-role-as-company.
#
# The regression: a JS-rendered careers site (metacareers.com) whose <title>/og:title is
# pure site branding produced `Company: Meta Careers` / `Role: Meta Careers` and the
# filename `meta-careers__meta-careers.txt`. Cleaning the COMPANY was not enough — the
# role was still branding. A title that is site chrome must be RECOVERED from the page
# (JSON-LD title -> first <h1> -> first non-navigation heading in the extracted body),
# and if recovery fails the title is marked a CAPTURE FAILURE (field_status `title`
# -> capture_failed) so the completeness gate and the prep report say so loudly, rather
# than a branding string being minted into a filename as if it were a job title.
# --------------------------------------------------------------------------- #

# "Careers at X" / "Jobs | X" — a branding wrapper occupying the WHOLE string.
_BRAND_ONLY_PREFIX_RE = re.compile(rf"^(?:careers?|jobs?)(?:\s+at\s+|{_BRAND_SEP})", re.I)
# Words that only ever appear in site navigation / page chrome, never alone in a job
# title. A line whose every word is in this set (plus the employer's own name) is nav.
_NAV_WORDS = {
    "a", "about", "accessibility", "alerts", "all", "an", "and", "apply", "at", "back",
    "benefits", "blog", "blogs", "board", "career", "careers", "content", "contact",
    "cookie", "cookies", "culture", "current", "diversity", "employees", "events",
    "faq", "faqs", "for", "found", "help", "home", "hiring", "in", "internships",
    "investors", "job", "jobs", "join", "language", "life", "listings", "locations",
    "location", "log", "login", "logout", "main", "menu", "more", "news", "now", "of",
    "offices", "open", "openings", "or", "our", "out", "overview", "people", "podcast",
    "podcasts", "policy", "positions", "press", "privacy", "profile", "program",
    "programs", "resources", "results", "roles", "saved", "search", "sign", "skip",
    "students", "team", "teams", "terms", "the", "to", "up", "us", "view", "we",
    "work", "working", "detail", "details", "description", "result", "results", "search",
    "share", "link", "copy", "print", "email",
}


# Generic ATS/careers PAGE titles that name the page, not the job. Matched exactly (after
# lowercasing + punctuation strip) so a real title is never caught by them.
_GENERIC_PAGE_TITLES = {
    "job details", "job detail", "details", "job description", "job posting", "job post",
    "job opening", "job openings", "position details", "position description",
    "opportunity details", "open positions", "open roles", "current openings",
    "job search", "search jobs", "apply now", "view job", "job", "jobs", "careers",
}


def _is_branding_only(text: str) -> bool:
    """True when a string is a careers-site branding label rather than a job title —
    "Meta Careers", "Careers at Acme", "Jobs — Acme", bare "Careers"/"Jobs".
    Deliberately narrow: only strings of at most 3 words qualify, so a real title that
    happens to contain the word "Careers" ("PM, Careers Platform Experience") is safe."""
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if not s:
        return True
    if re.sub(r"\s+", " ", re.sub(r"[^a-z ]+", " ", s.lower())).strip() in _GENERIC_PAGE_TITLES:
        return True
    words = [w for w in re.split(r"[^A-Za-z0-9'&]+", s) if w]
    # A short label built ENTIRELY of page-navigation vocabulary is chrome, not a role.
    # This is what generalizes past a fixed list: the same careers SPA served "job details"
    # on one visit and "Jobs search results" on the next.
    if words and len(words) <= 4 and all(w.lower() in _NAV_WORDS for w in words):
        return True
    if len(s.split(" ")) > 3:
        return False
    return bool(_BRAND_ONLY_PREFIX_RE.match(s) or _CO_WRAPPER_SUFFIX_RE.search(s))


def _title_is_branding(title: str) -> bool:
    """The title carries no role information at all: missing, or pure site branding.
    This is the DEFINITE failure — worth a full page rescan to recover a real title."""
    s = str(title or "").strip()
    return (not s) or s == "Unknown Title" or _is_branding_only(s)


def _title_is_invalid(title: str, company: str) -> bool:
    """Branding, or the same slug as the company (company-as-role). A plain collision is
    ambiguous — it can equally mean the COMPANY is wrong — so callers distinguish it from
    `_title_is_branding` and never rewrite such a title from loose page text."""
    if _title_is_branding(title):
        return True
    k = _identity_key(title)
    return bool(k) and k == _identity_key(company)


def _headings_from_html(html: str | None) -> list[str]:
    """<h1> text from a page's markup, tags stripped. A regex (not a parser) keeps
    prep_common dependency-free — this reads only heading text.

    Deliberately h1-ONLY. h2 is not a title signal on a real careers page: one observed
    page's h1 was "job details" and its h2 list ran "Jobs search results", "Follow Life at
    <Employer> on", "More about us" — footer chrome that would outrank the body's own first
    content line. (The primary fetch path already handles the branded-h1-then-real-h2 shape
    separately, in `extract_title`.)"""
    out: list[str] = []
    # Comments are markup, not content — and a comment mentioning a tag would otherwise
    # open a match that runs on until the real closing tag.
    src = re.sub(r"<!--.*?-->", " ", str(html or ""), flags=re.S)
    for level in ("h1",):
        for m in re.finditer(rf"<{level}\b[^>]*>(.*?)</{level}>", src, re.I | re.S):
            txt = re.sub(r"<[^>]+>", " ", m.group(1))
            txt = re.sub(r"\s+", " ", html_unescape(txt)).strip()
            if txt:
                out.append(txt)
    return out


# Job-description SECTION headers. These are the most likely wrong answer when scanning
# body text for a title, so they are rejected outright — a flagged capture failure beats a
# capture whose `Role:` line says "About the role".
_SECTION_HEADERS = {
    "about the role", "about the job", "about this role", "about this job", "about us",
    "about the team", "about the company", "the role", "the opportunity", "job description",
    "role description", "position summary", "overview", "summary", "responsibilities",
    "key responsibilities", "what you'll do", "what you will do", "what youll do",
    "qualifications", "minimum qualifications", "preferred qualifications", "requirements",
    "who you are", "what we're looking for", "what we are looking for", "nice to have",
    "benefits", "perks", "compensation", "salary", "pay transparency", "how to apply",
    "equal opportunity employer", "our mission", "why join us", "your impact",
}


def _first_content_heading(body: str | None, names: list[str]) -> str | None:
    """The first line of extracted body text that reads as a job title rather than
    navigation chrome or a JD section header. On the metacareers capture the body opens
    with "Skip to main content / Jobs / Teams / Career Programs / Working at Meta / Blog /
    Podcasts / Jobs" and then the real title, "Product Manager, Central Product"."""
    # The employer's own name(s) count as nav vocabulary only IN COMBINATION with a real nav
    # word ("Working at <Co>"). They can't stand alone as the test: when the company slot
    # holds the ROLE text, its words would otherwise mask the real title line.
    own = set()
    for name in names:
        own |= {w for w in re.split(r"[^a-z0-9]+", str(name or "").lower()) if w}
    nav = _NAV_WORDS | own
    for raw in str(body or "").splitlines()[:60]:
        ln = re.sub(r"\s+", " ", raw).strip(" \t|·:-–—")
        if not (6 <= len(ln) <= 120) or ln.endswith("."):  # a title is not a sentence
            continue
        if re.sub(r"[^a-z' ]+", "", ln.lower()).strip() in _SECTION_HEADERS:
            continue
        # Run-together case ("linkCopy link", "emailEmail a friend") is icon/label markup
        # collapsed by text extraction, never a real job title.
        if re.search(r"[a-z][A-Z]", ln):
            continue
        words = [w for w in re.split(r"[^A-Za-z0-9'&]+", ln) if w]
        low = [w.lower() for w in words]
        if len(words) < 2:
            continue
        if all(w in nav for w in low) and any(w in _NAV_WORDS for w in low):
            continue
        # Branding lines are skipped, but a line that merely MATCHES the "company" is kept:
        # when the title is branding, a company slot holding the same string as the body's
        # first content line is evidence the ROLE text landed in the company field, and the
        # role-as-company guard downstream is what repairs that.
        if _title_is_branding(ln):
            continue
        return ln
    return None


def _recover_title(jsonld: dict, html: str | None, body: str | None,
                   names: list[str], *, scan_body: bool = True) -> str | None:
    """Recover a real job title for a capture whose scraped title was branding.
    In order: JSON-LD `title`, the page's first heading, the first non-navigation
    heading line of the extracted body text. Returns None rather than inventing one.

    `names` is every name this employer is known by here (the cleaned company plus any
    domain-derived form) — a heading made only of nav words plus one of those names
    ("Working at Meta") is chrome, not a title.

    `scan_body=False` restricts recovery to the two HIGH-CONFIDENCE structured sources.
    Used when the title merely COLLIDES with the company: that can equally mean the company
    is the wrong one, and a loose body line is not good enough evidence to overwrite a
    title that may well be correct."""
    names = [n for n in names if str(n or "").strip()]
    candidates: list[str] = [str((jsonld or {}).get("title") or "")]
    candidates += _headings_from_html(html)
    heading = _first_content_heading(body, names) if scan_body else None
    if heading:
        candidates.append(heading)
    for cand in candidates:
        c = re.sub(r"\s+", " ", str(cand or "").strip())
        if not c:
            continue
        clean, _ = _strip_title_branding(c)
        clean = clean.strip()
        if clean and not _title_is_branding(clean):
            return clean
    return None


def _strip_trailing_company_echo(title: str, company: str) -> str:
    """Drop a trailing ` - <Company>` / ` | <Company>` echo from a title."""
    if not company or not title:
        return title
    m = re.search(rf"{_BRAND_SEP}{re.escape(company)}\s*$", title, re.I)
    if m and m.start() > 0:
        return title[:m.start()].strip(" \t|·:,-–—")
    return title


def normalize_capture_identity(company: str | None, title: str | None, url: str | None = None,
                               jsonld: dict | None = None, html: str | None = None,
                               body: str | None = None) -> tuple[str, str]:
    """Canonical (company, title) for a captured job post — the single normalizer behind
    the `company-name__job-title.txt` filename and the `Company:`/`Role:` header lines.

    Order of operations:
      1. Prefer structured JSON-LD identity (`hiringOrganization.name` / `title`).
      2. Strip site-branding suffixes from the title, remembering any employer name the
         suffix carried ("- Careers at Airbnb" -> Airbnb).
      3. Strip `Careers at X` / `X Jobs` wrappers from the company.
      4. If the company is empty or still career-y, use the suffix-derived name, else a
         domain-derived one.
      5. NEVER role-as-company: if the cleaned company equals (or contains / is contained
         by) the cleaned title, replace it with the suffix- or domain-derived name — but
         only when such an alternative actually exists (conservative: never invent one).
      6. NEVER company-as-role (symmetric guard): if the cleaned title is site branding
         ("Meta Careers", "Careers at X") or slugs to the same value as the company,
         RECOVER it from JSON-LD `title`, then the page's first heading, then the first
         non-navigation heading line of the extracted body. If nothing is recoverable the
         title becomes "Unknown Title", which `assess_completeness` records as
         `title: capture_failed` — a loud flag, never an invented or branding filename.

    Idempotent: an already-clean pair passes through unchanged.
    """
    jsonld = jsonld if isinstance(jsonld, dict) else {}
    raw_company = str(company or "").strip()
    raw_title = str(title or "").strip()
    j_co = str(jsonld.get("hiring_organization") or "").strip()
    j_title = str(jsonld.get("title") or "").strip()
    if j_co:
        raw_company = j_co
    if j_title:
        raw_title = j_title

    clean_title, wrapper_co = _strip_title_branding(raw_title)
    clean_company = _clean_company_wrappers(raw_company)
    domain_co = _company_from_domain(url)

    if not clean_company or _CAREERY_RE.search(clean_company):
        clean_company = wrapper_co or domain_co or clean_company
    clean_title = _strip_trailing_company_echo(clean_title, clean_company)

    # NEVER company-as-role. Attempted BEFORE the role-as-company swap below: when the two
    # values collide, recovering a real title from the page tells us which of the pair was
    # actually broken, so a good company name isn't thrown away to fix a bad title.
    names = [n for n in (clean_company, domain_co, wrapper_co) if n]
    if _title_is_invalid(clean_title, clean_company):
        recovered = _recover_title(jsonld, html, body, names,
                                   scan_body=_title_is_branding(clean_title))
        if recovered:
            clean_title = recovered

    # NEVER role-as-company. A company that is merely a SUBSTRING of a longer title is not
    # role-as-company: "Director, Product Management, ClassPass Consumer" legitimately names
    # its employer, and swapping in a domain-derived parent-company name there replaced a
    # correct, ATS-authoritative employer name with one the user wouldn't recognize. Require
    # the company to account for most of the title before treating it as the role.
    ck, tk = _identity_key(clean_company), _identity_key(clean_title)
    substantial = bool(ck) and bool(tk) and min(len(ck), len(tk)) >= 0.5 * max(len(ck), len(tk))
    if ck and tk and (ck == tk or (substantial and (ck in tk or tk in ck))):
        for alt in (wrapper_co, domain_co):
            if alt and _identity_key(alt) != tk:
                clean_company = alt
                break

    # Still branding: fail loudly rather than mint a filename out of site chrome.
    # "Unknown Title" is what assess_completeness reads as capture_failed. An UNRESOLVED
    # collision is deliberately NOT failed here — the title is probably the real role and
    # the company is the duplicated half, so keeping the role text loses less.
    if _title_is_branding(clean_title):
        clean_title = ""

    return (clean_company or "Unknown", clean_title or "Unknown Title")


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
# BASE-salary keywords only. "ote" and "total comp" were removed (2026-07-29): a
# variable-pay figure is NOT base salary, and letting those keywords qualify a range meant
# an OTE number could become the captured comp value and flow into the Comp Range envelope.
# Bonus/commission/OTE/equity stay separate (they're preserved in the archival block and in
# `mine_benefits_equity`), never merged into base.
_SALARY_KEYWORDS = (
    "salary", "compensation", "pay range", "pay for", "base pay", "base salary",
    "annual", "annually", "per year", "/year", "/yr", "a year",
    "target cash", "range for this", "hiring range", "wage",
)


def _prose_compensation_all(body: str) -> list[dict]:
    """EVERY employer pay range written into the JD prose, in document order, as
    `[{"value": "<range>", "line": "<the source line, verbatim>"}, ...]`.

    Collecting all of them (this used to stop at the first match) is what lets a
    multi-zone prose posting feed the full applicable-bands envelope instead of
    collapsing to whichever band happened to appear first. The verbatim `line` is
    preserved machine-readably (via field_status into the manifest); the capture's
    Base Salary bullets are built from these values when no structured field carried comp.
    """
    if not body:
        return []
    # Scan the whitespace-collapsed body (so a keyword and its range can sit on different
    # source lines, as they routinely do), then map each match back to its own line for the
    # verbatim record.
    text = re.sub(r"\s+", " ", body)
    low = text.lower()
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in body.splitlines()]
    lines = [ln for ln in lines if ln]
    out: list[dict] = []
    seen: set[str] = set()
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
        if not (has_cur or (has_comma_or_k and has_kw)):
            continue
        value = re.sub(r"\s+", " ", m.group(0)).strip()
        key = _norm_val(value)
        if key in seen:
            continue
        seen.add(key)
        source_line = next((ln for ln in lines if value in ln), value)
        out.append({"value": value, "line": source_line})
    return out


def _prose_compensation(body: str) -> str | None:
    """The FIRST employer pay figure written into the JD prose (back-compatible single
    value; `_prose_compensation_all` returns every match). Returns a cleaned range
    string, or None."""
    found = _prose_compensation_all(body)
    return found[0]["value"] if found else None


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


def _prose_city_states(body: str, limit: int = 6) -> list[str]:
    """EVERY distinct "City, ST" the JD prose names, in document order (deduped, capped).

    This used to return only the FIRST match, which silently dropped employer-listed
    offices — an Airbnb posting listing both San Francisco, CA and New York, NY came out
    as SF only. The archival capture must preserve every office the employer listed."""
    out: list[str] = []
    seen: set[str] = set()
    for cm in _CITY_STATE_RE.finditer(body or ""):
        if cm.group(2) not in _US_STATES:
            continue
        place = f"{cm.group(1)}, {cm.group(2)}"
        key = place.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(place)
        if len(out) >= limit:
            break
    return out


def _prose_working_location_detail(body: str) -> tuple[str | None, str | None]:
    """(value, verbatim_source_line) for the job location/cadence written into the JD
    prose. The verbatim line rides into the manifest via field_status when no
    structured location field exists."""
    if not body:
        return None, None

    def _line_for(needle: str) -> str | None:
        for raw in (body or "").splitlines():
            ln = re.sub(r"\s+", " ", raw).strip()
            if ln and needle and needle.lower() in ln.lower():
                return ln
        return None

    m = _LOC_LABEL_RE.search(body)
    if m and m.group(1).strip():
        cleaned = _sanitize_location(m.group(1))
        if cleaned:
            return cleaned, re.sub(r"\s+", " ", m.group(0)).strip()
    m = _REMOTE_RE.search(body)
    if m:
        value = m.group(0).strip().rstrip(",(").strip().title()
        return value, _line_for(m.group(0).strip())
    cities = _prose_city_states(body)
    if cities:
        return "; ".join(cities), _line_for(cities[0])
    m = _CADENCE_RE.search(body)
    if m:
        return m.group(0).strip(), _line_for(m.group(0).strip())
    return None, None


def _prose_working_location(body: str) -> str | None:
    """Best-effort job location/cadence written into the JD prose: EVERY named "City, ST"
    (`"; "`-joined), a Remote/hybrid/onsite signal, or an explicit Location: line. Returns a
    short, validated snippet, or None. Every candidate is run through _sanitize_location so
    a nav-label leak ("Locations" -> "s") or a marketing tail never counts as found."""
    return _prose_working_location_detail(body)[0]


# --------------------------------------------------------------------------- #
# Conflict producers — "materially disagree" = DISJOINT envelopes
#
# The CONFLICTING status and the `[CONFLICT]:` line have existed for a while but were
# UNREACHABLE: nothing in production ever populated `compensation_sources` /
# `location_sources`, so a real ATS-vs-prose disagreement was never detected. These helpers
# are the missing producers. The bar is deliberately conservative — identical or merely
# overlapping figures must NOT flag (a posting that repeats its structured range in the
# prose is the common case, not a conflict); only genuinely disjoint readings do.
# --------------------------------------------------------------------------- #
def _thousands_envelope(text: str) -> tuple[float, float] | None:
    """(min, max) of every plausible base-salary figure in a comp string, in whole
    thousands. `$236K – $296K` -> (236, 296); `USD 213,000-266,000` -> (213, 266)."""
    vals: list[float] = []
    for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*([kK])?\b", str(text or "")):
        raw = m.group(1).replace(",", "")
        try:
            v = float(raw)
        except ValueError:
            continue
        if not m.group(2) and v >= 10000:
            v = v / 1000.0
        if not (10 <= v <= 2000):
            continue
        vals.append(v)
    return (min(vals), max(vals)) if vals else None


def _comp_materially_disagrees(structured: str, prose_values: list[str]) -> bool:
    """True only when the structured and prose comp envelopes are DISJOINT."""
    a = _thousands_envelope(structured)
    b = _thousands_envelope(" ".join(prose_values))
    if not a or not b:
        return False
    return a[1] < b[0] or b[1] < a[0]


def _location_materially_disagrees(structured: str, prose_cities: list[str]) -> bool:
    """True only when BOTH sides name "City, ST" places and the city sets are disjoint."""
    a = {c.split(",")[0].strip().lower() for c in _prose_city_states(str(structured or ""), limit=12)}
    b = {c.split(",")[0].strip().lower() for c in prose_cities}
    if not a or not b:
        return False
    return a.isdisjoint(b)


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
    comp_prose_all = _prose_compensation_all(body)
    comp_prose = comp_prose_all[0]["value"] if comp_prose_all else None
    if comp_prose_all:
        # Keep every prose band machine-readably (it rides into the manifest entry via
        # field_status) so the applicable-bands envelope isn't limited to the first match.
        fs["compensation_prose_all"] = [c["value"] for c in comp_prose_all]
        fs["compensation_prose_verbatim"] = comp_prose_all[0]["line"]
    # Conflict producer: a structured ATS figure AND a prose figure that materially
    # disagree (disjoint envelopes) -> synthesize the two sources so the CONFLICTING
    # branch below fires and BOTH readings are preserved, never silently picked.
    if len(comp_sources) < 2 and meta.get("compensation") and comp_prose_all:
        if _comp_materially_disagrees(meta["compensation"], fs.get("compensation_prose_all") or []):
            label = str(meta.get("source") or "structured")
            synthesized = [(label, str(meta["compensation"])),
                           ("description", "; ".join(fs["compensation_prose_all"]))]
            fs["compensation_sources"] = synthesized
            comp_sources = _distinct([s for _, s in synthesized])
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
    loc_prose, loc_prose_line = _prose_working_location_detail(body)
    if loc_prose_line:
        fs["working_location_prose_verbatim"] = loc_prose_line
    structured_loc = meta.get("working_location") or meta.get("location")
    if len(loc_sources) < 2 and structured_loc:
        prose_cities = _prose_city_states(body)
        if _location_materially_disagrees(structured_loc, prose_cities):
            label = str(meta.get("source") or "structured")
            synthesized = [(label, str(structured_loc)), ("description", "; ".join(prose_cities))]
            fs["location_sources"] = synthesized
            loc_sources = _distinct([s for _, s in synthesized])
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
# Output text + quarantine stubs — the human-readable capture contract
# (JOB SNAPSHOT format, spec 2026-07-29). Section banners are all-caps with an
# underline whose length matches the banner text: `=` for the four content
# sections before the body, `-` for the CAPTURE blocks after it. Every field
# label is Title Case; per-field states use the honest-distinction phrases
# ("Employer Did Not Mention <X>." / "Could Not Verify." / "Conflicting
# Employer Information: <A> vs <B>." / "<X> Mentioned, but Details Were Not
# Provided." / "Not Specified"). The manifest `field_status` remains the
# machine record; the txt keeps one machine-anchored line family
# (`Job Posted At:` / `Job Updated At:`), which norm_contracts.py parses.
# --------------------------------------------------------------------------- #
_ET_TZ = ZoneInfo("America/New_York")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _banner(title: str, ch: str) -> list[str]:
    return [title, ch * len(title)]


def _human_date(iso) -> str:
    """`2026-06-13` -> `June 13, 2026`; absent/unparseable -> `Unknown` (never fabricated)."""
    s = str(iso or "").strip()
    if not s:
        return "Unknown"
    try:
        d = datetime.strptime(s[:10], "%Y-%m-%d")
    except ValueError:
        return "Unknown"
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def capture_timestamp(value) -> str:
    """OUR capture moment, rendered for humans in Eastern Time (DST-aware via
    zoneinfo America/New_York): `July 29, 2026 at 4:06 PM ET`. A historical
    date-only value renders `July 29, 2026 — Time Unavailable` — a time is
    never invented for a capture that only recorded a date."""
    s = str(value or "").strip()
    if not s:
        s = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if _ISO_DATE_RE.fullmatch(s):
        d = datetime.strptime(s, "%Y-%m-%d")
        return f"{d.strftime('%B')} {d.day}, {d.year} — Time Unavailable"
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        # Unparseable timestamp: fall back to any date prefix rather than inventing a time.
        m = re.match(r"\d{4}-\d{2}-\d{2}", s)
        return capture_timestamp(m.group(0)) if m else "Unknown"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    loc = dt.astimezone(_ET_TZ)
    hour = loc.hour % 12 or 12
    ampm = "AM" if loc.hour < 12 else "PM"
    return f"{loc.strftime('%B')} {loc.day}, {loc.year} at {hour}:{loc.minute:02d} {ampm} ET"


# Machine source tokens -> human names for the CAPTURE DETAILS `Source:` line.
_SOURCE_HUMAN = {
    "ashby-posting-api": "Ashby",
    "greenhouse-boards-api": "Greenhouse",
    "lever-postings-api": "Lever",
    "rippling-ats-api": "Rippling",
    "workable-api": "Workable",
    "workday-cxs-api": "Workday",
    "linkedin-guest": "LinkedIn (Guest)",
    "requests/html": "Employer Page",
    "playwright/html": "Rendered Employer Page",
}
_METHOD_HUMAN = {
    "ats": "ATS API", "requests": "Direct Fetch", "playwright": "Rendered Page",
    "greenhouse-embedded": "Embedded Greenhouse Recovery",
}


def _human_source(source: str) -> str:
    s = str(source or "").strip()
    if not s:
        return "Employer Page"
    base, _, qualifier = s.partition(" (")
    human = _SOURCE_HUMAN.get(s) or _SOURCE_HUMAN.get(base.strip())
    if human:
        if qualifier and s not in _SOURCE_HUMAN:
            qual = qualifier.rstrip(")").strip()
            return f"{human} ({qual.title() if qual.islower() else qual})"
        return human
    return s


def _human_method(method: str) -> str:
    m = str(method or "").strip()
    return _METHOD_HUMAN.get(m) or _human_source(m) if m else ""


def _apply_office_cadence(meta: dict, questions: list) -> tuple[str | None, str | None, str | None]:
    """If a kept question carries an office-attendance requirement, fold its full
    eligible-metro list into the working-location string and surface the cadence
    separately (verbatim-ish; no candidate-city mapping — vetting does that from
    jail.config.json). Returns (working_location, cadence, cadence_raw)."""
    working = meta.get("working_location") or meta.get("location")
    cadence = meta.get("cadence")
    cadence_raw = meta.get("cadence_raw")
    for q in questions or []:
        parsed = parse_office_cadence(q)
        if not parsed:
            continue
        metros = parsed.get("metros") or []
        if metros:
            metro_str = "; ".join(metros)
            working = f"{working}; {metro_str}" if working else metro_str
            # Dedupe while preserving order.
            working = "; ".join(dict.fromkeys(p.strip() for p in working.split(";") if p.strip()))
        cadence = cadence or parsed.get("cadence")
        cadence_raw = cadence_raw or parsed.get("verbatim")
    return working, cadence, cadence_raw


# --------------------------------------------------------------------------- #
# Miner-level extraction corrections (all offline) — employment from body prose,
# office-cadence prose fallback, additional-compensation mention splitting.
# --------------------------------------------------------------------------- #
_EXEMPT_RE = re.compile(r"(?i)\bfull[-\s]?time\b[,\s]+(?:and\s+)?exempt\b")
_EMPLOYMENT_PROSE_RE = re.compile(
    r"(?i)\b(full|part)[-\s]?time\b(\s*,\s*(non[-\s]?)?exempt\b)?")
_EMPLOYMENT_CONTEXT = ("position", "role", "employment", "employee", "schedule",
                       "status", "exempt", "opportunity")


def _mine_employment(body: str) -> str | None:
    """An explicit employment-type statement written in the JD prose (e.g. a
    `Full Time, Exempt` line) when no structured field carried one. Requires
    employment context on the same line — a marketing sentence that merely says
    "full-time" is never enough. Returns None rather than inferring."""
    for raw in (body or "").splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if not line:
            continue
        m = _EMPLOYMENT_PROSE_RE.search(line)
        if not m:
            continue
        has_exempt = bool(m.group(2))
        low = line.lower()
        if not has_exempt and not any(k in low for k in _EMPLOYMENT_CONTEXT):
            continue
        kind = f"{m.group(1).capitalize()} Time"
        if has_exempt:
            kind += ", Non-Exempt" if m.group(3) else ", Exempt"
        return kind
    return None


def _format_employment(structured, body: str) -> str:
    """The WORK DETAILS `Employment:` value. Maps structured tokens to readable
    Title Case (`FullTime` -> `Full Time`), appends `, Exempt` when the body
    states it, and falls back to an explicit body statement when the structured
    field is bare. `Not Specified` when the employer stated nothing."""
    s = str(structured or "").strip()
    if s:
        s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", s)
        s = re.sub(r"[_\-]+", " ", s)
        s = re.sub(r"\s+", " ", s).strip()
        s = " ".join(w if any(c.isupper() for c in w[1:]) else w.capitalize()
                     for w in s.split(" "))
        if "exempt" not in s.lower() and _EXEMPT_RE.search(body or ""):
            s += ", Exempt"
        return s
    return _mine_employment(body) or "Not Specified"


_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7}
_OFFICE_DAYS_RE = re.compile(
    r"(?i)\b(at least\s+|a minimum of\s+|minimum of\s+)?(one|two|three|four|five|\d)\s*\+?\s*"
    r"days?\s+(?:per|a|each)\s+week")


def _format_cadence(text: str | None) -> str | None:
    """A stated office cadence rendered in the spec's shape:
    `three days per week: Tuesday, Wednesday, Thursday` -> `3 Days Per Week, Tuesday–Thursday`;
    `at least 2 days per week` -> `At Least 2 Days Per Week`. Never infers a
    cadence that was not stated (returns None)."""
    s = str(text or "").strip()
    if not s:
        return None
    m = _OFFICE_DAYS_RE.search(s)
    if not m:
        # A stated cadence in another shape (e.g. "8 days per month") passes through as-is.
        return s
    n = _WORD_NUM.get(m.group(2).lower(), None)
    if n is None:
        try:
            n = int(m.group(2))
        except ValueError:
            return s
    open_ended = bool(m.group(1)) or "+" in m.group(0)
    base = f"{'At Least ' if open_ended else ''}{n} Day{'s' if n != 1 else ''} Per Week"
    # Named days immediately following the cadence ("...: Tuesday, Wednesday, Thursday").
    tail = s[m.end():m.end() + 120]
    named = [d for d in _DAY_NAMES if re.search(rf"(?i)\b{d}\b", tail)]
    if named:
        idxs = [_DAY_NAMES.index(d) for d in named]
        if len(named) >= 2 and idxs == list(range(idxs[0], idxs[0] + len(idxs))):
            days = f"{named[0]}–{named[-1]}"
        else:
            days = ", ".join(named)
        return f"{base}, {days}"
    return base


def _mine_office_expectation(body: str) -> str | None:
    """Prose fallback for the Office Expectation field: an explicit in-office
    cadence written in the JD body (e.g. "onsite ... three days per week:
    Tuesday, Wednesday, Thursday"). Returns the formatted cadence, or None —
    a cadence the employer never stated is NEVER inferred."""
    if not body:
        return None
    m = _OFFICE_DAYS_RE.search(body)
    if not m:
        return None
    # Format from the match onward so named days after the cadence are captured.
    return _format_cadence(body[m.start():m.start() + 160])


def _oxford_join(items: list[str]) -> str:
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


# --------------------------------------------------------------------------- #
# Working Location(s) rendering — short metro canon, `NYC Or SF` style
# --------------------------------------------------------------------------- #
_METRO_SHORT = {
    "new york city": "NYC", "new york": "NYC", "new york, ny": "NYC",
    "new york city, ny": "NYC", "new york city, new york": "NYC", "nyc": "NYC",
    "san francisco": "SF", "san francisco, ca": "SF", "san francisco, california": "SF",
    "sf": "SF",
    "san francisco bay area": "SF Bay Area", "sf bay area": "SF Bay Area",
    "los angeles": "LA", "los angeles, ca": "LA", "la": "LA",
    "washington, d.c.": "DC", "washington d.c.": "DC", "washington dc": "DC",
    "washington, dc": "DC", "dc": "DC", "d.c.": "DC",
}


def _short_metro(part: str) -> str:
    """A city name rendered in its common short form when the canon knows it
    (New York City -> NYC); anything unrecognized passes through verbatim."""
    s = re.sub(r"\s+", " ", str(part or "").strip()).strip(" ,;")
    key = s.lower()
    for suffix in (", united states", ", usa", ", us"):
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip(" ,")
    return _METRO_SHORT.get(key, s)


def _split_city_state_blob(s: str) -> list[str] | None:
    """Split a flat comma-joined offices blob (`San Francisco, CA, New York, NY`)
    into `City, ST` pairs — only when it actually contains two or more such pairs
    (a single `Austin, TX` is not a blob). Employer order is preserved."""
    tokens = [t.strip() for t in s.split(",") if t.strip()]
    parts: list[str] = []
    pairs = 0
    i = 0
    while i < len(tokens):
        if i + 1 < len(tokens) and re.fullmatch(r"[A-Z]{2}", tokens[i + 1]):
            parts.append(f"{tokens[i]}, {tokens[i + 1]}")
            pairs += 1
            i += 2
        else:
            parts.append(tokens[i])
            i += 1
    return parts if pairs >= 2 else None


def _format_working_locations(value: str) -> str:
    """A multi-city working-location list rendered for humans: short metro names
    joined with ` or ` (`New York City; San Francisco` -> `NYC or SF`), deduped
    after canonicalization. Handles both `;`-separated lists and a flat
    comma-joined `City, ST, City, ST` blob (Greenhouse offices strings). Display
    only — the employer's own order is always preserved, never re-sorted.
    Non-list values (Remote, honest phrases) pass through."""
    s = str(value or "").strip()
    if not s:
        return s
    if ";" in s:
        parts = [p.strip() for p in s.split(";") if p.strip()]
    else:
        parts = _split_city_state_blob(s) or [s]
    if len(parts) == 1:
        return _short_metro(parts[0])
    shorts = list(dict.fromkeys(_short_metro(p) for p in parts))
    return " or ".join(shorts)


# Long metro forms -> short, for rewriting cities INSIDE a quoted preference
# sentence. Ordered longest-first so "San Francisco Bay Area" wins over
# "San Francisco, CA".
_METRO_SENTENCE_FORMS = sorted(
    [("San Francisco Bay Area", "SF Bay Area"), ("San Francisco, California", "SF"),
     ("San Francisco, CA", "SF"), ("New York City, New York", "NYC"),
     ("New York City, NY", "NYC"), ("New York City", "NYC"), ("New York, NY", "NYC"),
     ("Los Angeles, CA", "LA"), ("Washington, D.C.", "DC"), ("Washington, DC", "DC")],
    key=lambda kv: -len(kv[0]))
# An employer-stated location PREFERENCE (never a requirement): a sentence whose
# preference wording attaches to being based/located somewhere.
_LOC_PREFERENCE_RE = re.compile(
    r"(?i)\b((?:strong(?:ly)?\s+)?prefer(?:ence|red|s)?\b[^.\n]*?"
    r"\b(?:based|located|reside|residing|work(?:ing)?\s+(?:from|in|out\s+of))\b[^.\n]*)")


def _mine_location_preference(body: str) -> str | None:
    """An employer-stated location PREFERENCE mined from the body, rendered as a
    short sentence with canonical metro names (`Strong preference for the
    successful applicant to be based in SF or NYC.`). Only a stated preference
    qualifies — a mandatory requirement is location/arrangement data, not a
    preference, and nothing here ever labels a preference a requirement. The full
    employer sentence stays in the body; only the obvious `ir` -> `or` source
    typo between place names is normalized."""
    m = _LOC_PREFERENCE_RE.search(body or "")
    if not m:
        return None
    s = re.sub(r"\s+", " ", m.group(1)).strip().rstrip(" ,;:")
    # The observed source typo: "San Francisco, CA ir New York, NY".
    s = re.sub(r"(?<=[A-Za-z.,])\s+ir\s+(?=[A-Z])", " or ", s)
    for long_form, short in _METRO_SENTENCE_FORMS:
        s = s.replace(long_form, short)
    s = s[0].upper() + s[1:]
    return s if s.endswith(".") else s + "."


# Eligibility/mention sentences that reference additional-compensation components.
_ADDL_MENTION_RE = re.compile(
    r"(?i)\b(?:does\s+not\s+include|doesn'?t\s+include|not\s+include|excludes?|"
    r"exclusive\s+of|in\s+addition\s+to|(?:may|might|could|can|will|are|is)\s+(?:also\s+)?be\s+"
    r"eligible(?:\s+for)?|eligibility\s+for)\b")
_ADDL_COMP_TOKENS = (
    (re.compile(r"(?i)\bbonus(es)?\b"), "Bonus"),
    (re.compile(r"(?i)\bcommissions?\b"), "Commission"),
    (re.compile(r"(?i)\b(equity|stock options?|rsus?|restricted stock)\b"), "Equity"),
    (re.compile(r"(?i)\btravel credits?\b"), "Employee Travel Credits"),
)


def _mine_additional_comp_mentions(body: str) -> list[str]:
    """Additional-compensation components the employer MENTIONED (eligibility or
    disclaimer sentences) without publishing specifics — split out of the old
    `Equity:` shoehorn. Returns ordered unique component names."""
    out: list[str] = []
    for raw in re.split(r"(?<=[.!?])\s+|\n", body or ""):
        sentence = raw.strip()
        if not sentence or not _ADDL_MENTION_RE.search(sentence):
            continue
        for rx, name in _ADDL_COMP_TOKENS:
            if rx.search(sentence) and name not in out:
                out.append(name)
    return out


# A short `<Label>:` prefix on a mined bullet ("Financial Wellness: 401(k) program
# and equity opportunities", "Parental Leave & Family Support: Up to 18 weeks…") is
# section formatting, not content. Anchored at the START of the bullet only — a
# mid-sentence clause ("… benefits. Note: details vary") is never treated as a label.
_LABEL_PREFIX_RE = re.compile(r"^([A-Z][A-Za-z0-9&/()'’ \-]{0,48}):\s+(.+)$")


def _strip_bullet_and_label(text: str) -> str:
    s = re.sub(r"^[\s\-•*·]+", "", str(text or "")).strip()
    m = _LABEL_PREFIX_RE.match(s)
    if m:
        # Count real words — connector tokens ("&", "and", "of") don't make a label a
        # sentence, so "Parental Leave & Family Support" still strips.
        words = [w for w in m.group(1).split() if w.lower() not in ("&", "and", "of", "the")]
        if len(words) <= 5:
            s = m.group(2).strip()
    return s


def _additional_compensation_value(meta: dict, body: str) -> str:
    """The COMPENSATION `Additional Compensation:` value — bonus/commission/equity
    eligibility, never merged into base salary. A real equity description (a grant
    size / vesting schedule / dollar value) passes through, cleaned of bullet
    markers and label prefixes; detail-free equity language collapses to clean
    comp-only wording (`Equity Opportunities.`) or the honest mention phrase.
    401(k)/benefits language never lands here — those are benefits."""
    equity = meta.get("equity")
    if equity is None and body:
        _b, equity = mine_benefits_equity(body)
    parts: list[str] = []
    mentions = _mine_additional_comp_mentions(body or "")
    if equity and equity != MENTIONED_NO_DETAILS:
        detail = _strip_bullet_and_label(equity)
        if _EQUITY_SPECIFICS_RE.search(detail):
            if detail and detail[-1] not in ".!?":
                detail += "."
            parts.append(detail)
            mentions = [m for m in mentions if m != "Equity"]
        elif re.search(r"(?i)\bequity\s+opportunit", detail):
            # "401(k) program and equity opportunities" — the 401(k) is a benefit;
            # only the comp component belongs here, as clean wording.
            parts.append("Equity Opportunities.")
            mentions = [m for m in mentions if m != "Equity"]
        elif "Equity" not in mentions:
            mentions.append("Equity")
    elif equity == MENTIONED_NO_DETAILS and "Equity" not in mentions:
        mentions.append("Equity")
    if mentions:
        parts.append(f"{_oxford_join(mentions)} mentioned, but details not provided.")
    if not parts:
        return "Employer did not mention additional compensation."
    return " ".join(parts)


# Sentence-bounded benefits budget: the summary never slices a sentence mid-word.
_BENEFITS_BUDGET = 480
# Concrete, unusually-important detail markers rank a sentence as worth keeping;
# generic perk wording ranks it as the first to drop when over budget.
_BENEFIT_CONCRETE_RE = re.compile(
    r"(?i)\d|\$|no[-\s]?cost|free\b|therapy|insurance|401|parental|leave|holiday|"
    r"paid|weeks|break|pto|equity")
_BENEFIT_GENERIC_RE = re.compile(
    r"(?i)stipend|perk|discount|wellness|growth|support|benefit|competitive|"
    r"tailored|opportunit")


def _benefit_distinctiveness(sentence: str) -> int:
    score = 2 if _BENEFIT_CONCRETE_RE.search(sentence) else 0
    if _BENEFIT_GENERIC_RE.search(sentence):
        score -= 1
    return score


def _benefits_value(meta: dict, body: str) -> str:
    """The COMPENSATION `Benefits:` value: period-separated short sentences from a
    mined benefits section, the honest mention phrase, or the did-not-mention
    phrase — never `Not Posted` when the employer did reference benefits.
    Over-budget summaries drop whole LEAST-DISTINCTIVE sentences (generic perk
    wording) rather than slicing characters — never a mid-word `…`."""
    benefits = meta.get("benefits")
    if benefits is None and body:
        benefits, _e = mine_benefits_equity(body)
    if not benefits:
        return "Employer did not mention benefits."
    if benefits == MENTIONED_NO_DETAILS:
        return "Mentioned, but details not provided."
    items: list[str] = []
    for raw in str(benefits).split(";"):
        item = _strip_bullet_and_label(raw)
        # Equity language belongs in Additional Compensation, not the benefits summary
        # ("401(k) program and equity opportunities" keeps only the 401(k) part here).
        item = re.sub(r"(?i)\s*(?:,\s*)?(?:and\s+|&\s*)?equity\s+"
                      r"(?:opportunit(?:y|ies)|grants?|compensation)\b", "", item)
        item = item.strip(" ,").rstrip(".")
        if item:
            items.append(item[0].upper() + item[1:])
    if not items:
        return "Employer did not mention benefits."

    def render(parts: list[str]) -> str:
        joined = ". ".join(parts)
        return joined + ("" if joined.endswith(("…", ".")) else ".")

    # Sentence-bounded budget: drop whole sentences, least distinctive first
    # (among ties, the later one goes), preserving original order of the keepers.
    while len(items) > 1 and len(render(items)) > _BENEFITS_BUDGET:
        drop_idx = min(range(len(items)),
                       key=lambda i: (_benefit_distinctiveness(items[i]), -i))
        items.pop(drop_idx)
    return render(items)


_K_AMOUNT_RE = re.compile(r"\$\s?(\d{1,3}(?:\.\d+)?)\s?[kK]\b")


def _expand_dollar_amounts(text: str) -> str:
    """`$236K` -> `$236,000` — Base Salary bullets carry full dollar amounts."""
    return _K_AMOUNT_RE.sub(lambda m: f"${int(round(float(m.group(1)) * 1000)):,}", text)


# A dollar range's separator renders as an en dash with no surrounding spaces,
# with the dollar sign on BOTH endpoints.
_RANGE_SEP_RE = re.compile(r"(\$[\d,]+(?:\.\d+)?)\s*(?:-|–|—|to|through)\s*(\$?[\d,]+(?:\.\d+)?)")
_ANNUAL_MARKER_RE = re.compile(r"(?i)\b(annually|annual|per year|a year)\b|/y(?:ea)?r\b")
_NON_ANNUAL_RE = re.compile(r"(?i)\bhour(ly)?\b|/hour|/hr\b|\bmonth(ly)?\b|/month|\bweek(ly)?\b")
# Generic comp labels an ATS prepends to a band ("Pay Range: USD 232,000–282,000") —
# stripped. Geo/level labels (Zone A, US Tier 1, city names) are MEANINGFUL and survive.
_GENERIC_COMP_LABEL_RE = re.compile(
    r"(?i)^(?:pay(?:\s+range)?|salary(?:\s+range)?|base\s+pay(?:\s+range)?|"
    r"base\s+salary(?:\s+range)?|compensation(?:\s+range)?|pay\s+rate)\s*:\s*")
_LEADING_CODE_RE = re.compile(r"(?i)^(?:USD|US\$)\s*")
_COMMA_AMOUNT_RE = re.compile(r"(?<![\d$.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?)")


def _normalize_salary_band(seg: str) -> str:
    """One band rendered canonically: generic label stripped, a leading currency
    code folded into `$…–$… USD` shape (`Pay Range: USD 232,000–282,000` ->
    `$232,000–$282,000 USD`), dollar signs on both endpoints, spaceless en dash."""
    seg = _GENERIC_COMP_LABEL_RE.sub("", str(seg or "").strip()).strip()
    if _LEADING_CODE_RE.match(seg):
        seg = _LEADING_CODE_RE.sub("", seg).strip()
        if "$" not in seg:
            seg = _COMMA_AMOUNT_RE.sub(lambda m: f"${m.group(1)}", seg)
    seg = _expand_dollar_amounts(seg)
    seg = _RANGE_SEP_RE.sub(
        lambda m: f"{m.group(1)}–{m.group(2) if m.group(2).startswith('$') else '$' + m.group(2)}",
        seg)
    return seg


# Abbreviated-thousands rendering (2026-07-29 revised spec): `$232,000–$282,000`
# -> `$232-282K`, no unnecessary `.0`. Non-USD currency codes are preserved
# explicitly; a `$` amount implies USD (no trailing code).
_ABBREV_RANGE_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)–\$([\d,]+(?:\.\d+)?)")
_ABBREV_SINGLE_RE = re.compile(r"\$([\d,]+(?:\.\d+)?)(?![\d,])")
_NON_USD_CODE_RE = re.compile(r"(?i)\b(EUR|GBP|CAD|AUD|CHF|JPY|MXN|BRL|INR)\b|[£€¥]")


def _k_amount(raw: str) -> str | None:
    """`232,000` -> `232`; `82,500` -> `82.5`; amounts under 1000 -> None."""
    try:
        v = float(raw.replace(",", ""))
    except ValueError:
        return None
    if v < 1000:
        return None
    kv = v / 1000.0
    s = f"{kv:.1f}".rstrip("0").rstrip(".")
    return s


def _abbrev_band(seg: str) -> str:
    """Abbreviate a normalized band's dollar amounts to thousands:
    `$232,000–$282,000` -> `$232-282K`; a lone `$232,000` -> `$232K`."""
    def range_sub(m):
        lo, hi = _k_amount(m.group(1)), _k_amount(m.group(2))
        if lo is None or hi is None:
            return m.group(0)
        return f"${lo}-{hi}K"

    seg = _ABBREV_RANGE_RE.sub(range_sub, seg)

    def single_sub(m):
        k = _k_amount(m.group(1))
        return f"${k}K" if k is not None else m.group(0)

    return re.sub(r"\$([\d,]{4,}(?:\.\d+)?)(?!-|\d|,\d|K)", single_sub, seg)


def _base_salary_bands(compensation, fs: dict, meta: dict | None = None) -> list[str]:
    """One entry per geo/level band: generic ATS labels stripped, abbreviated
    thousands (`$232-282K`), `Annually` appended only when the employer's own
    wording states the range is annual (never inferred). A `$` amount implies
    USD; non-USD currency codes stay explicit."""
    meta = meta or {}
    segments: list[str] = []
    if compensation:
        segments = [p.strip() for p in re.split(r"\s*[·•]\s*", str(compensation)) if p.strip()]
    elif fs.get("compensation_prose_all"):
        segments = [str(v).strip() for v in fs["compensation_prose_all"] if str(v).strip()]
    # Only the employer's own comp wording can testify the range is annual.
    employer_wording = " ".join(str(x or "") for x in (
        compensation, meta.get("compensation_raw"), fs.get("compensation_prose_verbatim")))
    stated_annual = bool(_ANNUAL_MARKER_RE.search(employer_wording))
    out: list[str] = []
    for seg in segments:
        raw_seg = seg
        seg = _normalize_salary_band(seg)
        seg = _abbrev_band(seg)
        # Strip a redundant USD tag ($ implies it); keep explicit non-USD codes.
        if not _NON_USD_CODE_RE.search(raw_seg):
            seg = re.sub(r"\s*\bUSD\b\s*", " ", seg).strip()
        if stated_annual and not _ANNUAL_MARKER_RE.search(seg) and not _NON_ANNUAL_RE.search(seg):
            seg = f"{seg} Annually"
        out.append(seg)
    return out


def _conflict_phrase(sources) -> str:
    values = [str(v).strip() for _s, v in (sources or []) if str(v or "").strip()]
    if len(values) >= 2:
        return f"Conflicting employer information: {values[0]} vs {values[1]}."
    return "Conflicting employer information: two sources disagree (both kept in the manifest)."


_V_MARK = {FOUND: "✓", NOT_POSTED: "—", CAPTURE_FAILED: "✗", CONFLICTING: "⚠ Conflicting"}


def _verification_line(fs: dict) -> str:
    def mark(field):
        return _V_MARK.get(fs.get(field), "✗")
    return (f"Verification: Job Description {mark('description')} | "
            f"Compensation {mark('compensation')} | Working Location {mark('working_location')}")


def _capture_details_lines(*, captured, apply_url, source, posting_id, methods, fs,
                           verification: str | None = None) -> list[str]:
    """ORIGINAL CAPTURE DETAILS. The human heading "ORIGINAL" means the earliest
    capture JAIL can establish from its durable records (the capture-history
    registry) — backfilled records may predate any batch still on disk."""
    lines = _banner("ORIGINAL CAPTURE DETAILS", "-")
    lines.append(f"Captured At: {capture_timestamp(captured)}")
    lines.append(f"Application URL: {apply_url}")
    lines.append(f"Source: {source}")
    lines.append(f"Posting ATS ID: {posting_id}")
    lines.append(f"Methods Checked: {methods}")
    lines.append(verification or _verification_line(fs))
    return lines


def _capture_update_lines(capture_update: dict, *, source, posting_id, methods, fs) -> list[str]:
    """LATEST CAPTURE DETAILS — present only when at least one later successful
    fetch exists. Describes the NEW fetch (ORIGINAL CAPTURE DETAILS above keeps
    describing the earliest one), then the comparison notes."""
    lines = _banner("LATEST CAPTURE DETAILS", "-")
    lines.append(f"Captured At: {capture_timestamp(capture_update.get('re_captured'))}")
    lines.append(f"Source: {source}")
    lines.append(f"Posting ATS ID: {posting_id}")
    lines.append(f"Methods Checked: {methods}")
    lines.append(_verification_line(fs))
    notes = capture_update.get("notes") or "Previous capture was not available for comparison."
    lines.append(f"Additional Notes: {notes}")
    return lines


# --------------------------------------------------------------------------- #
# Re-fetch comparison + best-verified merge (revisions #4 and #5)
# --------------------------------------------------------------------------- #
_BODY_MARKER_RE = re.compile(r"--- JOB TEXT START ---\n(.*)\n--- JOB TEXT END ---", re.S)

# The material regions a re-fetch comparison reads. Line-set membership per region
# (normalized), NEVER body length: chrome-only churn changes no region.
_MATERIAL_REGIONS = (
    ("Responsibilities", ("responsib", "what you'll do", "what you will do",
                          "what you own", "you will")),
    ("Qualifications", ("qualificat", "requirement", "who you are",
                        "looking for", "experience")),
    ("Compensation", ("$", "salary", "compensation", "pay range", "bonus", "equity")),
    ("Working Location", ("location", "remote", "hybrid", "office", "onsite", "on-site")),
    ("Office Cadence", ("days per week", "days a week", "in person", "in-person")),
    ("Application Questions", ("?",)),
)


def body_from_capture(text: str | None) -> str | None:
    """The body between the stable markers of a written capture, or None."""
    m = _BODY_MARKER_RE.search(str(text or ""))
    if not m:
        return None
    return m.group(1).strip("\n")


def _material_lines(body: str) -> list[str]:
    return [re.sub(r"\s+", " ", ln).strip().lower()
            for ln in str(body or "").splitlines() if ln.strip()]


def _region_set(lines: list[str], keys: tuple) -> set:
    return {ln for ln in lines if any(k in ln for k in keys)}


_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.)\S+")


def _substantive_units(body: str | None) -> dict:
    """The SUBSTANTIVE sentence multiset of a body. Everything a re-render can
    legitimately change is normalized away: bullet markers and list numbering,
    whitespace, letter CASE (the old flattener uppercased headings), raw URLs and
    link-rendering artifacts, and ELEMENT ORDER (a multiset, not a linear diff —
    HTML element order can differ from a plaintext flattening without the
    employer having edited anything). Only genuine sentence additions, removals,
    or rewordings change the multiset."""
    from collections import Counter
    units: Counter = Counter()
    for raw in str(body or "").splitlines():
        ln = re.sub(r"^[ \t]*(?:[-•*·]+|\d{1,3}\.)\s*", "", raw)
        ln = _URL_RE.sub(" ", ln)
        for sent in re.split(r"(?<=[.!?;])\s+", ln):
            unit = re.sub(r"[^a-z0-9 ]+", " ", sent.lower())
            unit = re.sub(r"\s+", " ", unit).strip()
            if unit:
                units[unit] += 1
    return units


def material_change_notes(old_body: str | None, new_body: str | None) -> str:
    """The `Additional Notes:` body sentence: (a) list/formatting-only differences
    are named as formatting restoration, never as an employer edit; (b) genuine
    content changes are detected on NORMALIZED SUBSTANTIVE text + the material
    regions — never body length. Chrome-only churn is no material change."""
    if old_body is None:
        return "Previous capture was not available for comparison."
    old_raw = str(old_body or "")
    new_raw = str(new_body or "")
    if old_raw == new_raw:
        return "No material changes detected."
    old_units, new_units = _substantive_units(old_raw), _substantive_units(new_raw)
    if old_units == new_units:
        return "Employer content unchanged; source list formatting restored."
    # Genuine sentence additions/removals/rewordings: judge only the CHANGED
    # units, so page-chrome churn (nav/cookie lines with no material vocabulary)
    # never masquerades as an employer edit.
    diff_units = ([u for u in old_units if old_units[u] > new_units.get(u, 0)]
                  + [u for u in new_units if new_units[u] > old_units.get(u, 0)])
    material = any(any(k in u for k in keys)
                   for _name, keys in _MATERIAL_REGIONS for u in diff_units)
    if material:
        return "Employer materially updated the posting."
    return "No material changes detected."


def body_would_degrade(old_body: str | None, new_body: str | None) -> bool:
    """True when replacing the existing body with a new fetch would LOSE a better
    capture (revision #4): the new body fails classification (truncated /
    contaminated / blocked shell) or drops material regions the old body carried.
    A genuine employer edit — same regions present, different content — is NOT
    degradation."""
    if not (old_body or "").strip():
        return False
    old_st, _ = classify(old_body)
    new_st, _ = classify(new_body or "")
    if old_st == USABLE and new_st != USABLE:
        return True
    if old_st != USABLE:
        return False
    old_lines, new_lines = _material_lines(old_body), _material_lines(new_body or "")
    for _name, keys in _MATERIAL_REGIONS:
        if _region_set(old_lines, keys) and not _region_set(new_lines, keys):
            return True
    return False


# --------------------------------------------------------------------------- #
# Snapshot-field comparison for CAPTURE UPDATE DETAILS — the notes must name what a
# re-capture ADDED or CORRECTED in the header fields, not only diff the body.
# Reads BOTH the current labels and the legacy `== NORMALIZED ==` labels, so a
# legacy-format prior capture compares faithfully.
# --------------------------------------------------------------------------- #
_FIELD_HUMAN = {
    "posted_date": "employer's posting date", "updated_date": "employer's update date",
    "employment": "employment type", "work_arrangement": "work arrangement",
    "working_location": "working location", "office_expectation": "office expectation",
    "base_salary": "base salary", "additional_compensation": "additional compensation",
    "benefits": "benefits",
}
# Values that mean "the capture had nothing here" (either format's placeholders).
_PLACEHOLDER_RE = re.compile(
    r"(?i)^(unknown|n/a|not specified|not explicitly stated|not posted|"
    r"could not verify\.?|not available|none)$|^employer did not mention")
_MENTION_STATE_RE = re.compile(r"(?i)mentioned.*(no details|details were not provided)")


def _grab_line(head: str, label: str) -> str | None:
    m = re.search(rf"^{re.escape(label)}:\s*(.*)$", head, re.M)
    return m.group(1).strip() if m else None


def _capture_fields(text: str) -> dict:
    """The snapshot fields of a written capture (either format), normalized to one
    canonical key set. Placeholder values come back as None (nothing captured)."""
    head = str(text or "").split("--- JOB TEXT START ---", 1)[0]
    f: dict = {}
    # Dates: current lines first, then the legacy provenance line.
    posted = _grab_line(head, "Job Posted At")
    updated = _grab_line(head, "Job Updated At")
    if posted is None:
        legacy = _grab_line(head, "Posted")
        if legacy:
            posted = legacy.split("·")[0].strip()
            um = re.search(r"Updated:\s*(\S+)", legacy)
            updated = um.group(1) if um else updated
    f["posted_date"] = posted
    f["updated_date"] = updated
    f["employment"] = _grab_line(head, "Employment") or _grab_line(head, "Employment Type")
    f["work_arrangement"] = _grab_line(head, "Work Arrangement") or _grab_line(head, "Workplace")
    loc = _grab_line(head, "Working Location(s)") or _grab_line(head, "Working Location")
    office = _grab_line(head, "Office Expectation")
    if loc:
        loc = re.sub(r"\s*\[[a-z _]+\]\s*$", "", loc).strip()  # legacy status tag
        if office is None and "—" in loc:                        # legacy combined cadence
            loc, _, cad = loc.rpartition("—")
            loc, office = loc.strip(), cad.strip()
    f["working_location"] = loc
    f["office_expectation"] = office
    base = _grab_line(head, "Base Salary") or _grab_line(head, "Compensation")
    if not base:  # bullet list (current bullets start at col 0; earlier were indented)
        m = re.search(r"^Base Salary:\s*\n((?:[ \t]*-\s+.*\n?)+)", head, re.M)
        if m:
            base = " · ".join(ln.strip().lstrip("- ").strip()
                              for ln in m.group(1).splitlines() if ln.strip())
    f["base_salary"] = base
    f["additional_compensation"] = (_grab_line(head, "Additional Compensation")
                                    or _grab_line(head, "Equity"))
    f["benefits"] = _grab_line(head, "Benefits")
    for k, v in list(f.items()):
        v = re.sub(r"\s*\[[a-z _]+\]\s*$", "", (v or "")).strip()  # legacy status tags
        if not v or _PLACEHOLDER_RE.match(v):
            f[k] = None
        else:
            f[k] = v
    return f


def _norm_field_value(key: str, value: str | None) -> str | None:
    """Comparison form of a field value: formatting drift (FullTime vs Full Time,
    ISO vs human dates, long vs short metro names, `$182,000-…` vs `USD 182,000…`)
    must NOT read as a correction — only content differences do."""
    if value is None:
        return None
    v = re.sub(r"\s+", " ", str(value)).strip()
    if _MENTION_STATE_RE.search(v):
        return "mentioned-no-details"
    if key in ("posted_date", "updated_date"):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v)
        if m:
            return f"{m.group(1)}{m.group(2)}{m.group(3)}"
        try:
            return datetime.strptime(v, "%B %d, %Y").strftime("%Y%m%d")
        except ValueError:
            return re.sub(r"[^0-9]+", "", v) or None
    if key == "base_salary":
        # Expand abbreviated-thousands shorthand so `$182-227K` compares equal to
        # `USD 182,000-227,000` — a rendering change is never a "correction".
        v = v.replace(",", "")
        v = re.sub(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)[Kk]\b",
                   lambda m: f"{int(float(m.group(1)) * 1000)}-{int(float(m.group(2)) * 1000)}", v)
        v = re.sub(r"(\d+(?:\.\d+)?)[Kk]\b",
                   lambda m: str(int(float(m.group(1)) * 1000)), v)
        return ",".join(re.findall(r"\d+", v)) or None
    if key == "working_location":
        parts = re.split(r";|\bor\b|\bOr\b", v)
        toks = sorted({re.sub(r"[^a-z0-9]+", "", _short_metro(p).lower())
                       for p in parts if p.strip()})
        return "|".join(t for t in toks if t) or None
    return re.sub(r"[^a-z0-9]+", "", v.lower()) or None


def capture_update_notes(prior_text: str | None, new_text: str,
                         *, kept_prior_body: bool = False) -> str:
    """The `Additional Notes:` sentence for a re-capture: a FIELD-level diff of the
    two captures' snapshot sections (what was added / corrected), plus the
    normalized material-content body comparison. Only when both fields and material
    body content are unchanged may it say `No Material Changes Detected.`"""
    if prior_text is None:
        return "Previous capture was not available for comparison."
    old_f, new_f = _capture_fields(prior_text), _capture_fields(new_text)
    added: list[str] = []
    corrected: list[str] = []
    for key, human in _FIELD_HUMAN.items():
        old_v = _norm_field_value(key, old_f.get(key))
        new_v = _norm_field_value(key, new_f.get(key))
        if new_v is None or old_v == new_v:
            continue
        (added if old_v is None else corrected).append(human)
    old_body = body_from_capture(prior_text)
    new_body = body_from_capture(new_text)
    body_notes = material_change_notes(old_body, new_body)
    parts: list[str] = []
    if added and corrected:
        parts.append(f"Added the {_oxford_join(added)} and corrected the "
                     f"{_oxford_join(corrected)} that the original capture missed.")
    elif added:
        parts.append(f"Added the {_oxford_join(added)} that the original capture missed.")
    elif corrected:
        parts.append(f"Corrected the {_oxford_join(corrected)} from the original capture.")
    if kept_prior_body:
        parts.append("The new fetch's job text was degraded, so the prior job text was kept.")
    elif body_notes == "Employer content unchanged; source list formatting restored.":
        # NEVER "Job text unchanged" when the formatting changed.
        parts.append(body_notes)
    elif body_notes == "Employer materially updated the posting.":
        parts.append(body_notes)
    elif parts and (old_body or "") == (new_body or ""):
        parts.append("Job text unchanged.")
    elif parts:
        # The bytes differ but nothing the comparator deems employer content did
        # (chrome-level churn) — still never claim "Job text unchanged".
        parts.append("Employer content unchanged; source list formatting restored.")
    if not parts:
        return "No material changes detected."
    return " ".join(parts)


def _original_capture_details(prior_text: str | None, prev_entry: dict | None) -> dict:
    """The ORIGINAL capture's CAPTURE DETAILS field values, recovered from the prior
    file (current format: the first CAPTURE DETAILS block after the END marker;
    legacy: the provenance line), falling back to the prior manifest entry. These
    keep describing the original capture when a re-fetch adds an UPDATE block."""
    d: dict = {}
    text = str(prior_text or "")
    tail = text.split("--- JOB TEXT END ---", 1)[-1] if "--- JOB TEXT END ---" in text else ""
    if "CAPTURE DETAILS" in tail:
        for label, key in (("Application URL", "apply_url"), ("Source", "source"),
                           ("Posting ATS ID", "posting_id"), ("Methods Checked", "methods")):
            v = _grab_line(tail, label)
            if v:
                d[key] = v
        m = re.search(r"^(Verification:.*)$", tail, re.M)
        if m:
            d["verification"] = m.group(1).strip()
    else:
        m = re.search(r"^Source:\s*(.+?)\s*·\s*Posting ID:\s*(.+?)\s*·\s*Captured:.*?"
                      r"·\s*Methods tried:\s*(.+)$", text, re.M)
        if m:
            d["source"] = _human_source(m.group(1))
            d["posting_id"] = m.group(2)
            d["methods"] = ", ".join(dict.fromkeys(
                _human_method(x.strip()) for x in m.group(3).split(",") if x.strip()))
        v = _grab_line(text.split("--- JOB TEXT START ---", 1)[0], "Application URL")
        if v:
            d["apply_url"] = v
    prev_entry = prev_entry or {}
    if "verification" not in d and prev_entry.get("field_status"):
        d["verification"] = _verification_line(prev_entry["field_status"])
    if "posting_id" not in d and prev_entry.get("posting_id"):
        d["posting_id"] = prev_entry["posting_id"]
    if "methods" not in d and prev_entry.get("methods_tried"):
        d["methods"] = ", ".join(dict.fromkeys(
            _human_method(x) for x in prev_entry["methods_tried"] if x))
    return d


def build_output_text(url: str, title: str, company: str, body_text: str, *,
                      meta: dict | None = None, questions: list | None = None,
                      field_status: dict | None = None, methods_tried: list | None = None,
                      captured: str | None = None, capture_update: dict | None = None) -> str:
    """The human-readable capture contract (JOB SNAPSHOT format): JOB SNAPSHOT /
    WORK DETAILS / COMPENSATION / APPLICATION QUESTIONS WORTH PREPARING sections,
    the full job text byte-for-byte between the stable START/END markers, then
    CAPTURE DETAILS below the END marker (and CAPTURE UPDATE DETAILS only on a
    genuine re-fetch — pass `capture_update` with `original_captured` /
    `re_captured` / `notes`). `captured` is the FULL fetched-at timestamp
    (ISO with TZ), rendered in Eastern Time. Golden-file tested."""
    meta = meta or {}
    questions = questions if questions is not None else (meta.get("questions") or [])
    fs = field_status or assess_completeness(meta, body_text, questions)

    apply_url = meta.get("apply_url") or "Not Available"
    source = _human_source(meta.get("source") or "requests/html")
    posting_id = meta.get("posting_id") or "Not Available"
    methods = ", ".join(dict.fromkeys(
        _human_method(m) for m in (methods_tried or []) if m))
    if not methods:
        methods = _human_method(meta.get("method") or meta.get("source") or "") or "Not Recorded"
    captured_ts = captured or datetime.now(timezone.utc).isoformat(timespec="seconds")
    original_captured = captured_ts
    if capture_update and capture_update.get("original_captured"):
        original_captured = capture_update["original_captured"]

    workplace = meta.get("workplace") or ("Remote" if meta.get("remote") else None)
    working_location, cadence, _cadence_raw = _apply_office_cadence(meta, questions)
    compensation = meta.get("compensation")

    # When a field was found only in the JD prose (no structured value), the prose
    # figure IS the employer's published value — surface it.
    if not compensation and fs.get("compensation_source") == "description":
        compensation = fs.get("compensation_prose")
    if not working_location and fs.get("working_location_source") == "description":
        working_location = fs.get("working_location_prose")

    def _honest(value, field: str, label: str) -> str:
        if value:
            return str(value)
        st = fs.get(field)
        if st == CONFLICTING:
            key = "compensation_sources" if field == "compensation" else "location_sources"
            return _conflict_phrase(fs.get(key) or meta.get(key))
        if st == NOT_POSTED:
            return f"Employer did not mention {label}."
        return "Could not verify."

    lines: list[str] = []
    lines += _banner("JOB SNAPSHOT", "=")
    lines.append(f"Company: {company}")
    lines.append(f"Role: {title}")
    lines.append(f"Job Posting URL: {url}")
    # Always present — `Unknown` when the source exposed no date, never fabricated.
    lines.append(f"Job Posted At: {_human_date(meta.get('posted_date'))}")
    lines.append(f"Job Updated At: {_human_date(meta.get('updated_date'))}")
    lines.append("")
    lines += _banner("WORK DETAILS", "=")
    lines.append(f"Employment: {_format_employment(meta.get('employment_type'), body_text)}")
    lines.append(f"Work Arrangement: {workplace or 'Not Explicitly Stated'}")
    if fs.get("working_location") == CONFLICTING:
        loc_value = _conflict_phrase(fs.get("location_sources") or meta.get("location_sources"))
    elif working_location:
        loc_value = _format_working_locations(working_location)
    else:
        loc_value = _honest(None, "working_location", "working location")
    lines.append(f"Working Location(s): {loc_value}")
    # Optional: an employer-STATED location preference (never a requirement, never
    # folded into Work Arrangement or Office Expectation; omitted when unstated).
    preference = _mine_location_preference(body_text)
    if preference:
        lines.append(f"Location Preference: {preference}")
    office = _format_cadence(cadence) or _mine_office_expectation(body_text)
    lines.append(f"Office Expectation: {office or 'Not Specified'}")
    lines.append("")
    lines += _banner("COMPENSATION", "=")
    bands = ([] if fs.get("compensation") == CONFLICTING
             else _base_salary_bands(compensation, fs, meta))
    if len(bands) == 1:
        # A single range renders INLINE — no one-item bullet list.
        lines.append(f"Base Salary: {bands[0]}")
    elif bands:
        lines.append("Base Salary:")
        for b in bands:
            lines.append(f"- {b}")
    else:
        lines.append(f"Base Salary: {_honest(None, 'compensation', 'compensation')}")
    lines.append("")
    lines.append(f"Additional Compensation: {_additional_compensation_value(meta, body_text)}")
    lines.append("")
    lines.append(f"Benefits: {_benefits_value(meta, body_text)}")
    lines.append("")
    lines += _banner("APPLICATION QUESTIONS WORTH PREPARING", "=")
    if questions:
        for i, q in enumerate(questions, 1):
            req = "[Required]" if q.get("required") else "[Optional]"
            label = _strip_wrapping_quotes(q.get("label", "").strip())
            lines.append(f"{i}. {label} {req}")
            if q.get("help"):
                lines.append(f"   [Context: {q['help']}]")
            opts = [str(o) for o in (q.get("options") or [])]
            if opts:
                lines.append("   [Options: " + " / ".join(f'"{o}"' for o in opts) + "]")
            parsed = parse_office_cadence(q)
            if parsed:
                metros = parsed.get("metros") or []
                if metros and metros != opts:
                    lines.append(f"   [Locations: {'; '.join(metros)}]")
                if parsed.get("cadence"):
                    lines.append(f"   [Office Expectation: {_format_cadence(parsed['cadence'])}]")
            if q.get("address"):
                lines.append(f"   [Address: {q['address']}]")
    else:
        lines.append("None Found.")
    lines.append("")
    lines.append("--- JOB TEXT START ---")
    lines.append("")
    lines.append(body_text)
    lines.append("")
    lines.append("--- JOB TEXT END ---")
    lines.append("")
    # On a re-fetch, CAPTURE DETAILS keeps describing the ORIGINAL capture (its own
    # source/methods/verification, recovered from the prior file); the new fetch's
    # details live in CAPTURE UPDATE DETAILS below.
    orig = (capture_update or {}).get("original") or {}
    lines += _capture_details_lines(captured=original_captured,
                                    apply_url=orig.get("apply_url") or apply_url,
                                    source=orig.get("source") or source,
                                    posting_id=orig.get("posting_id") or posting_id,
                                    methods=orig.get("methods") or methods,
                                    fs=fs, verification=orig.get("verification"))
    if capture_update:
        lines.append("")
        lines += _capture_update_lines(capture_update, source=source,
                                       posting_id=posting_id, methods=methods, fs=fs)
    return "\n".join(lines) + "\n"


def thin_text(url: str, title: str, company: str, body_text: str, reason: str, ts: str,
              *, meta: dict | None = None, questions: list | None = None,
              field_status: dict | None = None, methods_tried: list | None = None,
              capture_update: dict | None = None) -> str:
    return (
        f"# QUARANTINED — THIN FETCH (needs your review)\n"
        f"# Reason: {reason}\n"
        f"# Fetched: {ts}\n"
        f"# What to do: open this, confirm it's the real job post. If it's incomplete,\n"
        f"#   paste the full job text below the marker, then re-run prep (it will pick it up),\n"
        f"#   OR move this file into 'All Job Posts (full text)/' if it's actually fine.\n\n"
        + build_output_text(url, title, company, body_text, meta=meta, questions=questions,
                            field_status=field_status, methods_tried=methods_tried,
                            captured=ts, capture_update=capture_update)
    )


def failed_text(url: str, error: str, ts: str) -> str:
    """A failed capture keeps only the SNAPSHOT, the body markers (empty, ready
    for a manual paste), and CAPTURE DETAILS — same banners as a real capture."""
    fs = {"description": CAPTURE_FAILED, "compensation": CAPTURE_FAILED,
          "working_location": CAPTURE_FAILED}
    lines = [
        f"# FAILED FETCH (no usable content)\n"
        f"# Error: {error}\n"
        f"# What to do: re-run prep to retry this URL, or paste the full job text below\n"
        f"#   the marker and move this file into 'All Job Posts (full text)/'.\n",
    ]
    lines += _banner("JOB SNAPSHOT", "=")
    lines.append("Company: Unknown")
    lines.append("Role: Unknown Title")
    lines.append(f"Job Posting URL: {url}")
    lines.append("Job Posted At: Unknown")
    lines.append("Job Updated At: Unknown")
    lines.append("")
    lines.append("--- JOB TEXT START ---")
    lines.append("")
    lines.append("")
    lines.append("")
    lines.append("--- JOB TEXT END ---")
    lines.append("")
    lines += _capture_details_lines(captured=ts, apply_url="Not Available",
                                    source="Not Available", posting_id="Not Available",
                                    methods="Not Recorded", fs=fs)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Global capture-history registry (durable, GITIGNORED — lives under the PRIVATE
# root, which .gitignore covers wholesale).
#
# The batch manifest is a per-batch MIRROR; this registry is the source of truth
# for a posting's capture history across batches. Keyed by canonical posting
# identity: `<ats>:<board>:<posting id>` when recognizable (URL aliases —
# employer-hosted deep links, gh_jid query params, board URLs — all resolve to
# the same key), else the canonical normalized URL.
#
# Semantics (2026-07-29 spec, all pinned by tests):
#   - `original_capture` is IMMUTABLE once set — the earliest SUCCESSFUL fetch
#     the registry knows of. The human heading "ORIGINAL" in a capture file means
#     "the earliest capture JAIL can establish from its durable records": a
#     backfilled record (original_source: backfill-earliest-known) may not be the
#     true first-ever fetch, only the earliest provable one.
#   - Every successful network fetch appends a history event and advances
#     `latest_capture`. A FAILED request appends an event but NEVER replaces
#     latest. Skipped (carried-forward) URLs and local re-renders/preview
#     generation are NOT captures and never touch the registry.
# --------------------------------------------------------------------------- #
DEFAULT_REGISTRY_PATH = (Path(__file__).resolve().parents[2]
                         / "PRIVATE__YOUR_FILES_GITIGNORED"
                         / "02-PREP__YOUR_PRIVATE_INFO"
                         / "capture-history-registry.json")
_EMPLOYER_GH_ID_RES = (
    re.compile(r"[?&]gh_jid=(\d{6,})"),
    re.compile(r"/positions?/(\d{6,})(?:[/?#]|$)"),
)


def canonical_capture_key(url: str, apply_url: str | None = None,
                          posting_id=None) -> str:
    """The registry key for a posting: a recognized ATS identity from the URL or
    the (canonical) apply URL, an employer-hosted Greenhouse identity recovered
    from `/positions/<id>` / `?gh_jid=<id>` shapes, else the normalized URL."""
    for u in (url, apply_url):
        k = ats_canonical_key(u) if u else None
        if k:
            return k
    u = str(url or "")
    pid = None
    for rx in _EMPLOYER_GH_ID_RES:
        m = rx.search(u)
        if m:
            pid = m.group(1)
            break
    if pid is None and posting_id is not None and str(posting_id).isdigit() \
            and len(str(posting_id)) >= 6:
        pid = str(posting_id)
    if pid:
        try:
            tokens = _gh_board_tokens_from_domain(u)
        except Exception:
            tokens = []
        if tokens:
            # The suffix-stripped (shortest) brand variant, so acmecareers.com and
            # careers.acme.com alias to the same key.
            return f"greenhouse:{min(tokens, key=len)}:{pid}"
    return normalize_url(u)


# --------------------------------------------------------------------------- #
# Atomic + lock-guarded writes (REQUIRED for the parallel refresh)
#
# Two workers writing the same registry or manifest must never interleave a partial file or lose
# each other's events. Every write goes to a tmp file in the SAME directory (so os.replace is a
# same-filesystem atomic rename) under an advisory flock on a sidecar `.lock`, with a timeout and
# a clear error rather than an indefinite hang.
# --------------------------------------------------------------------------- #
LOCK_TIMEOUT_SECONDS = 30


class LockTimeout(RuntimeError):
    """Raised when a sidecar lock cannot be acquired within the timeout."""


@contextmanager
def file_lock(path, timeout: float = LOCK_TIMEOUT_SECONDS):
    """Advisory exclusive lock on `<path>.lock`, held for the duration of the block."""
    lock_path = Path(str(path) + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    fh = open(lock_path, "a+")
    try:
        while True:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise LockTimeout(
                        f"could not acquire the lock on {lock_path} within {timeout:g}s — another "
                        f"prep worker is still writing it. Wait for that run to finish (or remove "
                        f"the stale lock file if no prep process is running) and retry."
                    )
                time.sleep(0.05)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def atomic_write_text(path, text: str) -> None:
    """Write via a tmp file in the same directory + os.replace, so a reader never sees a
    half-written file and a crash can't truncate the existing one."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def load_capture_registry(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("postings"), dict):
            return data
    except Exception:
        pass
    return {"schema_version": 1, "postings": {}}


def save_capture_registry(path, registry: dict) -> None:
    """Atomic, lock-guarded write of the registry."""
    with file_lock(path):
        atomic_write_text(path, json.dumps(registry, indent=2) + "\n")


def update_capture_registry(path, mutate):
    """Read-modify-write the registry under ONE lock, so two concurrent workers can't lose each
    other's events (the read and the write must not be separated by another writer). `mutate`
    receives the registry dict and mutates it in place; returns the written registry."""
    with file_lock(path):
        registry = load_capture_registry(path)
        mutate(registry)
        atomic_write_text(path, json.dumps(registry, indent=2) + "\n")
        return registry


def resolve_registry_path(registry_path=None):
    """The registry file this process must write. Precedence: an explicit `registry_path`
    argument, then the `JAIL_CAPTURE_REGISTRY` environment variable (the SHARD switch — a
    staging/canary worker points it at its own file so the global registry is untouched), then
    the global default."""
    if registry_path:
        return Path(registry_path)
    env = os.environ.get("JAIL_CAPTURE_REGISTRY", "").strip()
    if env:
        return Path(env)
    return DEFAULT_REGISTRY_PATH


def merge_registry_shards(global_path, shard_paths, accepted_keys):
    """Merge validated shard events into the global registry.

    ONLY postings whose identity is in `accepted_keys` are merged — a staging capture that was
    rejected or found defective must never become the permanent original, so post-validation the
    caller passes exactly the keys it accepted. History is unioned and deduped on
    (key, fetched_at, url); the EARLIEST original wins and stays immutable (an earlier original
    already in the global file is never replaced by a later shard event); `latest_capture` only
    ever advances, and only on a SUCCESSFUL event. Idempotent: merging the same shards again
    changes nothing. Returns the written global registry.
    """
    accepted = set(accepted_keys or ())
    shard_regs = [load_capture_registry(p) for p in (shard_paths or [])]

    def _mutate(registry):
        postings = registry.setdefault("postings", {})
        for shard in shard_regs:
            for key, sposting in (shard.get("postings") or {}).items():
                if key not in accepted:
                    continue
                target = postings.setdefault(key, {})
                history = target.setdefault("history", [])
                seen = {(h.get("fetched_at"), h.get("url")) for h in history}
                for ev in (sposting.get("history") or []):
                    sig = (ev.get("fetched_at"), ev.get("url"))
                    if sig in seen:
                        continue
                    seen.add(sig)
                    history.append(dict(ev))
                history.sort(key=lambda h: (h.get("fetched_at") or ""))
                # Earliest successful event wins as the immutable original.
                cand = sposting.get("original_capture")
                cur = target.get("original_capture")
                if cand and (not cur or (cand.get("fetched_at") or "") < (cur.get("fetched_at") or "")):
                    target["original_capture"] = dict(cand)
                    target["original_source"] = sposting.get("original_source") or "merged-shard"
                elif cur:
                    target.setdefault("original_source", target.get("original_source") or "live")
                # Latest advances only on a successful, strictly newer event.
                slatest = sposting.get("latest_capture")
                if slatest and slatest.get("ok") is not False:
                    cl = target.get("latest_capture")
                    if not cl or (slatest.get("fetched_at") or "") > (cl.get("fetched_at") or ""):
                        target["latest_capture"] = dict(slatest)

    return update_capture_registry(global_path, _mutate)


def record_capture_event(registry: dict, key: str, event: dict, *, success: bool,
                         origin: str = "live", dedupe: bool = False) -> dict:
    """Append one fetch event to a posting's history. The original is set only
    once (immutable thereafter) and only by a SUCCESSFUL fetch; latest advances
    only on success. With `dedupe=True` (backfill), identical (fetched_at, url)
    events collapse — mirrored batch folders contribute one event, not two.
    Returns the posting record."""
    posting = registry.setdefault("postings", {}).setdefault(key, {})
    history = posting.setdefault("history", [])
    dup = dedupe and any(h.get("fetched_at") == event.get("fetched_at")
                         and h.get("url") == event.get("url") for h in history)
    if not dup:
        history.append(dict(event))
    if success:
        if "original_capture" not in posting:
            posting["original_capture"] = dict(event)
            posting["original_source"] = origin
        latest = posting.get("latest_capture")
        if latest is None or (event.get("fetched_at") or "") >= (latest.get("fetched_at") or ""):
            posting["latest_capture"] = dict(event)
    return posting


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
    """Atomic, lock-guarded: a concurrent worker never sees a half-written manifest."""
    with file_lock(path):
        atomic_write_text(path, json.dumps(data, indent=2) + "\n")


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
    # Usable posts whose JOB TITLE could not be captured (the page offered only careers-site
    # branding and no real title was recoverable from JSON-LD / headings / body). Flagged
    # separately and loudly: the capture is still rankable, but its filename and `Role:` line
    # are placeholders, so paste the real title (or re-fetch) before tailoring anything.
    titleless = [x for x in usable if (x.get("field_status") or {}).get("title") == CAPTURE_FAILED]
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
    if titleless:
        lines.append(f"- 🚨 {len(titleless)} usable post(s) whose JOB TITLE could not be captured — see below")
    lines += ["", "## Details"]
    if titleless:
        lines.append("**🚨 Job title not captured (the page gave only careers-site branding):**")
        for x in titleless:
            lines.append(f"- {x.get('company','?')} — title unknown; the capture's `Role:` line and "
                         f"filename are placeholders. Paste the real title into the file or re-fetch "
                         f"before tailoring.  ({x['original_url']})")
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
                  fetch_fallback=None, fallback_label: str | None = None,
                  registry_path=None) -> dict:
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
    # The durable cross-batch capture-history registry (gitignored). The batch
    # manifest below is a mirror; the registry is the source of truth for a
    # posting's Original/Latest capture identity.
    # Shard-aware: an explicit `registry_path`, else JAIL_CAPTURE_REGISTRY, else the global file.
    # A staging/canary worker sets one of those and the global registry is never touched.
    reg_path = resolve_registry_path(registry_path)
    registry = load_capture_registry(reg_path)
    pending_events: list[tuple] = []   # (key, event, success) — flushed under ONE lock at the end
    registry_dirty = False

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
             "has_compensation": None, "has_working_location": None,
             # Employer posting dates (plain YYYY-MM-DD, or None when the source has none) —
             # the rankings `Posted` column reads these back out of the capture.
             "posted_date": None, "updated_date": None,
             # ATS posting id (when the source exposed one) + per-entry capture history —
             # prior fetched_at/source/ats-id records so CAPTURE UPDATE DETAILS can be
             # regenerated faithfully and the ORIGINAL Captured survives later re-fetches.
             "posting_id": None, "capture_history": []}
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

        # Genuine re-fetch of a previously-manifested capture: preserve the prior file's
        # full text (best-verified merge + the CAPTURE UPDATE DETAILS field-and-body
        # comparison need it) BEFORE removing the prior file so we never orphan/duplicate.
        prior_text = None
        prior_body = None
        if prev:
            for rel in (prev.get("output_path"), prev.get("quarantine_path")):
                if not rel:
                    continue
                fp = batch_root / rel
                try:
                    if fp.exists():
                        prior_text = fp.read_text(encoding="utf-8", errors="replace")
                        prior_body = body_from_capture(prior_text)
                        break
                except OSError:
                    continue
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

        # The NETWORK outcome of this fetch, recorded before the merge below can
        # preserve the prior body — a failed request is a failed capture attempt
        # in the registry even when the batch keeps its existing file.
        fetch_success = bool(res.get("ok")) and status != FAILED
        fetch_method = res.get("method")
        fetch_source = (res.get("meta") or {}).get("source")
        fetch_status = status

        # Best-verified merge on a re-fetch (revision #4): never let a truncated /
        # contaminated / blocked new fetch replace a better existing body. The prior
        # body wins when the new one demonstrably degrades it; the new fetch's
        # structured fields still win field-by-field below (posted/updated dates are
        # back-filled from the prior entry only when the new source lost them).
        kept_prior_body = False
        if prior_body and body_would_degrade(prior_body, res.get("body") or ""):
            res = dict(res)
            res["body"] = prior_body
            res["ok"] = True
            if not (res.get("title") or "").strip() or res.get("title") == "Unknown Title":
                res["title"] = prev.get("title") or res.get("title")
            if not (res.get("company") or "").strip() or res.get("company") == "Unknown":
                res["company"] = prev.get("company") or res.get("company")
            kept_prior_body = True
            status, reason, field_status = _evaluate(res)

        # A genuine re-fetch of a previously-manifested URL gets a CAPTURE UPDATE
        # DETAILS block: the ORIGINAL Captured is preserved (first capture-history
        # record, falling back to the prior entry's fetched_at) and Additional Notes
        # come from a normalized-content comparison of the material regions — never
        # body length (revision #5).
        # Record this network fetch in the durable registry (success advances
        # Latest and may seed the immutable Original; a failure is history only).
        res_meta = res.get("meta") or {}
        cap_key = canonical_capture_key(url, apply_url=res_meta.get("apply_url"),
                                        posting_id=res_meta.get("posting_id"))
        posting_prior = dict((registry.get("postings") or {}).get(cap_key) or {})
        prior_original = posting_prior.get("original_capture")
        cap_event = {
            "fetched_at": ts, "url": url, "normalized_url": norm,
            "batch": batch_root.name, "method": fetch_method,
            "source": fetch_source, "posting_id": res_meta.get("posting_id"),
            "status": fetch_status, "ok": fetch_success}
        # Applied to the in-memory copy now (this run's own later reads see it) and replayed
        # under a single lock at the end, so a concurrent worker's events are never lost.
        record_capture_event(registry, cap_key, cap_event, success=fetch_success)
        pending_events.append((cap_key, cap_event, fetch_success))
        registry_dirty = True

        # A LATEST CAPTURE DETAILS block appears when the registry (or the batch
        # manifest mirror) proves at least one earlier successful capture.
        capture_update = None
        history = []
        if prev:
            history = [h for h in (prev.get("capture_history") or []) if isinstance(h, dict)]
            history.append({"fetched_at": prev.get("fetched_at"),
                            "source": prev.get("method"),
                            "posting_id": prev.get("posting_id")})
        if prior_original or prev:
            original_captured = ((prior_original or {}).get("fetched_at")
                                 or (history[0].get("fetched_at") if history else None)
                                 or (prev or {}).get("fetched_at"))
            original_details = _original_capture_details(prior_text if prev else None, prev)
            if prior_original:
                if prior_original.get("source") and not original_details.get("source"):
                    original_details["source"] = _human_source(prior_original["source"])
                if prior_original.get("posting_id") and not original_details.get("posting_id"):
                    original_details["posting_id"] = str(prior_original["posting_id"])
            capture_update = {"original_captured": original_captured,
                              "re_captured": ts,
                              "original": original_details,
                              # Notes are computed AFTER the new capture's fields are
                              # rendered (field-level diff needs both snapshots).
                              "notes": None}

        if status == FAILED:
            fn = failed_filename(url, norm)
            out = dirs["failed"] / fn
            out.write_text(failed_text(url, reason, ts), encoding="utf-8")
            entries.append(base_entry(url, norm, status=FAILED, method=res.get("method"),
                                      error=reason, notes=f"methods tried: {', '.join(methods_tried)}",
                                      methods_tried=methods_tried, capture_history=history,
                                      quarantine_path=_rel(out, batch_root)))
            continue

        title = (res.get("title") or "Unknown Title").strip()
        company = (res.get("company") or "Unknown").strip()
        body = res.get("body") or ""
        method = res.get("method")
        meta = res.get("meta") or {}
        # THE choke point for captured identity: whichever fetch path won above, its
        # (company, title) pair is canonicalized here — once — before the filename, the
        # header, and the manifest entry are derived from it. Idempotent per URL.
        company, title = normalize_capture_identity(
            company, title, url=url, jsonld=meta.get("jsonld_identity"),
            html=meta.get("raw_html"), body=body)
        meta["company"], meta["title"] = company, title
        # The title status was assessed against the RAW scraped title; re-derive it from
        # the canonical one so a branding-only title that could not be recovered shows up
        # as a capture failure in the completeness line, the manifest, and the report.
        field_status["title"] = FOUND if title != "Unknown Title" else CAPTURE_FAILED
        questions = res.get("questions") if res.get("questions") is not None else meta.get("questions")
        missing = missing_hard_fields(field_status)
        has_comp = field_status.get("compensation") == FOUND
        has_loc = field_status.get("working_location") == FOUND
        # Field-by-field best-verified merge: a re-fetch whose source lost the posting
        # dates never erases the previously verified ones.
        if prev:
            if not meta.get("posted_date") and prev.get("posted_date"):
                meta["posted_date"] = prev["posted_date"]
            if not meta.get("updated_date") and prev.get("updated_date"):
                meta["updated_date"] = prev["updated_date"]

        fn = unique_filename(company, title, norm, taken, url)
        taken[fn] = norm
        if capture_update:
            # Two-pass: render the new capture WITHOUT the update block, diff its
            # snapshot fields + body against the prior file, then render for real.
            if prior_text is None:
                capture_update["notes"] = "Previous capture was not available for comparison."
            else:
                provisional = build_output_text(
                    url, title, company, body, meta=meta, questions=questions,
                    field_status=field_status, methods_tried=methods_tried, captured=ts)
                capture_update["notes"] = capture_update_notes(
                    prior_text, provisional, kept_prior_body=kept_prior_body)
        out_text = build_output_text(url, title, company, body, meta=meta, questions=questions,
                                     field_status=field_status, methods_tried=methods_tried,
                                     captured=ts, capture_update=capture_update)
        if status == USABLE:
            out = dirs["source"] / fn
            out.write_text(out_text, encoding="utf-8")
            note_bits = []
            if len(methods_tried) > 1:
                note_bits.append(f"usable after fallback (tried: {', '.join(methods_tried)})")
            if kept_prior_body:
                note_bits.append("re-fetch degraded the body — kept the prior job text "
                                 "(best-verified merge)")
            if field_status.get("title") == CAPTURE_FAILED:
                note_bits.append("job title capture failed — the page gave only site branding "
                                 "and no real role title could be recovered")
            if missing:
                note_bits.append("incomplete capture: " + ", ".join(
                    f"{f.replace('_', '-')} {field_status.get(f)}" for f in missing))
            entries.append(base_entry(url, norm, status=USABLE, method=method, company=company,
                                      title=title, char_count=len(body), notes="; ".join(note_bits),
                                      field_status=field_status, missing_fields=missing,
                                      methods_tried=methods_tried, has_compensation=has_comp,
                                      has_working_location=has_loc,
                                      posted_date=meta.get("posted_date"),
                                      updated_date=meta.get("updated_date"),
                                      posting_id=meta.get("posting_id"),
                                      capture_history=history,
                                      output_path=_rel(out, batch_root)))
        else:  # THIN
            out = dirs["needs_review"] / fn
            out.write_text(thin_text(url, title, company, body, reason, ts, meta=meta,
                                     questions=questions, field_status=field_status,
                                     methods_tried=methods_tried,
                                     capture_update=capture_update), encoding="utf-8")
            entries.append(base_entry(url, norm, status=THIN, method=method, company=company,
                                      title=title, char_count=len(body), notes=reason,
                                      field_status=field_status, missing_fields=missing,
                                      methods_tried=methods_tried, has_compensation=has_comp,
                                      has_working_location=has_loc,
                                      posted_date=meta.get("posted_date"),
                                      updated_date=meta.get("updated_date"),
                                      posting_id=meta.get("posting_id"),
                                      capture_history=history,
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

    # A PARTIAL run over an existing batch must never wipe the other jobs' history:
    # every prior entry whose URL is NOT in this run's input is carried forward into
    # the written manifest UNTOUCHED (field_status, posted dates, capture_history,
    # fetched_at all preserved). Without this, prepping a few newly-added URLs
    # silently deleted every other job's manifest entry — so its next re-fetch was
    # treated as a first capture (original Captured lost, no CAPTURE UPDATE DETAILS).
    carried_untouched = [e for e in manifest.get("entries", [])
                         if e.get("normalized_url") not in seen]
    entries.extend(carried_untouched)

    manifest["entries"] = entries
    manifest["input_count"] = sum(1 for u in urls if u.strip() and not u.strip().startswith("#"))
    manifest["counts"] = _counts(entries)
    manifest["fetched_at"] = ts
    if registry_dirty:
        def _apply(reg):
            # Replayed onto a FRESH read inside the lock (so a concurrent worker's events
            # survive), without dedupe: these events are this run's own and are new by
            # definition — two real fetches landing in the same second are two events.
            for key, event, ok in pending_events:
                record_capture_event(reg, key, event, success=ok)
        update_capture_registry(reg_path, _apply)
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
